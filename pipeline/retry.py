"""Retry policy owned by our code (provider SDK retries are disabled)."""

import random
import time

from .config import BACKOFF_BASE_S, BACKOFF_CAP_S, MAX_ATTEMPTS


class Retryable(Exception):
    def __init__(self, message, retry_after=None, usage=None):
        super().__init__(message)
        self.retry_after = retry_after
        self.usage = usage


class Fatal(Exception):
    """Do not retry (bad request, invalid output after retries...)."""


class AuthFailure(Fatal):
    """Stop the whole run: the key is missing or rejected."""


def backoff(attempt, retry_after=None, rng=random.random):
    if retry_after is not None:
        return min(float(retry_after), BACKOFF_CAP_S)
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1)) * (0.5 + rng())


def run_with_retries(attempt_fn, on_failed_attempt, max_attempts=MAX_ATTEMPTS, sleep=time.sleep):
    """attempt_fn(attempt) returns a result or raises Retryable/Fatal.

    on_failed_attempt(attempt, error) is called for every failed attempt so that
    each one is logged as a failed call.
    """
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            return attempt_fn(attempt)
        except Retryable as e:
            last = e
            on_failed_attempt(attempt, e)
            if attempt < max_attempts:
                sleep(backoff(attempt, e.retry_after))
        except Fatal as e:
            on_failed_attempt(attempt, e)
            raise
    raise Fatal(f"gave up after {max_attempts} attempts: {last}")


class RateLimiter:
    """Simple token bucket shared by worker threads."""

    def __init__(self, rate_per_s):
        import threading
        self.interval = 1.0 / rate_per_s
        self.next_time = time.monotonic()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_time)
            self.next_time = slot + self.interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)
