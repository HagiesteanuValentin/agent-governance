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


def test_cost_per_turn_is_filled_only_in_trends():
    assert analyzed()["v17"]["cost_per_turn"] is None


def test_task_class_from_slug_and_from_an_old_record():
    assert sm.task_class("-home-vali-workflow-proiecte-agent-governance") == "governance-rd"
    assert sm.task_class("-home-vali-proiecte-site_ac") == "product"
    assert sm.task_class({"project": "-home-x-agent-governance"}) == "governance-rd"
    assert sm.task_class({"project": "-home-x-shop", "task_class": "governance-rd"}) \
        == "governance-rd"
    assert analyzed()["task_class"] == "product"


def _rec(name, project, high, medium, main_cost):
    return {"name": name, "project": project, "main": {"cost_usd": main_cost},
            "v17": {"effort_turns": {"high": high, "medium": medium,
                                     "low": 0, "unknown": 0}}}


def test_cost_per_turn_medians_per_task_class():
    gov = "-home-x-agent-governance"
    sessions = [_rec("g1", gov, 10, 0, 10.0), _rec("g2", gov, 10, 0, 30.0),
                _rec("g3", gov, 0, 10, 5.0),
                _rec("p1", "-home-x-shop", 10, 0, 100.0),
                _rec("mix", gov, 5, 5, 20.0)]
    sm.apply_cost_per_turn(sessions)
    c = sessions[0]["v17"]["cost_per_turn"]
    assert c["task_class"] == "governance-rd" and c["main_usd_per_turn"] == 1.0
    assert c["corpus_n_high"] == 2 and c["corpus_high_median"] == 2.0
    # one medium session only -> no median
    assert c["corpus_n_medium"] == 1 and c["corpus_medium_median"] is None
    # the product session has its own corpus and does not feed the governance median
    p = sessions[3]["v17"]["cost_per_turn"]
    assert p["task_class"] == "product" and p["corpus_n_high"] == 1
    # a mixed-effort session gets the block but is not part of any corpus
    assert sessions[4]["v17"]["cost_per_turn"]["corpus_n_high"] == 2


def test_advisor_counts_items_not_lines():
    txt = ("SCHIMBARI: \n"
           "- Brief 1 - muta pasul 3\n"
           "  pentru ca ordinea rupe testul\n"
           "- Brief 2 - fixeaza calea\n"
           "  altfel scrie in repo\n"
           "3. Brief 3 - adauga fixture\n"
           "  cu doua rulari\n"
           "NEED: niciuna")
    assert sm.advisor_section_count(txt, sm.CHANGES_RE) == 3


def test_plan_echo():
    e = analyzed()["v17"]["plan"]["echo"]
    assert e["chars"] == len("plan aprobat")
    assert e["tokens_est"] == e["chars"] // 4
    # ExitPlanMode is turn 2 of 8; the plan is re-sent on the 5 turns after it
    assert e["turns_after"] == 5
    assert e["cost_est_usd"] > 0


def test_fork_chain_does_not_double_agent_runs():
    s = analyzed(fixture=os.path.join(HERE, "fixtures", "v17-fork-a.jsonl"))
    assert s["forked_to"] == ["v17-fork-b"]
    assert s["iterations"]["agent_runs_by_type"]["explorer"] == 2
    assert sorted(w["agent_id"] for w in s["workers"]) == ["e1", "e2"]


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


def test_summary_is_the_first_section():
    md = sm.markdown([analyzed()], aggregate=False)
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert heads[0] == "## Summary" and heads[1] == "## Session"
    body = md.split("## Session")[0].split("## Summary")[1].splitlines()
    lines = [l for l in body if l.strip()]
    assert len(lines) <= 8
    assert any(l.startswith("ok: ") for l in lines)
    assert any(l.startswith("Plan echo: $") for l in lines)
    assert any(l.startswith("Advisor: GO") for l in lines)


def _trend_rec(name, project, cost, main_cost):
    return {"session": name, "name": name, "project": project, "version": "v1.7",
            "started": "2026-09-02T10:00:00Z", "ended": "2026-09-02T12:00:00Z",
            "totals": {"cost_usd": cost, "agents_cost_usd": 0.0, "output": 10},
            "main": {"cost_usd": main_cost, "effort": "high"}, "context": {},
            "flags": [], "workers": [], "postmortem": {}, "counterfactual": {},
            "main_tool_calls": 0,
            "v17": {"effort_turns": {"high": 10, "medium": 0, "low": 0, "unknown": 0}}}


def test_trends_has_three_tables_and_the_rd_block():
    recs = [_trend_rec("g", "-home-x-agent-governance", 10.0, 8.0),
            _trend_rec("p", "-home-x-shop", 4.0, 4.0)]
    md = sm.trends_md(recs, 0, [{"name": "v1.7", "from": "2026-09-01T00:00"}])
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert heads[1:4] == ["## Versions — product", "## Versions — governance-rd",
                          "## Versions — total"]
    assert "## R&D governance cost" in heads
    # only the governance session counts, with its own $ main and 2 session hours
    assert "| **total** | 1 | $10.00 | $8.00 | 2.0 |" in md


def test_cumulative_saved_is_per_table():
    g = _trend_rec("g", "-home-x-agent-governance", 10.0, 8.0)
    p = _trend_rec("p", "-home-x-shop", 4.0, 4.0)
    g["counterfactual"] = {"realistic_usd": 40.0, "floor_usd": 20.0}
    p["counterfactual"] = {"realistic_usd": 14.0, "floor_usd": 6.0}
    md = sm.trends_md([g, p], 0, [{"name": "v1.7", "from": "2026-09-01T00:00"}])
    cum = {}
    title = None
    for line in md.splitlines():
        if line.startswith("## Versions"):
            title = line.split("— ")[1]
        elif title and line.startswith("| v1.7 |"):
            cum[title] = [c.strip() for c in line.split("|")][8]
            title = None
    # product saved 14-4=10, governance-rd 40-10=30, total is the sum
    assert cum["product"] == "$10.00" and cum["governance-rd"] == "$30.00"
    assert cum["total"] == "$40.00"


def test_v17_md_shows_the_median_of_its_own_class():
    recs = [_trend_rec("g1", "-home-x-agent-governance", 10.0, 10.0),
            _trend_rec("g2", "-home-x-agent-governance", 30.0, 30.0)]
    sm.apply_cost_per_turn(recs)
    row = [l for l in sm.v17_md(recs).splitlines() if l.startswith("| g1 ")][0]
    cells = [c.strip() for c in row.split("|")]
    assert cells[2] == "governance-rd"
    # pure-high session: the medium column stays empty, the high one holds the median
    assert cells[10] == "—" and cells[11] == "2.0"
    assert "$ if high" not in sm.v17_md(recs)


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
