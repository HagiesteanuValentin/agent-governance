#!/usr/bin/env python3
"""v1.12: auditor-complex after orchestrator, no explorer cap, brief-*.md not code."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import session_metrics as sm  # noqa: E402
from test_v181_flags import write_jsonl, user_start, call, result  # noqa: E402,F401


def analyzed(records):
    path = write_jsonl(records)
    try:
        pricing = sm.load_pricing(os.path.join(os.path.dirname(HERE), "pricing.json"))
        return sm.analyze(path, pricing, versions=[{"name": "v1.12", "from": "2026-09-01T00:00"}])
    finally:
        os.unlink(path)


def launch(uid, kind, minute):
    return [call(uid, "Agent", {"subagent_type": kind, "description": "d " + uid,
                                "prompt": "brief"}, minute),
            result(uid, "done", minute)]


def codes(records):
    return [f["code"] for f in analyzed([user_start()] + records)["flags"]]


def test_auditor_after_orchestrator_is_not_flagged():
    c = codes(launch("o1", "orchestrator", 1) + launch("a1", "auditor-complex", 2))
    assert "fable_launched_worker" not in c, c


def test_auditor_per_brief_in_main_is_flagged():
    c = codes(launch("o1", "orchestrator", 1) + launch("a1", "auditor-complex", 2)
              + launch("a2", "auditor-complex", 3))
    assert "fable_launched_worker" in c, c


def test_auditor_without_orchestrator_is_flagged():
    assert "fable_launched_worker" in codes(launch("a1", "auditor-complex", 1))


def test_implementer_from_main_is_flagged():
    c = codes(launch("o1", "orchestrator", 1) + launch("i1", "implementer", 2))
    assert "fable_launched_worker" in c, c


def test_five_explorers_no_too_many_runs():
    recs = []
    for i in range(5):
        recs += launch("e%d" % i, "explorer", i + 1)
    assert "too_many_runs" not in codes(recs)


def test_brief_write_is_not_code():
    body = "\n".join("line %d" % i for i in range(40))
    c = codes([call("w1", "Write", {"file_path": "/tmp/s/brief-3.md", "content": body}, 1),
               result("w1", "ok", 1)])
    assert "fable_wrote_code" not in c, c


def test_ts_write_is_code():
    body = "\n".join("const a%d = 1;" % i for i in range(40))
    c = codes([call("w1", "Write", {"file_path": "/tmp/proj/x.ts", "content": body}, 1),
               result("w1", "ok", 1)])
    assert "fable_wrote_code" in c, c


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
