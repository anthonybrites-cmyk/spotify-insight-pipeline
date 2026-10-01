"""Retry policy owned by our code (provider SDK retries are disabled)."""

import random
import time

from .config import BACKOFF_BASE_S, BACKOFF_CAP_S, MAX_ATTEMPTS


class Retryable(Exception):
    def __init__(self, message, retry_after=None, usage=None):
        super().__init__(message)
        self.retry_after = retry_after
        self.usage = usage


class InvalidOutput(Exception):
    """The provider answered, but the answer failed validation. Retried at most once."""


class Fatal(Exception):
    """Do not retry (bad request, invalid output after retries...)."""


class AuthFailure(Fatal):
    """Stop the whole run: the key is missing or rejected, or the account is out of credits."""


def backoff(attempt, retry_after=None, rng=random.random):
    if retry_after is not None:
        return min(float(retry_after), BACKOFF_CAP_S)
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1)) * (0.5 + rng())


def run_with_retries(attempt_fn, on_failed_attempt, max_attempts=MAX_ATTEMPTS, max_invalid_retries=1,
                     sleep=time.sleep):
    """attempt_fn(attempt, previous_error) returns a result or raises Retryable/InvalidOutput/Fatal.

    Two separate bounds, per the assignment:
      * transient errors (rate limits, 5xx, timeouts): exponential backoff, at most max_attempts calls;
      * invalid output: retried at most once (with the error available to attempt_fn), then Fatal,
        so the unit is quarantined with the reason.
    on_failed_attempt(attempt, error) is called for every failed attempt so each one is logged.
    """
    last = None
    invalid = 0
    for attempt in range(1, max_attempts + 1):
        try:
            return attempt_fn(attempt, last)
        except InvalidOutput as e:
            last = e
            invalid += 1
            on_failed_attempt(attempt, e)
            if invalid > max_invalid_retries:
                raise Fatal(f"invalid output after {max_invalid_retries} retry: {e}")
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
