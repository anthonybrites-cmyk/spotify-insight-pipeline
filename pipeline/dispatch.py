"""Concurrent dispatch of single-review Jev requests with retries, budget and graceful stop.

Workers only talk to the network. The main thread is the single writer of the
call log and the stage results, so saved state is never interleaved or partial.
"""

import signal
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from .budget import BudgetExceeded, cost_usd
from .config import JEV_PRICE_IN, JEV_PRICE_OUT, JEV_RPS, JEV_WORKERS
from .retry import AuthFailure, Fatal, InvalidOutput, RateLimiter, run_with_retries


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class StopFlag:
    """First Ctrl-C asks for a graceful stop (finish in-flight calls, save); a second one exits."""

    def __init__(self, max_minutes=None):
        self.reason = None
        self._previous = None
        self.deadline = time.monotonic() + max_minutes * 60 if max_minutes else None

    def check_deadline(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            self.set("time_cap")

    def set(self, reason):
        if self.reason is None:
            self.reason = reason

    def __enter__(self):
        def handler(signum, frame):
            if self.reason == "interrupted":
                raise KeyboardInterrupt
            self.set("interrupted")
            print("\nInterrupt received: finishing in-flight calls and saving progress "
                  "(press Ctrl-C again to abort immediately).", flush=True)
        if threading.current_thread() is threading.main_thread():
            self._previous = signal.signal(signal.SIGINT, handler)
        return self

    def __exit__(self, *exc):
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)


@dataclass
class Task:
    key: str            # unit hash
    review_id: str      # the original ID actually sent
    state: dict
    questions: dict
    text_len: int


@dataclass
class Outcome:
    task: Task
    response: object = None
    error: str = None
    fatal_auth: bool = False
    budget_stop: bool = False
    events: list = field(default_factory=list)
    cost: Decimal = Decimal(0)
    parsed: object = None
    attempts: int = 0
    timing: dict = field(default_factory=dict)


class TokenEstimator:
    """Conservative pre-call input estimate: learned question overhead + 1 token per 2 chars."""

    def __init__(self, overhead=1500):
        self.overhead = overhead
        self.lock = threading.Lock()

    def estimate(self, task):
        return self.overhead + task.text_len // 2 + 50 * len(task.questions)

    def observe(self, task, input_tokens):
        with self.lock:
            self.overhead = max(self.overhead, input_tokens - task.text_len // 4 + 100)


def run_tasks(tasks, client, budget, role, phase, label_config, validate, on_outcome, stop, calls,
              workers=JEV_WORKERS, rps=JEV_RPS, max_new=None, log=print, sleep=time.sleep):
    """Dispatch tasks; returns the stop reason or None when all tasks were processed.

    validate(task, response) runs in the worker and returns parsed labels or raises
    ValueError (the attempt is logged as failed and retried once; a second invalid answer
    quarantines the task). Transient errors use bounded backoff.
    on_outcome(outcome) is called on the main thread for each finished task and may
    call stop.set(reason) (e.g. the early cost gate).
    """
    limiter = RateLimiter(rps)
    estimator = TokenEstimator()

    def work(task):
        outcome = Outcome(task=task)
        billed = {}

        def attempt(n, previous_error):
            billed.clear()
            outcome.attempts = n
            outcome.timing = {"started_at": utc_now()}
            t0 = time.monotonic()
            if stop.reason in ("auth", "budget"):
                raise Fatal("stopped before sending")
            limiter.wait()
            reservation = budget.reserve(cost_usd(estimator.estimate(task), 0, JEV_PRICE_IN, JEV_PRICE_OUT))
            try:
                response = client.ask(task.state, task.questions)
            except BaseException:
                budget.release(reservation)
                outcome.timing["duration_ms"] = round((time.monotonic() - t0) * 1000)
                raise
            outcome.timing["duration_ms"] = round((time.monotonic() - t0) * 1000)
            actual = cost_usd(response.input_tokens, response.output_tokens, JEV_PRICE_IN, JEV_PRICE_OUT)
            budget.commit(reservation, actual, role, response.request_id)
            estimator.observe(task, response.input_tokens)
            outcome.cost += actual
            try:
                outcome.parsed = validate(task, response)
            except ValueError as e:
                # Billed but unusable output: log it as a failed call with its real usage, then retry.
                billed.update(request_id=response.request_id, model=response.model,
                              input_tokens=response.input_tokens, output_tokens=response.output_tokens)
                raise InvalidOutput(f"invalid_answer: {e}")
            return response

        def failed(n, error):
            event = {"request_id": billed.get("request_id") or f"local-failed-{uuid.uuid4().hex}",
                     "attempt": n, "error": str(error)[:300], **getattr(outcome, "timing", {})}
            if "timed out" in str(error).lower() or "timeout" in str(error).lower():
                # The provider may have processed (and billed) a request we never saw answered.
                event["possible_unlogged_charge"] = True
            event.update({k: v for k, v in billed.items() if k != "request_id"})
            outcome.events.append(event)

        try:
            outcome.response = run_with_retries(attempt, failed, sleep=sleep)
        except AuthFailure as e:
            outcome.error, outcome.fatal_auth = str(e), True
        except BudgetExceeded as e:
            outcome.error, outcome.budget_stop = str(e), True
        except Fatal as e:
            outcome.error = str(e)
        return outcome

    def record(outcome):
        task = outcome.task
        for ev in outcome.events:
            has_usage = "input_tokens" in ev
            calls.write({"request_id": ev["request_id"], "role": role, "review_ids": [task.review_id],
                         "model": ev.get("model", client.model), "phase": phase, "outcome": "failed",
                         "label_config": label_config, "input_tokens": ev.get("input_tokens", 0),
                         "output_tokens": ev.get("output_tokens", 0), "usage_available": has_usage,
                         "attempt": ev["attempt"], "error": ev["error"], "started_at": ev.get("started_at"),
                         "duration_ms": ev.get("duration_ms"),
                         **({"possible_unlogged_charge": True} if ev.get("possible_unlogged_charge") else {})})
        if outcome.response is not None:
            r = outcome.response
            calls.write({"request_id": r.request_id, "role": role, "review_ids": [task.review_id],
                         "model": r.model, "phase": phase, "outcome": "succeeded", "label_config": label_config,
                         "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                         "usage_available": True, "cost_usd": str(outcome.cost), "attempt": outcome.attempts,
                         "started_at": outcome.timing.get("started_at"), "duration_ms": outcome.timing.get("duration_ms")})
        if outcome.fatal_auth:
            stop.set("auth")
        if outcome.budget_stop:
            stop.set("budget")
        on_outcome(outcome)

    iterator = iter(tasks)
    submitted = 0
    in_flight = set()
    last_flush = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            if hasattr(stop, "check_deadline"):
                stop.check_deadline()
            while (stop.reason is None and len(in_flight) < workers * 2
                   and (max_new is None or submitted < max_new)):
                task = next(iterator, None)
                if task is None:
                    break
                in_flight.add(pool.submit(work, task))
                submitted += 1
            if not in_flight:
                break
            done, in_flight = wait(in_flight, timeout=5, return_when=FIRST_COMPLETED)
            for future in done:
                record(future.result())
            if time.monotonic() - last_flush > 2:
                calls.flush()
                budget.flush()
                last_flush = time.monotonic()
    calls.flush()
    budget.flush()
    if stop.reason is None and max_new is not None and submitted >= max_new and next(iterator, None) is not None:
        stop.set("stop_after")
    return stop.reason
