"""Spending limits enforced in code.

Every model call reserves a conservative cost estimate before it is sent and is
reconciled to the provider-reported usage afterwards. A call whose reservation
would push committed + reserved spend past the cap is never sent.

Ledgers are per budget group (e.g. "dev" shared by the 500 and 10k runs, "full"
for the graded run) and persist across runs and resumes in budgets/<group>.jsonl.
"""

import threading
from decimal import Decimal

from .config import REPO
from .store import JsonlAppender, read_jsonl

MILLION = Decimal(1_000_000)


class BudgetExceeded(Exception):
    pass


class EarlyGateHalt(Exception):
    pass


def cost_usd(input_tokens, output_tokens, price_in, price_out):
    return (Decimal(input_tokens) * price_in + Decimal(output_tokens) * price_out) / MILLION


class Budget:
    def __init__(self, group, cap_usd, run_name, ledger_dir=REPO / "budgets"):
        self.group = group
        self.cap = Decimal(str(cap_usd))
        self.run_name = run_name
        self.path = ledger_dir / f"{group}.jsonl"
        self.lock = threading.Lock()
        self.committed = Decimal(0)
        self.run_committed = Decimal(0)
        for entry in read_jsonl(self.path):
            amount = Decimal(entry["cost_usd"])
            self.committed += amount
            if entry["run"] == run_name:
                self.run_committed += amount
        self.reserved = Decimal(0)
        self.ledger = JsonlAppender(self.path)

    def reserve(self, estimate):
        estimate = Decimal(estimate)
        with self.lock:
            if self.committed + self.reserved + estimate > self.cap:
                raise BudgetExceeded(
                    f"budget '{self.group}': committed ${self.committed:.4f} + in-flight ${self.reserved:.4f} "
                    f"+ next call ${estimate:.4f} would exceed cap ${self.cap}")
            self.reserved += estimate
        return estimate

    def commit(self, reservation, actual, role, request_id):
        actual = Decimal(actual)
        with self.lock:
            self.reserved -= reservation
            self.committed += actual
            self.run_committed += actual
            self.ledger.write({"run": self.run_name, "role": role, "request_id": request_id,
                               "cost_usd": str(actual)})

    def release(self, reservation):
        with self.lock:
            self.reserved -= reservation

    def flush(self):
        with self.lock:
            self.ledger.flush()

    def close(self):
        with self.lock:
            self.ledger.close()

    def summary(self):
        with self.lock:
            return {"group": self.group, "cap_usd": str(self.cap), "committed_usd": str(self.committed),
                    "this_run_usd": str(self.run_committed), "remaining_usd": str(self.cap - self.committed)}

    def early_gate(self, run_spend, fraction_done, gate_fraction):
        """At the gate fraction of units, spend so far must be within the same fraction of the cap."""
        allowed = self.cap * gate_fraction
        projected = run_spend / fraction_done if fraction_done else None
        return {"fraction_done": str(fraction_done), "spend_at_gate_usd": str(run_spend),
                "allowed_at_gate_usd": str(allowed),
                "linear_projection_usd": str(projected.quantize(Decimal("0.0001"))) if projected is not None else None,
                "passed": run_spend <= allowed}
