"""Claude calls for verify / group-taxonomy / memo, with our own retries, budget and logging.

Every request and response is saved under <run>/<stage>/handoffs/ before it is used.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import anthropic

from .budget import cost_usd
from .config import (CLAUDE_PRICES, CLAUDE_BASE_URL, CLAUDE_EFFORT, CLAUDE_MAX_TOKENS, CLAUDE_MODEL, CLAUDE_PRICE_IN,
                     CLAUDE_PRICE_OUT, CLAUDE_TIMEOUT_S)
from .retry import AuthFailure, Fatal, InvalidOutput, Retryable, run_with_retries
from .store import write_json


class ClaudeClient:
    provider = "anthropic"

    def __init__(self, api_key, model=CLAUDE_MODEL, effort=CLAUDE_EFFORT, max_tokens=CLAUDE_MAX_TOKENS):
        # Explicit base_url and api_key so a shell ANTHROPIC_BASE_URL / auth token is never picked up.
        self.client = anthropic.Anthropic(api_key=api_key, base_url=CLAUDE_BASE_URL, max_retries=0,
                                          timeout=CLAUDE_TIMEOUT_S)
        self.model = model
        self.effort = effort          # reasoning effort for every role this client serves (part of each config tag)
        self.max_tokens = max_tokens  # output-token cap per request (thinking tokens count as output)

    def params(self, system, user, schema=None, max_tokens=None, effort=None):
        max_tokens = max_tokens or self.max_tokens
        effort = effort or self.effort
        params = {"model": self.model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}], "output_config": {}}
        if effort == "none":
            # Haiku 4.5 rejects the effort parameter; running it without extended thinking is its cheapest setting.
            pass
        else:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"]["effort"] = effort
        if schema is not None:
            params["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        if not params["output_config"]:
            del params["output_config"]
        return params

    # Message Batches API (50% price, asynchronous). Errors here are account/setup problems.
    def create_batch(self, requests):
        """requests: list of (custom_id, params). Returns the batch ID."""
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        try:
            batch = self.client.messages.batches.create(requests=[
                Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**p)) for cid, p in requests])
        except anthropic.AuthenticationError as e:
            raise AuthFailure(f"Anthropic rejected the API key: {e}")
        except anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower():
                raise AuthFailure(f"Anthropic: credit balance too low ({e})")
            raise Fatal(f"batch rejected: {e}")
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError,
                anthropic.InternalServerError) as e:
            raise Retryable(f"batch create: {e}")
        return batch.id

    def batch_status(self, batch_id):
        batch = self.client.messages.batches.retrieve(batch_id)
        return batch.processing_status

    def batch_results(self, batch_id):
        """Yields (custom_id, outcome dict) with the same shape create() returns, or an error."""
        for item in self.client.messages.batches.results(batch_id):
            r = item.result
            if r.type == "succeeded":
                m = r.message
                yield item.custom_id, {"ok": True, "request_id": m.id, "model": m.model, "stop_reason": m.stop_reason,
                                       "text": "".join(b.text for b in m.content if b.type == "text"),
                                       "input_tokens": m.usage.input_tokens, "output_tokens": m.usage.output_tokens}
            else:
                detail = getattr(getattr(r, "error", None), "type", None) or r.type
                yield item.custom_id, {"ok": False, "error": f"batch result {r.type}: {detail}"}

    def create(self, system, user, schema=None, max_tokens=None, effort=None):
        params = self.params(system, user, schema, max_tokens, effort)
        try:
            response = self.client.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise AuthFailure(f"Anthropic rejected the API key: {e}")
        except anthropic.PermissionDeniedError as e:
            raise AuthFailure(f"Anthropic permission denied: {e}")
        except anthropic.BadRequestError as e:
            # The API reports an exhausted prepaid balance as a 400; stop the run instead of failing one batch.
            if "credit balance" in str(e).lower():
                raise AuthFailure(f"Anthropic: credit balance too low ({e})")
            raise Fatal(f"bad request: {e}")
        except anthropic.RateLimitError as e:
            raise Retryable(f"rate limited: {e}", retry_after=e.response.headers.get("retry-after"))
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 or e.status_code in (408, 409, 529):
                raise Retryable(f"HTTP {e.status_code}: {e}")
            raise Fatal(f"HTTP {e.status_code}: {e}")
        except anthropic.APITimeoutError as e:
            raise Retryable(f"network: request timed out (may have been processed and billed): {e}")
        except anthropic.APIConnectionError as e:
            raise Retryable(f"network: {e}")
        text = "".join(b.text for b in response.content if b.type == "text")
        u = response.usage
        return {"request_id": getattr(response, "_request_id", None) or f"local-{uuid.uuid4().hex}",
                "model": response.model, "stop_reason": response.stop_reason, "text": text,
                "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                # Mutually exclusive billing categories reported by the API (input_tokens excludes cached ones).
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                "effort": params.get("output_config", {}).get("effort", "none"), "max_tokens": params["max_tokens"]}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _usage_fields(response):
    return {"cache_creation_input_tokens": response.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": response.get("cache_read_input_tokens", 0)}


def handoff_ref(handoff_dir, name):
    return f"{handoff_dir.parent.name}/{handoff_dir.name}/{name}"


def estimate_tokens(text):
    # Conservative: 1 token per 2.5 characters of prompt.
    return int(len(text) / 2.5) + 500


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def call(client, budget, calls, handoff_dir, name, role, phase, label_config, review_ids, system, user,
         schema=None, validate=None, max_tokens=None, max_attempts=4, effort=None, lock=None, max_invalid_retries=1):
    """One logical request with retries. Saves request/response handoffs; returns (parsed, response).

    Pass a shared `lock` when several threads write to the same call log. Pass max_invalid_retries=0 when this
    call is itself the single retry of an invalid answer (e.g. from a Batch API request).
    """
    lock = lock or _NoLock()
    price_in, price_out = CLAUDE_PRICES.get(client.model, (CLAUDE_PRICE_IN, CLAUDE_PRICE_OUT))
    max_tokens = max_tokens or getattr(client, "max_tokens", CLAUDE_MAX_TOKENS)
    effort = effort or getattr(client, "effort", CLAUDE_EFFORT)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    write_json(handoff_dir / f"{name}.request.json",
               {"model": client.model, "role": role, "review_ids": review_ids, "system": system, "user": user,
                "schema": schema, "max_tokens": max_tokens, "effort": effort, "label_config": label_config})
    state = {}

    def attempt(n, previous_error):
        state.clear()
        state["timing"] = {"started_at": _utc_now()}
        t0 = time.monotonic()
        prompt = user
        if isinstance(previous_error, InvalidOutput):
            # The single invalid-output retry carries the validation error back to the model.
            prompt = (user + "\n\nYour previous response was rejected by validation: " + str(previous_error)[:500]
                      + "\nReturn a corrected, complete response.")
        # Reserve the worst case: full input estimate plus max_tokens of output.
        reservation = budget.reserve(cost_usd(estimate_tokens(system + prompt), max_tokens,
                                              price_in, price_out))
        try:
            response = client.create(system, prompt, schema, max_tokens, effort)
        except BaseException:
            budget.release(reservation)
            state["timing"]["duration_ms"] = round((time.monotonic() - t0) * 1000)
            raise
        state["timing"]["duration_ms"] = round((time.monotonic() - t0) * 1000)
        cost = cost_usd(response["input_tokens"], response["output_tokens"], price_in, price_out) \
            + cost_usd(response.get("cache_creation_input_tokens", 0), 0, price_in * Decimal("1.25"), 0) \
            + cost_usd(response.get("cache_read_input_tokens", 0), 0, price_in * Decimal("0.1"), 0)
        budget.commit(reservation, cost, role, response["request_id"])
        response["cost_usd"] = str(cost)
        state["response"] = response
        state["attempt"] = n
        write_json(handoff_dir / f"{name}.response.{n}.json", response)
        if response["stop_reason"] == "refusal":
            raise Fatal("model refused")
        if response["stop_reason"] == "max_tokens":
            raise InvalidOutput("truncated at max_tokens")
        try:
            parsed = json.loads(response["text"]) if schema is not None else response["text"]
            if validate is not None:
                parsed = validate(parsed)
        except ValueError as e:  # includes json.JSONDecodeError
            raise InvalidOutput(f"invalid output: {e}")
        return parsed

    def failed(n, error):
        response = state.get("response") or {}
        with lock:
            _log_failed(n, error, response)

    def _log_failed(n, error, response):
        timing = state.get("timing", {})
        extra = {"possible_unlogged_charge": True} if "timed out" in str(error).lower() else {}
        calls.write({**extra, **_usage_fields(response), "started_at": timing.get("started_at"),
                     "duration_ms": timing.get("duration_ms"), "effort": effort, "max_tokens": max_tokens,
                     "request_id": response.get("request_id") or f"local-failed-{uuid.uuid4().hex}",
                     "role": role, "review_ids": review_ids, "model": response.get("model", client.model),
                     "phase": phase, "outcome": "failed", "label_config": label_config,
                     "input_tokens": response.get("input_tokens", 0),
                     "output_tokens": response.get("output_tokens", 0), "usage_available": bool(response),
                     "attempt": n, "error": str(error)[:300], "handoff": handoff_ref(handoff_dir, name)})
        calls.flush()

    def _log_ok(response):
        timing = state.get("timing", {})
        calls.write({**_usage_fields(response), "started_at": timing.get("started_at"),
                     "duration_ms": timing.get("duration_ms"), "effort": effort, "max_tokens": max_tokens,
                     "attempt": state.get("attempt"), "request_id": response["request_id"], "role": role, "review_ids": review_ids,
                     "model": response["model"], "phase": phase, "outcome": "succeeded", "label_config": label_config,
                     "input_tokens": response["input_tokens"], "output_tokens": response["output_tokens"],
                     "usage_available": True, "cost_usd": response["cost_usd"],
                     "handoff": handoff_ref(handoff_dir, name)})
        calls.flush()
        budget.flush()

    parsed = run_with_retries(attempt, failed, max_attempts=max_attempts, max_invalid_retries=max_invalid_retries)
    response = state["response"]
    with lock:
        _log_ok(response)
    write_json(handoff_dir / f"{name}.parsed.json", parsed if not isinstance(parsed, str) else {"text": parsed})
    return parsed, response
