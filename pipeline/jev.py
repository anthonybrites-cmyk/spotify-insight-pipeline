"""Minimal HTTP client for TypeSafe's System One endpoint (Jev).

Uses the documented POST /v1/systemone shape. Retries live in retry.py, not here:
this client makes exactly one HTTP attempt per call and classifies the outcome.
"""

import json
import socket
import ssl
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

import certifi

from .config import JEV_MODEL, JEV_TIMEOUT_S, JEV_URL
from .retry import AuthFailure, Fatal, Retryable


@dataclass
class JevResponse:
    answers: dict
    input_tokens: int
    output_tokens: int
    model: str
    request_id: str


# python.org builds of Python on macOS ship without trusted root certificates; use certifi's bundle
# (the same one the Anthropic SDK uses) so TLS verification works without changing the system.
_TLS = ssl.create_default_context(cafile=certifi.where())


class JevClient:
    provider = "typesafe"

    def __init__(self, api_key, model=JEV_MODEL, url=JEV_URL, timeout=JEV_TIMEOUT_S):
        self.api_key = api_key
        self.model = model
        self.url = url
        self.timeout = timeout

    def ask(self, state, questions):
        body = json.dumps({"state": state, "model": self.model, "questions": questions},
                          ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        local_id = "local-" + uuid.uuid4().hex
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_TLS) as response:
                payload = json.loads(response.read().decode("utf-8"))
                request_id = (response.headers.get("x-request-id") or response.headers.get("request-id")
                              or local_id)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if e.code in (401, 403):
                raise AuthFailure(f"TypeSafe rejected the API key ({e.code})")
            if e.code == 402 or "credit" in detail.lower() or "balance" in detail.lower():
                raise AuthFailure(f"TypeSafe: payment or credits problem ({e.code}): {detail}")
            if e.code in (408, 409, 429, 529) or e.code >= 500:
                raise Retryable(f"HTTP {e.code}: {detail}", retry_after=e.headers.get("retry-after"))
            raise Fatal(f"HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLError):
                # A certificate problem is a setup error, not a transient one: stop the run instead of retrying.
                raise AuthFailure(f"TLS verification failed for {self.url}: {e.reason}")
            raise Retryable(f"network: {e}")
        except (socket.timeout, TimeoutError, ConnectionError) as e:
            raise Retryable(f"network: {e}")
        except json.JSONDecodeError as e:
            raise Retryable(f"unparseable response: {e}")
        usage = payload.get("usage") or {}
        return JevResponse(answers=payload.get("answers") or {},
                           input_tokens=int(usage.get("input_tokens", 0)),
                           output_tokens=int(usage.get("output_tokens", 0)),
                           model=payload.get("model", self.model), request_id=request_id)
