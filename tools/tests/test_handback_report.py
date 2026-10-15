#!/usr/bin/env python3
"""A report delivered through SubagentHandback counts as the agent's final text."""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import session_metrics as sm  # noqa: E402

REPORT = "RĂSPUNS: x" * 10
SID = "hb"


def usage():
    return {"input_tokens": 40, "output_tokens": 300, "cache_read_input_tokens": 150,
            "cache_creation_input_tokens": 0}


def session(agent_content, agent_type="auditor"):
    root = tempfile.mkdtemp(prefix="hb-")
    main = os.path.join(root, SID + ".jsonl")
    sub = os.path.join(root, SID, "subagents")
    os.makedirs(sub)
    recs = [
        {"type": "user", "timestamp": "2026-10-12T10:00:00Z", "cwd": "/tmp/proj",
         "session_id": SID, "message": {"role": "user", "content": "task"}},
        {"type": "assistant", "timestamp": "2026-10-12T10:01:00Z", "session_id": SID,
         "message": {"id": "m1", "model": "claude-fable-5-1", "usage": usage(),
                     "content": [{"type": "tool_use", "id": "t_imp", "name": "Agent",
                                  "input": {"subagent_type": agent_type,
                                            "description": "audit", "prompt": "p"}}]}},
        {"type": "user", "timestamp": "2026-10-12T10:05:00Z", "session_id": SID,
         "toolUseResult": {"agentId": "imp1"},
         "message": {"role": "user", "content": [{"type": "tool_result",
                                                  "tool_use_id": "t_imp",
                                                  "content": "agentId: imp1\ndone"}]}},
    ]
    with open(main, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(sub, "agent-imp1.meta.json"), "w") as f:
        json.dump({"agentType": agent_type, "description": "audit", "toolUseId": "t_imp"}, f)
    with open(os.path.join(sub, "agent-imp1.jsonl"), "w") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-10-12T10:02:00Z",
                            "isSidechain": True, "session_id": "imp1",
                            "message": {"id": "u1", "model": "claude-fable-5-1",
                                        "usage": usage(), "content": agent_content}}) + "\n")
    return root, main


def analyzed(agent_content, agent_type="auditor"):
    root, main = session(agent_content, agent_type)
    try:
        pricing = sm.load_pricing(os.path.join(os.path.dirname(HERE), "pricing.json"))
        return sm.analyze(main, pricing, versions=[{"name": "v", "from": "2026-10-01T00:00"}])
    finally:
        shutil.rmtree(root)


def handback(msg):
    return {"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": msg}}


def no_report_flags(a):
    return [f for f in a["flags"] if f["code"] == "agent_no_report"]


def test_handback_only_counts_as_report():
    a = analyzed([handback(REPORT)])
    w = a["workers"][0]
    assert w["final_report_chars"] == len(REPORT), w["final_report_chars"]
    assert no_report_flags(a) == []


def test_text_report_is_unchanged():
    a = analyzed([{"type": "text", "text": REPORT}])
    assert a["workers"][0]["final_report_chars"] == len(REPORT)
    assert no_report_flags(a) == []


def test_text_plus_handback_is_not_doubled():
    a = analyzed([{"type": "text", "text": "gata."}, handback(REPORT)])
    assert a["workers"][0]["final_report_chars"] == len(REPORT)


def test_handback_without_string_message_adds_nothing():
    a = analyzed([{"type": "tool_use", "id": "h1", "name": "SubagentHandback",
                   "input": {"message": 5}}])
    assert a["workers"][0]["final_report_chars"] == 0
    assert len(no_report_flags(a)) == 1


def long_report_flags(a):
    return [f for f in a["flags"] if f["code"] == "long_agent_report"]


def test_design_lead_13000_is_under_plan_lead_cap():
    a = analyzed([handback("x" * 13000)], "design-lead-expert")
    assert long_report_flags(a) == []


def test_scribe_2500_is_flagged():
    a = analyzed([handback("x" * 2500)], "scribe")
    assert len(long_report_flags(a)) == 1
