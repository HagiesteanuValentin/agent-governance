#!/usr/bin/env python3
"""The v1.7 block on a hand-written mini transcript: effort phases, plan lag, advisor, audit."""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import session_metrics as sm  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "v17-mini.jsonl")
BASELINE = {"model": "claude-fable-5-1", "effort": "high", "n": 10,
            "median_output_tokens": 500, "median_thinking_tokens": 100}


def analyzed(baseline=None, fixture=FIXTURE):
    pricing = sm.load_pricing(os.path.join(os.path.dirname(HERE), "pricing.json"))
    versions = [{"name": "v1.7", "from": "2026-09-02T15:42"}]
    return sm.analyze(fixture, pricing, versions=versions, effort_baseline=baseline)


def test_effort_phases():
    v = analyzed()["v17"]
    assert v["effort_turns"] == {"high": 2, "medium": 3, "low": 3, "unknown": 0}
    assert [r["effort"] for r in v["effort_runs"]] == ["medium", "high", "low"]
    assert v["effort_cost_usd"]["low"] > 0


def test_plan_lag_is_two_turns():
    v = analyzed()["v17"]
    assert v["plan"]["exit_plan_count"] == 1
    assert v["plan"]["lag_turns_to_low"] == [2]
    assert v["plan"]["mismatch_turns"] == 2  # the two high turns of the lag


def test_advisor_call_and_sendmessage():
    v = analyzed()["v17"]
    a = v["advisor"]
    assert (a["calls"], a["sendmessages"], a["rounds"]) == (1, 1, 2)
    assert a["verdict"].startswith("GO")
    assert a["n_schimbari"] == 2 and a["n_scope_plus"] == 1
    assert a["cost_usd"] > 0 and a["reason_line"].startswith("plan cu 2 briefuri")


def test_audit_abateri():
    v = analyzed()["v17"]
    assert v["low_phase"]["audit_abateri_total"] == 2
    assert v["low_phase"]["audit_ok"] == 0


def test_counterfactual_needs_a_baseline():
    assert analyzed()["v17"]["counterfactual_high"] is None
    cf = analyzed(BASELINE)["v17"]["counterfactual_high"]
    assert cf is not None and cf["basis_n"] == 10
    assert cf["cost_if_high_est_usd"] > 0
    # the medium/low turns wrote less than the high median -> the estimate is more expensive
    assert cf["cost_saved_est_usd"] > 0


def test_baseline_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "baseline.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(BASELINE, fh)
        assert sm.load_effort_baseline(path)["median_output_tokens"] == 500
        assert sm.load_effort_baseline(os.path.join(tmp, "missing.json")) is None


def test_rating_feeds_advisor_score_and_mistakes():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "pending-rating.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"score": 4, "note": "n", "project": "mini", "ts": "2026-09-02T17:00:00Z",
                       "advisor_score": 5, "mistakes": 2}, fh)
        rating = sm.load_rating(path)
    s = analyzed()
    s["quality"] = sm.quality_of(rating)
    sm.apply_quality_to_v17(s)
    assert s["v17"]["advisor"]["score"] == 5
    assert s["v17"]["low_phase"]["mistakes"] == 2
    s["quality"] = {"score": 3}
    sm.apply_quality_to_v17(s)
    assert s["v17"]["advisor"]["score"] is None


def test_inherited_turns_are_outside_the_figures():
    s = analyzed(BASELINE, os.path.join(HERE, "fixtures", "v17-inherited.jsonl"))
    v = s["v17"]
    assert v["inherited_turns"] == 1
    assert v["effort_turns"] == {"high": 0, "medium": 1, "low": 1, "unknown": 0}
    # the parent's ExitPlanMode must not become this session's approval
    assert v["plan"]["exit_plan_count"] == 0 and v["plan"]["mismatch_turns"] is None
    assert v["effort_cost_usd"]["high"] == 0.0
    assert any("moștenite" in l for l in sm.v17_lines(s))


def test_v17_md_survives_a_record_without_the_block():
    empty = {"version": "v1.7", "v17": None, "name": "x", "session": "x",
             "totals": {"cost_usd": 1.0}, "main": {}, "workers": [], "flags": []}
    assert sm.v17_group_of(empty) is None
    assert "Medians per setup" in sm.v17_md([empty])


def test_empty_advisor_sections_count_zero():
    txt = "VERDICT: GO\nSCHIMBĂRI: niciuna\nIMPROVEMENTS: none\nNEED: -"
    assert sm.advisor_section_count(txt, sm.CHANGES_RE) == 0
    assert sm.advisor_section_count(txt, sm.IMPROVE_RE) == 0


def test_v17_report_and_md():
    s = analyzed(BASELINE)
    lines = sm.v17_lines(s)
    assert lines and lines[0].startswith("## v1.7")
    assert any("Advisor:" in l for l in lines)
    assert sm.v17_group_of(s) == "v1.7"
    md = sm.v17_md([s])
    assert "Medians per setup" in md and s["name"] in md


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print("ok   %s" % name)
        except AssertionError as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
    print("%d failed" % failed)
    sys.exit(1 if failed else 0)
