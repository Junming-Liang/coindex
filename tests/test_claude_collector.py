"""Claude Code source: collector, store, service transport and connection checks.

All fixtures are fictional; no real Claude or Codex data is read.
"""
import datetime
import json
import os
import pathlib
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/"backend"))
from claude_collector import VERSION, claude_root, collect, merge, parse_session
from collector import HEAD_BYTES, TAIL_BYTES
from connections import local_check, normalize_remote, normalize_settings, remote_check
from service import collect_host
from store import Store
from test_backend import conversation, entry, task

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSION = "22222222-2222-4222-8222-222222222222"


def stamp(minute):
    return (datetime.datetime(2026, 11, 10, 1, tzinfo=datetime.timezone.utc)
            + datetime.timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")


def user_row(text="实现登录功能", minute=0, **extra):
    row = {"type": "user", "sessionId": SESSION, "cwd": "/workspace", "timestamp": stamp(minute),
           "message": {"role": "user", "content": text}}
    row.update(extra)
    return row


def assistant_row(text="已完成实现", stop_reason="end_turn", minute=1, **extra):
    row = {"type": "assistant", "sessionId": SESSION, "cwd": "/workspace", "timestamp": stamp(minute),
           "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "stop_reason": stop_reason}}
    row.update(extra)
    return row


def write_session(root, rows, name=None):
    folder = root/"projects"/"-workspace"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(name or SESSION + ".jsonl")
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def make_claude_root(base):
    root = pathlib.Path(base)/"claude"
    write_session(root, [user_row(), assistant_row()])
    return root


def make_codex_root(base):
    root = pathlib.Path(base)/"codex"
    (root/"sessions").mkdir(parents=True)
    records = [{"type": "session_meta", "payload": {"id": str(uuid.uuid4()), "source": "vscode", "cwd": "/workspace"}},
               {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "实现应用"}]}}]
    (root/"sessions"/"rollout.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return root


class ClaudeCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_session_extracts_agent_title_messages_and_idle_state(self):
        path = write_session(self.root, [user_row(), assistant_row()])
        conv = parse_session(path, "mac")
        self.assertEqual(conv["id"], "mac:" + SESSION)
        self.assertEqual(conv["thread_id"], SESSION)
        self.assertEqual(conv["agent"], "claude")
        self.assertEqual(conv["host"], "mac")
        self.assertEqual(conv["title"], "实现登录功能")
        self.assertEqual(conv["cwd"], "/workspace")
        self.assertFalse(conv["active"])
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"])
        self.assertEqual(conv["messages"][0]["text"], "实现登录功能")
        self.assertEqual(len(conv["fingerprint"]), 64)
        self.assertGreater(conv["updated_at"], 0)
        self.assertFalse(conv["truncated"])
        self.assertEqual(conv["malformed_lines"], 0)

    def test_tool_results_are_kept_and_sidechain_meta_thinking_are_excluded(self):
        rows = [user_row(minute=0),
                {"type": "user", "sessionId": SESSION, "cwd": "/workspace", "timestamp": stamp(1),
                 "message": {"role": "user", "content": [
                     {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "测试通过 3 个"}]},
                     {"type": "text", "text": "继续修复"}]}},
                {"type": "assistant", "sessionId": SESSION, "cwd": "/workspace", "timestamp": stamp(2),
                 "message": {"role": "assistant", "stop_reason": "tool_use",
                             "content": [{"type": "thinking", "thinking": "内部思考不应出现"},
                                         {"type": "text", "text": "正在运行测试"}]}},
                user_row("侧面任务不应出现", minute=3, isSidechain=True),
                user_row("元信息不应出现", minute=4, isMeta=True)]
        conv = parse_session(write_session(self.root, rows), "mac")
        text = json.dumps(conv["messages"], ensure_ascii=False)
        self.assertIn("测试通过 3 个", text)
        self.assertIn("继续修复", text)
        self.assertTrue(any(m["role"] == "tool" for m in conv["messages"]))
        for hidden in ("侧面任务", "元信息", "内部思考"):
            self.assertNotIn(hidden, text)
        self.assertTrue(conv["active"])

    def test_active_heuristic_follows_the_latest_row(self):
        path = write_session(self.root, [user_row(), assistant_row(stop_reason=None)])
        self.assertTrue(parse_session(path, "mac")["active"])
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in
                                  [user_row(), assistant_row(stop_reason="tool_use")]), encoding="utf-8")
        self.assertTrue(parse_session(path, "mac")["active"])
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in
                                  [user_row(), assistant_row(stop_reason="end_turn")]), encoding="utf-8")
        self.assertFalse(parse_session(path, "mac")["active"])
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in
                                  [user_row(), assistant_row(), user_row("继续", minute=2)]), encoding="utf-8")
        self.assertTrue(parse_session(path, "mac")["active"])

    def test_command_echoes_are_cleaned_and_titles_prefer_custom_then_summary(self):
        echoed = ("<command-name>/clear</command-name><command-message>clear</command-message>"
                  "<command-args></command-args><command-name />实现导出功能"
                  "<system-reminder>注入提示不应成为目标</system-reminder>")
        rows = [{"type": "summary", "summary": "摘要标题"}, user_row(echoed),
                user_row("Caveat: 本地命令输出勿跟踪", minute=1)]
        path = write_session(self.root, rows)
        conv = parse_session(path, "mac")
        self.assertEqual(conv["title"], "摘要标题")
        self.assertEqual([m["text"] for m in conv["messages"] if m["role"] == "user"], ["实现导出功能"])
        rows.append({"type": "custom-title", "customTitle": "自定义标题", "sessionId": SESSION})
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        self.assertEqual(parse_session(path, "mac")["title"], "自定义标题")

    def test_sessions_without_user_or_session_id_are_skipped_and_malformed_counted(self):
        path = write_session(self.root, [assistant_row()])
        self.assertIsNone(parse_session(path, "mac"))
        row = user_row()
        del row["sessionId"]
        path = write_session(self.root, [row], name="notes.jsonl")
        self.assertIsNone(parse_session(path, "mac"))
        path = write_session(self.root, [user_row(), assistant_row()])
        path.write_text("not json\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(parse_session(path, "mac")["malformed_lines"], 1)

    def test_collect_uses_agent_versioned_cursors_limit_and_recency(self):
        write_session(self.root, [user_row(), assistant_row()])
        other = "33333333-3333-4333-8333-333333333333"
        old = write_session(self.root, [user_row(sessionId=other), assistant_row(sessionId=other)],
                            name=other + ".jsonl")
        result = collect({"root": str(self.root), "host": "mac"})
        self.assertEqual(len(result["conversations"]), 2)
        self.assertEqual(result["total_files"], 2)
        self.assertEqual(result["remaining_files"], 0)
        for name, signature in result["files"].items():
            stat = pathlib.Path(name).stat()
            self.assertEqual(signature, ["claude", VERSION, stat.st_mtime_ns, stat.st_size])
        again = collect({"root": str(self.root), "host": "mac", "known": result["files"]})
        self.assertEqual(again["conversations"], [])
        bumped = {p: ["claude", VERSION + 1, s[2], s[3]] for p, s in result["files"].items()}
        self.assertEqual(len(collect({"root": str(self.root), "known": bumped})["conversations"]), 2)
        limited = collect({"root": str(self.root), "limit": 1})
        self.assertEqual(len(limited["conversations"]), 1)
        self.assertEqual(limited["remaining_files"], 1)
        past = time.time() - 3 * 86400
        os.utime(old, (past, past))
        recent = collect({"root": str(self.root), "days": 1})
        self.assertEqual(recent["total_files"], 1)
        self.assertEqual(recent["conversations"][0]["thread_id"], SESSION)

    def test_missing_projects_directory_raises(self):
        with self.assertRaisesRegex(RuntimeError, "projects"):
            collect({"root": str(self.root)})

    def test_merge_combines_legs_and_tolerates_missing_keys(self):
        primary = {"conversations": [{"id": "a"}], "files": {"/a": [6, 1]}, "total_files": 1,
                   "remaining_files": 0, "read_errors": [{"path": "/x", "error": "E"}]}
        secondary = {"conversations": [{"id": "b"}], "files": {"/b": ["claude", 1, 2, 3]},
                     "total_files": 2, "remaining_files": 1, "read_errors": []}
        merged = merge(primary, secondary)
        self.assertEqual([c["id"] for c in merged["conversations"]], ["a", "b"])
        self.assertEqual(merged["files"], {"/a": [6, 1], "/b": ["claude", 1, 2, 3]})
        self.assertEqual(merged["total_files"], 3)
        self.assertEqual(merged["remaining_files"], 1)
        self.assertEqual(merged["read_errors"], [{"path": "/x", "error": "E"}])
        self.assertEqual(merge({"conversations": []}, {})["conversations"], [])

    def test_bounded_read_keeps_first_user_and_latest_turns(self):
        rows = [user_row("最初目标", minute=0)]
        rows += [{"type": "system", "content": "x" * 2000} for _ in range(1000)]
        rows += [assistant_row("中间步骤 %d" % i, stop_reason="tool_use", minute=i + 1) for i in range(21)]
        rows.append(assistant_row("最终结论", minute=30))
        path = write_session(self.root, rows)
        self.assertGreater(path.stat().st_size, HEAD_BYTES + TAIL_BYTES)
        conv = parse_session(path, "mac")
        self.assertTrue(conv["truncated"])
        texts = [m["text"] for m in conv["messages"]]
        self.assertIn("最初目标", texts)
        self.assertIn("最终结论", texts)
        self.assertLessEqual(len(conv["messages"]), 23)
        self.assertEqual(conv["malformed_lines"], 0)
        self.assertFalse(conv["active"])


class ClaudeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def ingest(self, conv):
        self.store.ingest(dict(host=conv["host"], files={}, conversations=[conv], total_files=1, remaining_files=0, root="/tmp"))

    def test_agent_defaults_to_codex_and_claude_agent_is_exposed(self):
        codex = conversation()
        self.ingest(codex)
        self.store.reconcile([entry()], [codex])
        claude = dict(conversation("mac:" + str(uuid.uuid4())), agent="claude")
        self.ingest(claude)
        self.store.reconcile([entry(claude["id"], tasks=[task(key="claude-review", artifact="Claude 会话记录")])], [claude])
        snapshot = self.store.snapshot()
        by_conv = {t["conversation_id"]: t for t in snapshot["tasks"]}
        self.assertEqual(by_conv[codex["id"]]["agent"], "codex")
        self.assertEqual(by_conv[claude["id"]]["agent"], "claude")
        convs = {c["id"]: c for c in snapshot["conversations"]}
        self.assertEqual(convs[codex["id"]]["agent"], "codex")
        self.assertEqual(convs[claude["id"]]["agent"], "claude")

    def test_nudge_target_rejects_claude_conversations(self):
        claude = dict(conversation("mac:" + str(uuid.uuid4())), agent="claude")
        self.ingest(claude)
        self.store.reconcile([entry(claude["id"], tasks=[task(key="claude-review", artifact="Claude 会话记录")])], [claude])
        task_id = self.store.snapshot()["tasks"][0]["id"]
        with self.assertRaisesRegex(ValueError, "Claude"):
            self.store.nudge_target(task_id)

    def test_claude_home_change_clears_only_claude_cursors(self):
        self.store.db.executemany("INSERT INTO files VALUES(?,?,?)",
                                  [("mac", "/codex.jsonl", "[6,1,2]"), ("mac", "/claude.jsonl", '["claude",1,2,3]')])
        self.store.db.commit()
        self.store.save_settings({"claude_enabled": True})
        self.assertEqual(len(self.store.known("mac")), 2)
        self.store.save_settings({"claude_home": "/new-claude"})
        self.assertEqual(self.store.known("mac"), {"/codex.jsonl": [6, 1, 2]})
        self.store.save_settings({"remote_hosts": [{"id": "lab"}], "enabled_hosts": ["mac", "lab"]})
        self.store.db.executemany("INSERT INTO files VALUES(?,?,?)",
                                  [("lab", "/c.jsonl", "[6,1,2]"), ("lab", "/cl.jsonl", '["claude",1,2,3]')])
        self.store.db.commit()
        self.store.save_settings({"remote_hosts": [{"id": "lab", "claude_home": "/remote-claude"}]})
        self.assertEqual(self.store.known("lab"), {})
        self.assertEqual(self.store.known("mac"), {"/codex.jsonl": [6, 1, 2]})

    def test_settings_normalize_claude_fields_atomically(self):
        defaults = self.store.settings()
        self.assertIs(defaults["claude_enabled"], False)
        self.assertEqual(defaults["claude_home"], "")
        self.store.save_settings({"claude_enabled": True, "claude_home": "/tmp/claude"})
        settings = self.store.settings()
        self.assertIs(settings["claude_enabled"], True)
        self.assertEqual(settings["claude_home"], "/tmp/claude")
        with self.assertRaises(ValueError):
            self.store.save_settings({"claude_home": "/x\nrm -rf"})
        self.assertEqual(self.store.settings(), settings)

    def test_legacy_database_gains_agent_column_without_losing_rows(self):
        conv = conversation()
        self.ingest(conv)
        self.store.db.close()
        legacy = sqlite3.connect(str(pathlib.Path(self.tmp.name)/"todos.sqlite"))
        legacy.execute("ALTER TABLE conversations DROP COLUMN agent")
        legacy.commit()
        legacy.close()
        self.store = Store(self.tmp.name)
        row = self.store.db.execute("SELECT agent,title FROM conversations WHERE id=?", (conv["id"],)).fetchone()
        self.assertEqual(row["agent"], "codex")
        self.assertEqual(row["title"], conv["title"])


class ClaudeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.codex = make_codex_root(self.tmp.name)
        self.claude = make_claude_root(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_collection_merges_claude_when_enabled(self):
        settings = {"codex_home": str(self.codex), "claude_enabled": True, "claude_home": str(self.claude)}
        result = collect_host("mac", {}, settings)
        self.assertEqual(sorted(c.get("agent", "codex") for c in result["conversations"]), ["claude", "codex"])
        self.assertEqual(result["total_files"], 2)
        self.assertEqual(result["read_errors"], [])
        self.assertEqual(result["root"], str(self.codex))
        self.assertTrue(all(c["host"] == "mac" for c in result["conversations"]))

    def test_disabled_claude_never_reads_the_claude_root(self):
        settings = {"codex_home": str(self.codex), "claude_home": str(self.root_missing)}
        result = collect_host("mac", {}, settings)
        self.assertEqual([c.get("agent", "codex") for c in result["conversations"]], ["codex"])
        self.assertEqual(result["read_errors"], [])

    @property
    def root_missing(self):
        return pathlib.Path(self.tmp.name)/"missing"

    def test_claude_failure_keeps_codex_data_and_reports_partial_error(self):
        settings = {"codex_home": str(self.codex), "claude_enabled": True, "claude_home": str(self.root_missing)}
        result = collect_host("mac", {}, settings)
        self.assertEqual([c.get("agent", "codex") for c in result["conversations"]], ["codex"])
        self.assertEqual(len(result["read_errors"]), 1)
        self.assertTrue(result["read_errors"][0]["path"].startswith("claude:"))
        self.assertIn("projects", result["read_errors"][0]["error"])

    def test_ssh_wrapper_ships_both_collectors_and_merges_read_only(self):
        rollout = self.codex/"sessions"/"rollout.jsonl"
        before = rollout.read_bytes()
        real_run = subprocess.run

        def run(args, **kwargs):
            self.assertIn("HostName=192.0.2.30", args)
            self.assertIn("StrictHostKeyChecking=yes", args)
            return real_run([sys.executable] + shlex.split(args[-1])[1:], **kwargs)

        settings = {"claude_enabled": True, "remote_hosts": [
            {"id": "lab", "hostname": "192.0.2.30", "codex_home": str(self.codex), "claude_home": str(self.claude)}]}
        with patch("service.subprocess.run", side_effect=run):
            result = collect_host("lab", {}, settings)
        self.assertEqual(sorted(c.get("agent", "codex") for c in result["conversations"]), ["claude", "codex"])
        self.assertTrue(all(c["host"] == "lab" for c in result["conversations"]))
        self.assertEqual(result["total_files"], 2)
        self.assertEqual(result["read_errors"], [])
        self.assertEqual(rollout.read_bytes(), before)

    def test_ssh_claude_failure_keeps_codex_and_reports_error(self):
        real_run = subprocess.run

        def run(args, **kwargs):
            return real_run([sys.executable] + shlex.split(args[-1])[1:], **kwargs)

        settings = {"claude_enabled": True, "remote_hosts": [
            {"id": "lab", "hostname": "192.0.2.30", "codex_home": str(self.codex), "claude_home": str(self.root_missing)}]}
        with patch("service.subprocess.run", side_effect=run):
            result = collect_host("lab", {}, settings)
        self.assertEqual([c.get("agent", "codex") for c in result["conversations"]], ["codex"])
        self.assertEqual(result["read_errors"][0]["path"], "claude")

    def test_open_thread_for_claude_returns_resume_command_over_stdio(self):
        folder = pathlib.Path(self.tmp.name)/"service"
        store = Store(str(folder))
        thread = str(uuid.uuid4())
        claude = dict(conversation("mac:" + thread), agent="claude", cwd="/workspace/example")
        store.ingest(dict(host="mac", files={}, conversations=[claude], total_files=1, remaining_files=0, root="/tmp"))
        store.save_settings({"automatic": False})
        store.db.close()
        proc = subprocess.Popen([sys.executable, str(ROOT/"backend/service.py"), "--data-dir", str(folder), "serve"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1, start_new_session=True)
        try:
            proc.stdin.write(json.dumps({"id": "o1", "method": "open_thread", "entity_id": claude["id"]}) + "\n")
            proc.stdin.flush()
            deadline = time.monotonic() + 8
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise AssertionError("service closed its response stream")
                response = json.loads(line)
                if response.get("id") == "o1":
                    break
                if time.monotonic() > deadline:
                    raise AssertionError("timed out waiting for open_thread")
            self.assertNotIn("error", response)
            result = response["result"]
            self.assertFalse(result["opened"])
            self.assertEqual(result["command"], "cd /workspace/example && claude --resume " + thread)
            self.assertTrue(result["detail"])
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=2)
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(proc.returncode, 0)


class ClaudeConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.codex = make_codex_root(self.tmp.name)
        self.claude = make_claude_root(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalize_remote_and_settings_accept_claude_home(self):
        entry = normalize_remote({"id": "lab", "claude_home": "/data/claude"})
        self.assertEqual(entry["claude_home"], "/data/claude")
        with self.assertRaises(ValueError):
            normalize_remote({"id": "lab", "claude_home": "/x\nbad"})
        settings = normalize_settings({"claude_enabled": True, "claude_home": "/data/claude"})
        self.assertIs(settings["claude_enabled"], True)
        self.assertEqual(settings["claude_home"], "/data/claude")
        defaults = normalize_settings({})
        self.assertIs(defaults["claude_enabled"], False)
        self.assertEqual(defaults["claude_home"], "")
        with self.assertRaises(ValueError):
            normalize_settings({"claude_home": "/x\nbad"})

    def test_local_check_reports_claude_readiness_without_gating_codex(self):
        settings = {"codex_home": str(self.codex), "claude_enabled": True, "claude_home": str(self.claude)}
        result = local_check(settings)
        self.assertTrue(result["sessions_ready"])
        self.assertTrue(result["claude_ready"])
        self.assertIn("Claude", result["detail"])
        settings["claude_home"] = str(pathlib.Path(self.tmp.name)/"missing")
        result = local_check(settings)
        self.assertTrue(result["sessions_ready"])
        self.assertFalse(result["claude_ready"])
        result = local_check({"codex_home": str(self.codex)})
        self.assertNotIn("claude_ready", result)

    def test_remote_check_passes_claude_root_and_reports_readiness(self):
        real_run = subprocess.run

        def run(args, **kwargs):
            self.assertIn("StrictHostKeyChecking=yes", args)
            return real_run([sys.executable] + shlex.split(args[-1])[1:], **kwargs)

        entry = {"id": "lab", "codex_home": str(self.codex), "claude_home": str(self.claude)}
        with patch("connections.subprocess.run", side_effect=run):
            result = remote_check(entry, claude_enabled=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["claude_ready"])
        self.assertIn("Claude", result["detail"])
        entry["claude_home"] = str(pathlib.Path(self.tmp.name)/"missing")
        with patch("connections.subprocess.run", side_effect=run):
            result = remote_check(entry, claude_enabled=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["claude_ready"])
        with patch("connections.subprocess.run", side_effect=run):
            result = remote_check(entry)
        self.assertNotIn("claude_ready", result)


if __name__ == "__main__":
    unittest.main()