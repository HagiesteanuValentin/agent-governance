#!/usr/bin/env python3
"""v1.8.1: image blocks cost IMAGE_CHARS, batchable_bash skips dependent chains."""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import session_metrics as sm  # noqa: E402


def write_jsonl(records):
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="v181-")
    with os.fdopen(fd, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def analyzed(records):
    path = write_jsonl(records)
    try:
        pricing = sm.load_pricing(os.path.join(os.path.dirname(HERE), "pricing.json"))
        return sm.analyze(path, pricing, versions=[{"name": "v1.8.1", "from": "2026-09-01T00:00"}])
    finally:
        os.unlink(path)


def user_start():
    return {"type": "user", "timestamp": "2026-09-08T10:00:00Z", "cwd": "/tmp/proj",
            "session_id": "v181", "message": {"role": "user", "content": "task"}}


def call(uid, name, inp, minute):
    return {"type": "assistant", "timestamp": "2026-09-08T10:%02d:00Z" % minute,
            "session_id": "v181",
            "message": {"id": "a%s" % uid, "model": "claude-fable-5-1",
                        "usage": {"input_tokens": 100, "output_tokens": 100,
                                  "cache_read_input_tokens": 1000,
                                  "cache_creation_input_tokens": 0},
                        "content": [{"type": "tool_use", "id": uid, "name": name,
                                     "input": inp}]}}


def result(uid, content, minute):
    return {"type": "user", "timestamp": "2026-09-08T10:%02d:30Z" % minute,
            "session_id": "v181",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": uid,
                                     "content": content}]}}


def test_image_block_counts_image_chars_and_raises_no_flag():
    big = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": "A" * 400000}}]
    assert sm.result_chars(big) == sm.IMAGE_CHARS
    a = analyzed([user_start(),
                  call("u1", "Read", {"file_path": "/tmp/proj/shot.png"}, 1),
                  result("u1", big, 1)])
    rows = [f for f in a["flags"] if f["code"] == "big_tool_result_main"]
    assert rows == [], rows


def test_text_result_over_the_threshold_still_flags():
    a = analyzed([user_start(),
                  call("u1", "Bash", {"command": "cat docs/x.md"}, 1),
                  result("u1", [{"type": "text", "text": "x" * 12000}], 1)])
    codes = [f["code"] for f in a["flags"]]
    assert "big_tool_result_main" in codes, codes


BATCH_READONLY = ["ls /tmp/proj", "grep -n foo /tmp/proj/a.md 2>&1", "sed -n '1,5p' /tmp/proj/a.md"]


def batch_records(cmds):
    recs = [user_start()]
    for k, cmd in enumerate(cmds):
        uid = "b%d" % k
        recs.append(call(uid, "Bash", {"command": cmd}, k + 1))
        recs.append(result(uid, "ok", k + 1))
    return recs


def test_readonly_chain_is_batchable():
    a = analyzed(batch_records(BATCH_READONLY))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" in codes, codes


def test_chain_with_sed_i_is_not_batchable():
    cmds = list(BATCH_READONLY)
    cmds[1] = "sed -i 's/foo/bar/' /tmp/proj/a.md"
    a = analyzed(batch_records(cmds))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" not in codes, codes


def test_dev_null_redirect_stays_batchable():
    cmds = list(BATCH_READONLY)
    cmds[0] = "ls /tmp/proj >/dev/null"
    a = analyzed(batch_records(cmds))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" in codes, codes


def test_mutating_regex_edges():
    for cmd in ("git add -A", "rm /tmp/a", "echo hi > /tmp/out.txt",
                "mv a b", "cp a b", "mkdir -p x", "touch f", "chmod +x f",
                "cat f | tee out.txt", "git add f && git commit -m x",
                "sed -i 's/a/b/' f", "git reset --hard", "git merge main"):
        assert sm.BATCH_MUTATING_RE.search(cmd), cmd
    for cmd in ("grep -n foo a.md 2>&1", "ls -la", "git log --oneline",
                "cat a.md | wc -l", "ls /tmp >/dev/null", "make 2>/dev/null",
                "npm test", "npx tsc --noEmit", "python3 tools/x.py",
                "node scripts/a.mjs", "bash scripts/check.sh",
                "git status --short", "git diff --stat", "git show HEAD",
                "echo format", "rmdir olddir", "cat cpio.log"):
        assert not sm.BATCH_MUTATING_RE.search(cmd), cmd


def test_verifier_chain_is_batchable():
    a = analyzed(batch_records(["npm test", "python3 tools/x.py", "node b.mjs"]))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" in codes, codes


def test_git_readonly_chain_is_batchable():
    a = analyzed(batch_records(["git status --short", "git log -1", "git diff --stat"]))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" in codes, codes


def test_chain_with_rm_is_not_batchable():
    cmds = list(BATCH_READONLY)
    cmds[1] = "rm /tmp/proj/a.md"
    a = analyzed(batch_records(cmds))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" not in codes, codes


def test_file_redirect_chain_is_not_batchable():
    cmds = list(BATCH_READONLY)
    cmds[0] = "ls /tmp/proj > out.txt"
    a = analyzed(batch_records(cmds))
    codes = [f["code"] for f in a["flags"]]
    assert "batchable_bash" not in codes, codes
