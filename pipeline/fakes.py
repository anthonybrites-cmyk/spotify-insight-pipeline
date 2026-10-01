"""OFFLINE FAKE PROVIDERS FOR TESTS ONLY.

They let the whole pipeline run without keys or spend so plumbing (resume, budget,
validation, export, checker) can be tested. Their model IDs contain "fake", every
label_config therefore contains "fake", and export refuses fake records unless
--allow-fake is passed. Fake output is never evidence of a real run.
"""

import hashlib
import itertools
import uuid
import json
import re

from .jev import JevResponse

_counter = itertools.count()

KEYWORDS = [
    ("access", r"log ?in|password|sign ?in|account"), ("billing", r"premium|charge|price|subscri|refund"),
    ("downloads", r"download|offline"), ("playback", r"crash|stop|pause|skip|play|lag|freez"),
    ("catalog", r"song|artist|search|lyrics|recommend"), ("usability", r"ads?\b|shuffle|queue|playlist|button"),
    ("support", r"support|customer service"),
]


class FakeJev:
    provider = "fake"
    model = "fake-jev-0"

    def __init__(self, fail_every=0, invalid_every=0, always_invalid_every=0, low_conf_every=0):
        self.low_conf_every = low_conf_every  # every Nth text (by hash) answers with confidence 0.3
        self.fail_every = fail_every
        self.invalid_every = invalid_every            # first attempt invalid -> recovered by the one retry
        self.always_invalid_every = always_invalid_every  # every attempt invalid -> quarantined
        self.calls = 0
        self.sent = []
        self.attempts = {}

    def ask(self, state, questions):
        from .retry import Retryable
        self.calls += 1
        self.sent.append((json.loads(json.dumps(state)), sorted(questions)))
        # Deterministic per text: the first attempt of every Nth distinct text fails / is invalid.
        raw = state["review"]
        text = raw.lower()
        n = self.attempts[raw] = self.attempts.get(raw, 0) + 1
        bucket = int(hashlib.sha256(raw.encode()).hexdigest(), 16)
        if self.fail_every and n == 1 and bucket % self.fail_every == 0:
            raise Retryable("fake transient 529")
        conf = 0.3 if self.low_conf_every and bucket % self.low_conf_every == 3 else 0.8
        invalid_now = ((bool(self.invalid_every) and n == 1 and bucket % self.invalid_every == 1)
                       or (bool(self.always_invalid_every) and bucket % self.always_invalid_every == 2))
        answers = {}
        for key, q in questions.items():
            if q["type"] == "choice":
                options = list(q["criteria"])
                pick = options[-1] if key == "topic" else options[0]
                if key == "topic":
                    pick = next((t for t, pat in KEYWORDS if re.search(pat, text)), "other")
                elif key == "intent":
                    pick = ("cancellation" if re.search(r"uninstall|cancel|leaving", text) else
                            "complaint" if re.search(r"bad|worst|hate|crash|not|can't|cant|stop|ads", text) else
                            "praise" if re.search(r"good|great|love|nice|best|excellent|awesome", text) else "unclear")
                elif key == "severity":
                    pick = "4" if re.search(r"can't|cannot|won't|doesn't", text) else "2"
                if invalid_now and key == "topic":
                    pick = "not-a-topic"
                answers[key] = {"type": "choice", "choice": pick, "confidence": conf,
                                "probabilities": {o: (1.0 if o == pick else 0.0) for o in options}}
            elif q["type"] == "score":
                answers[key] = {"type": "score", "score": 2.0 if "bad" not in text else 0.5, "confidence": 0.8,
                                "probabilities": {str(i): (1.0 if i == 2 else 0.0) for i in range(len(q["criteria"]))}}
            else:
                answers[key] = {"type": "noul", "noul": 0.1}
        return JevResponse(answers=answers, input_tokens=800 + len(text) // 4, output_tokens=20,
                           model=self.model, request_id=f"fake-jev-{uuid.uuid4().hex}")


class FakeClaude:
    provider = "fake"
    model = "fake-claude-0"
    effort = "medium"
    max_tokens = 16000

    def __init__(self, memo_text=None, fail_with=None, bad_quote_ids=(), polls_before_end=0):
        self.memo_text = memo_text
        self.requests = []
        self.fail_with = fail_with  # an exception instance to raise (tests for clean stops)
        self.bad_quote_ids = set(bad_quote_ids)  # fallback answers a non-substring quote for these the first time
        self.quote_attempts = {}
        self.batches = {}
        self.polls_before_end = polls_before_end
        self.polls = 0

    def params(self, system, user, schema=None, max_tokens=None, effort=None):
        return {"system": system, "user": user, "schema": schema, "max_tokens": max_tokens, "effort": effort}

    def create_batch(self, requests):
        batch_id = f"fake-batch-{uuid.uuid4().hex[:8]}"
        self.batches[batch_id] = requests
        return batch_id

    def batch_status(self, batch_id):
        self.polls += 1
        return "ended" if self.polls > self.polls_before_end else "in_progress"

    def batch_results(self, batch_id):
        for cid, p in self.batches[batch_id]:
            r = self.create(p["system"], p["user"], p["schema"], p["max_tokens"], p["effort"])
            yield cid, {"ok": True, "request_id": "msg_" + uuid.uuid4().hex, "model": r["model"],
                        "stop_reason": r["stop_reason"], "text": r["text"], "input_tokens": r["input_tokens"],
                        "output_tokens": r["output_tokens"]}

    def create(self, system, user, schema=None, max_tokens=None, effort=None):
        if self.fail_with is not None:
            raise self.fail_with
        self.requests.append(user)
        if schema is not None and "results" in schema["properties"]:
            reviews = json.loads(user.split("<reviews>\n", 1)[1].split("\n</reviews>", 1)[0])
            item = schema["properties"]["results"]["items"]["properties"]
            if "evidence_quote" in item:  # fallback relabel
                results = []
                for r in reviews:
                    n = self.quote_attempts[r["review_id"]] = self.quote_attempts.get(r["review_id"], 0) + 1
                    quote = r["text"][:20] if not (r["review_id"] in self.bad_quote_ids and n == 1) else "not in the text"
                    results.append({"review_id": r["review_id"], "topic": "playback", "intent": "complaint",
                                    "severity": 3, "sentiment": "negative", "evidence_quote": quote,
                                    "needs_review": False, "reason": "fake fallback"})
                body = {"results": results}
            elif "translation" in item:
                body = {"results": [{"review_id": r["review_id"], "language": "fake", "is_english": False,
                                     "meaningful": True, "translation": "[fake translation] " + r["text"][:40]}
                                    for r in reviews]}
            else:
                body = {"results": [{"review_id": r["review_id"], "topic": "other", "intent": "complaint",
                                     "severity": 2, "reason": "fake"} for r in reviews]}
        elif schema is not None:
            body = {"topics": [{"topic": "playback", "subtopics": [
                {"slug": "crashes", "name": "Crashes", "definition": "The app crashes."}]}]}
        else:
            claims = json.loads(user.split("<claims>\n", 1)[1].split("\n</claims>", 1)[0])
            first = claims[0]
            body = self.memo_text or (f"# Memo\n\nThe top issue is {first['issue_id']} with priority "
                                      f"{first['value']} [{first['claim_id']}].")
        text = body if isinstance(body, str) else json.dumps(body)
        return {"request_id": f"fake-claude-{uuid.uuid4().hex}", "model": self.model, "stop_reason": "end_turn",
                "text": text, "input_tokens": len(system + user) // 4, "output_tokens": len(text) // 4}
