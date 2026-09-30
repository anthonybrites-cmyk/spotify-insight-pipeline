"""Claude calls for verify / group-taxonomy / memo, with our own retries, budget and logging.

Every request and response is saved under <run>/<stage>/handoffs/ before it is used.
"""

import json
import uuid

import anthropic

from .budget import cost_usd
from .config import (CLAUDE_BASE_URL, CLAUDE_EFFORT, CLAUDE_MAX_TOKENS, CLAUDE_MODEL, CLAUDE_PRICE_IN,
                     CLAUDE_PRICE_OUT, CLAUDE_TIMEOUT_S)
from .retry import AuthFailure, Fatal, Retryable, run_with_retries
from .store import write_json


class ClaudeClient:
    provider = "anthropic"

    def __init__(self, api_key, model=CLAUDE_MODEL):
        # Explicit base_url and api_key so a shell ANTHROPIC_BASE_URL / auth token is never picked up.
        self.client = anthropic.Anthropic(api_key=api_key, base_url=CLAUDE_BASE_URL, max_retries=0,
                                          timeout=CLAUDE_TIMEOUT_S)
        self.model = model

    def create(self, system, user, schema=None, max_tokens=CLAUDE_MAX_TOKENS):
        params = {"model": self.model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}],
                  "thinking": {"type": "adaptive"}, "output_config": {"effort": CLAUDE_EFFORT}}
        if schema is not None:
            params["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        try:
            response = self.client.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise AuthFailure(f"Anthropic rejected the API key: {e}")
        except anthropic.PermissionDeniedError as e:
            raise AuthFailure(f"Anthropic permission denied: {e}")
        except anthropic.BadRequestError as e:
            raise Fatal(f"bad request: {e}")
        except anthropic.RateLimitError as e:
            raise Retryable(f"rate limited: {e}", retry_after=e.response.headers.get("retry-after"))
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 or e.status_code in (408, 409, 529):
                raise Retryable(f"HTTP {e.status_code}: {e}")
            raise Fatal(f"HTTP {e.status_code}: {e}")
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            raise Retryable(f"network: {e}")
        text = "".join(b.text for b in response.content if b.type == "text")
        return {"request_id": getattr(response, "_request_id", None) or f"local-{uuid.uuid4().hex}",
                "model": response.model, "stop_reason": response.stop_reason, "text": text,
                "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}


def handoff_ref(handoff_dir, name):
    return f"{handoff_dir.parent.name}/{handoff_dir.name}/{name}"


def estimate_tokens(text):
    # Conservative: 1 token per 2.5 characters of prompt.
    return int(len(text) / 2.5) + 500


def call(client, budget, calls, handoff_dir, name, role, phase, label_config, review_ids, system, user,
         schema=None, validate=None, max_tokens=CLAUDE_MAX_TOKENS, max_attempts=3):
    """One logical request with retries. Saves request/response handoffs; returns (parsed, response)."""
    handoff_dir.mkdir(parents=True, exist_ok=True)
    write_json(handoff_dir / f"{name}.request.json",
               {"model": client.model, "role": role, "review_ids": review_ids, "system": system, "user": user,
                "schema": schema, "max_tokens": max_tokens, "label_config": label_config})
    state = {}

    def attempt(n):
        state.clear()
        # Reserve the worst case: full input estimate plus max_tokens of output.
        reservation = budget.reserve(cost_usd(estimate_tokens(system + user), max_tokens,
                                              CLAUDE_PRICE_IN, CLAUDE_PRICE_OUT))
        try:
            response = client.create(system, user, schema, max_tokens)
        except BaseException:
            budget.release(reservation)
            raise
        cost = cost_usd(response["input_tokens"], response["output_tokens"], CLAUDE_PRICE_IN, CLAUDE_PRICE_OUT)
        budget.commit(reservation, cost, role, response["request_id"])
        response["cost_usd"] = str(cost)
        state["response"] = response
        write_json(handoff_dir / f"{name}.response.{n}.json", response)
        if response["stop_reason"] == "refusal":
            raise Fatal("model refused")
        if response["stop_reason"] == "max_tokens":
            raise Retryable("truncated at max_tokens")
        parsed = json.loads(response["text"]) if schema is not None else response["text"]
        if validate is not None:
            try:
                parsed = validate(parsed)
            except ValueError as e:
                raise Retryable(f"invalid output: {e}")
        return parsed

    def failed(n, error):
        response = state.get("response") or {}
        calls.write({"request_id": response.get("request_id") or f"local-failed-{uuid.uuid4().hex}",
                     "role": role, "review_ids": review_ids, "model": response.get("model", client.model),
                     "phase": phase, "outcome": "failed", "label_config": label_config,
                     "input_tokens": response.get("input_tokens", 0),
                     "output_tokens": response.get("output_tokens", 0), "usage_available": bool(response),
                     "attempt": n, "error": str(error)[:300], "handoff": handoff_ref(handoff_dir, name)})
        calls.flush()

    parsed = run_with_retries(attempt, failed, max_attempts=max_attempts)
    response = state["response"]
    calls.write({"request_id": response["request_id"], "role": role, "review_ids": review_ids,
                 "model": response["model"], "phase": phase, "outcome": "succeeded", "label_config": label_config,
                 "input_tokens": response["input_tokens"], "output_tokens": response["output_tokens"],
                 "usage_available": True, "cost_usd": response["cost_usd"], "handoff": handoff_ref(handoff_dir, name)})
    calls.flush()
    budget.flush()
    write_json(handoff_dir / f"{name}.parsed.json", parsed if not isinstance(parsed, str) else {"text": parsed})
    return parsed, response
