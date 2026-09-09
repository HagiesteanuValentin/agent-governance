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
    assert sm.task_class("-home-user-workflow-proiecte-agent-governance") == "governance-rd"
    assert sm.task_class("-home-user-proiecte-site_ac") == "product"
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
    # no manual value left -> the auto formula fills both
    assert s["v17"]["advisor"]["score"] == 3
    assert s["v17"]["low_phase"]["mistakes"] == 2


def _v17(verdict, n_schimbari=0, plan_edits_after=0, abateri=0, flags=(), reruns=0,
         effort_runs=()):
    return {"advisor": {"verdict": verdict, "n_schimbari": n_schimbari,
                        "plan_edits_after": plan_edits_after},
            "effort_runs": [{"effort": e} for e in effort_runs],
            "low_phase": {"audit_abateri_total": abateri, "flags": list(flags),
                          "reruns": reruns}}


def test_derive_quality_without_an_advisor_report():
    score, mistakes, breakdown = sm.derive_quality(_v17(None, abateri=1, reruns=1))
    assert score is None
    assert mistakes == 2 and breakdown["reruns"] == 1


def test_derive_quality_on_session_1609():
    # GO, 3 SCHIMBARI but no plan edit after, 1 ABATERI, one late_first_edit flag
    v = _v17("GO", n_schimbari=3, plan_edits_after=0, abateri=1,
             flags=[("late_first_edit", 1)])
    assert sm.derive_quality(v) == (3, 2, {"audit_abateri_total": 1, "low_flags": 1,
                                           "reruns": 0})
    # a NO-GO plan implemented anyway loses a point
    assert sm.derive_quality(_v17("NO-GO: plan neclar", effort_runs=("medium", "low")))[0] == 3
    assert sm.derive_quality(_v17("NO-GO: plan neclar"))[0] == 4


def test_manual_rating_overrides_auto_and_is_marked():
    s = analyzed()
    s["quality"] = {"score": 4, "advisor_score": 5, "mistakes": 9}
    sm.apply_quality_to_v17(s)
    v = s["v17"]
    assert (v["advisor"]["score"], v["advisor"]["advisor_score_src"]) == (5, "manual")
    assert (v["low_phase"]["mistakes"], v["low_phase"]["mistakes_src"]) == (9, "manual")
    # what apply_ wrote back into quality is marked auto and must not look manual next run
    s2 = analyzed()
    s2["quality"] = {"score": 4}
    sm.apply_quality_to_v17(s2)
    assert s2["quality"]["mistakes"] == 2 and s2["quality"]["mistakes_src"] == "auto"
    sm.apply_quality_to_v17(s2)
    assert s2["v17"]["advisor"]["advisor_score_src"] == "auto"
    assert s2["v17"]["low_phase"]["mistakes"] == 2


def test_inherited_turns_are_outside_the_figures():
    s = analyzed(BASELINE, os.path.join(HERE, "fixtures", "v17-inherited.jsonl"))
    v = s["v17"]
    assert v["inherited_turns"] == 1
    assert v["effort_turns"] == {"high": 0, "medium": 1, "low": 1, "unknown": 0}
    # the parent's ExitPlanMode must not become this session's approval
    assert v["plan"]["exit_plan_count"] == 0 and v["plan"]["mismatch_turns"] is None
    assert v["effort_cost_usd"]["high"] == 0.0
    assert any("inherited turns" in l for l in sm.v17_lines(s))


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


def _session(name, main_in, wasted):
    m = {"input": main_in, "cache_creation": 0, "cache_read": 0, "cost_usd": 1.0}
    return {"name": name, "started": "2026-08-30T18:00", "main": m,
            "totals": {"cost_usd": 2.0}, "flags": [],
            "postmortem": {"wasted_total": wasted,
                           "wasted_pct_of_main_input": round(100.0 * wasted / (main_in or 1), 1),
                           "severity_counts": {"high": 0, "medium": 0, "low": 0}}}


def test_wasted_pct_skips_sessions_without_main_input():
    broken = _session("no-main", 0, 48074)          # main attribution failed: all zeros
    good = _session("ok", 400000, 40000)
    v = sm.version_stats([broken, good])
    assert v["wasted_na"] == 1
    assert 0 < v["wasted_pct"] <= 100, v["wasted_pct"]
    assert abs(v["wasted_pct"] - 10.0) < 0.01, v["wasted_pct"]
    assert v["wasted"] == 88074  # the tokens still count in the total
    only_broken = sm.version_stats([broken])
    assert only_broken["wasted_pct"] is None and only_broken["wasted_na"] == 1


def test_wasted_pct_cell_is_na_not_a_huge_number():
    broken = _session("no-main", 0, 48074)
    rows = sm.versions_table(["v1.5"], {"v1.5": [broken]}, {})
    row = [r for r in rows if r.startswith("| v1.5 |")][0]
    assert "n/a (1 excl.)" in row and "4807400" not in row, row
    mixed = sm.versions_table(["v1.5"], {"v1.5": [broken, _session("ok", 400000, 40000)]}, {})
    mrow = [r for r in mixed if r.startswith("| v1.5 |")][0]
    assert "10.0% (1 excl.)" in mrow, mrow
    clean = sm.versions_table(["v1.5"], {"v1.5": [_session("ok", 400000, 40000)]}, {})
    crow = [r for r in clean if r.startswith("| v1.5 |")][0]
    assert "10.0% |" in crow and "excl." not in crow, crow
    sess = sm.version_block("v1.5", [broken], {"v1.5": [broken]}, None, {})
    assert not any("4807400" in l for l in sess), [l for l in sess if "4807400" in l]
    assert any("n/a of main input volume" in l for l in sess)


def test_inherited_needs_the_uuid_copied_from_the_parent():
    # proc-abc.jsonl only has u-copied; u-nou-1/2 are its own even though session_id is foreign
    s = analyzed(BASELINE, os.path.join(HERE, "fixtures", "v17-sessionid.jsonl"))
    assert s["v17"]["inherited_turns"] == 1
    assert s["totals"]["main_cost_usd"] > 0


WASTE_LEGIT = os.path.join(HERE, "fixtures", "v18-waste-legit.jsonl")


def waste_flags():
    return analyzed(fixture=WASTE_LEGIT)["flags"]


def test_advisor_reading_the_whole_plan_is_not_waste():
    codes = [(f["code"], f["scope"]) for f in waste_flags()]
    assert ("agent_read_plan_whole", "advisor#1") not in codes, codes
    assert ("agent_read_plan_whole", "implementer#1") in codes, codes


def test_main_reading_a_refine_report_is_a_zero_token_flag():
    flags = waste_flags()
    rep = [f for f in flags if f["code"] == "main_read_report"]
    assert len(rep) == 1 and "docs/refine/pret.md" in rep[0]["detail"], flags
    assert rep[0].get("est_wasted_tokens", 0) == 0 and rep[0]["severity"] == "low"
    cmds = [f["detail"] for f in flags if f["code"] == "main_read_files"]
    assert any("src/a.ts" in c for c in cmds), cmds        # mixed stays taxed
    assert any("src/index.astro" in c for c in cmds), cmds
    assert len(cmds) == 2, cmds


def test_wasted_total_still_equals_the_sum_of_the_families():
    a = analyzed(fixture=WASTE_LEGIT)
    total = a["postmortem"]["wasted_total"]
    assert total == sum(f.get("est_wasted_tokens", 0) for f in a["flags"]), total
    assert sm.WASTE_FAMILIES["main_read_report"] == "reads"


REREAD_REGEN = os.path.join(HERE, "fixtures", "v18-reread-regen.jsonl")


def test_reread_skips_a_file_regenerated_between_two_reads():
    a = analyzed(fixture=REREAD_REGEN)
    paths = [r["path"] for r in a["reread_files"]]
    assert "/tmp/proj/shot-a.png" not in paths, paths        # magick rewrote it
    assert "/tmp/proj/notes-b.md" in paths, paths            # ls is read-only
    assert "/tmp/proj/src-c.ts" in paths, paths              # Edit does not exempt
    flagged = [f["detail"] for f in a["flags"] if f["code"] == "reread"]
    assert not any("shot-a.png" in d for d in flagged), flagged
    assert any("notes-b.md" in d for d in flagged), flagged
    assert any("src-c.ts" in d for d in flagged), flagged
    assert "/tmp/proj/notes-d.md" in paths, paths           # cd prefix, cat is read-only
    assert any("notes-d.md" in d for d in flagged), flagged


def _cf_session(name, peak_cf):
    s = _session(name, 400000, 40000)
    if peak_cf is not None:
        s["counterfactual"] = {"peak_context_cf": peak_cf}
    return s


def test_versions_table_cf_peak_columns():
    grp = [_cf_session("a", 200000), _cf_session("b", 500000), _cf_session("c", 1200000)]
    v = sm.version_stats(grp, 0.35, 1000000)
    assert v["cf_n"] == 3
    assert v["peak_cf_max"] == 1200000 and v["peak_cf_median"] == 500000
    assert abs(v["cf_over_rot_pct"] - 66.67) < 0.1, v["cf_over_rot_pct"]
    assert abs(v["cf_over_window_pct"] - 33.33) < 0.1, v["cf_over_window_pct"]
    rows = sm.versions_table(["v1.8", "v1.5"], {"v1.8": grp, "v1.5": [_cf_session("d", None)]},
                             {}, rot_at=0.35, window=1000000)
    row = [r for r in rows if r.startswith("| v1.8 |")][0]
    assert "1.2M/500.0k" in row and "67% (2/3)" in row, row
    other = [r for r in rows if r.startswith("| v1.5 |")][0]
    assert sm.version_stats([_cf_session("d", None)])["cf_n"] == 0
    assert "| — | — |" in other, other
    assert any("single-context threshold: rot 350.0k · window 1.0M" in r for r in rows), rows


CACHE_FIXTURE = os.path.join(HERE, "fixtures", "v18-cache.jsonl")


def cache_flags():
    return analyzed(fixture=CACHE_FIXTURE)["flags"]


def test_cache_rewrite_main_skips_a_pause_over_an_hour():
    rw = [f for f in cache_flags() if f["code"] == "cache_rewrite_main"]
    assert len(rw) == 1, rw                      # m3 rewrites too, but 1h55m later
    ev = rw[0]["evidence"]
    assert ev["tokens"] == 45000 and ev["gap_s"] == 300.0, ev
    assert ev["prev_tokens"] == 40000 and rw[0]["severity"] == "medium"
    assert rw[0].get("est_wasted_tokens", 0) == 0  # tokens are not moved into wasted%


def test_agent_resume_rewrite_is_priced_at_the_5m_write_rate():
    rs = [f for f in cache_flags() if f["code"] == "agent_resume_rewrite"]
    assert len(rs) == 1 and rs[0]["scope"] == "scripter-complex#1", rs
    ev = rs[0]["evidence"]
    assert ev["kind"] == "resume" and ev["gap_s"] == 550.0 and ev["tokens"] == 30000, ev
    assert abs(ev["usd"] - 30000 * 12.5 / 1e6) < 1e-6, ev   # claude-fable-5-1 cache_write_5m
    assert rs[0].get("est_wasted_tokens", 0) == 0


def test_scripter_below_threshold():
    sb = [f for f in cache_flags() if f["code"] == "scripter_below_threshold"]
    assert len(sb) == 1 and sb[0]["severity"] == "low", sb
    assert sb[0]["evidence"]["files_changed"] == 2, sb


def _flag_session(name, codes):
    s = _session(name, 400000, 40000)
    s["flags"] = codes
    return s


def test_versions_table_cache_columns_are_dashes_without_data():
    with_data = _flag_session("a", [
        {"code": "cache_rewrite_main", "evidence": {"tokens": 45000}},
        {"code": "cache_rewrite_main", "evidence": {"tokens": 15000}},
        {"code": "agent_resume_rewrite", "evidence": {"usd": 0.375}},
        {"code": "scripter_below_threshold", "evidence": {"files_changed": 2}}])
    old = _flag_session("b", [{"code": "reread"}])       # analyzed before the flags existed
    v = sm.version_stats([with_data])
    assert (v["cache_rw_n"], v["cache_rw_tok"], v["resume_n"], v["scr_below_n"]) == (2, 60000, 1, 1)
    assert v["cache_flags_seen"] and sm.version_stats([old])["cache_flags_seen"] is False
    assert sm.version_stats([old])["cache_rw_per"] is None
    rows = sm.versions_table(["v1.8", "v1.7"], {"v1.8": [with_data], "v1.7": [old]}, {})
    row = [r for r in rows if r.startswith("| v1.8 |")][0]
    assert row.endswith("| 2 / 60.0k | 1 / $0.38 | 1 |"), row
    assert [r for r in rows if r.startswith("| v1.7 |")][0].endswith("| — | — | — |")
    empty = sm.versions_table(["v1.6"], {"v1.6": []}, {})
    blank = [r for r in empty if r.startswith("| v1.6 |")][0]
    assert blank.count("|") == empty[2].count("|") == row.count("|"), blank


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
