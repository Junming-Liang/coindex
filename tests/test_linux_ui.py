"""Focused checks for the Linux frontend and its real private stdio lifecycle."""
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
import json
import threading
import uuid
from unittest.mock import patch

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None
    ttk = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from linux.app import CoindexApp, SettingsDialog, StdioClient, demo_snapshot


class DemoUITests(unittest.TestCase):
    def setUp(self):
        if tk is None:
            self.skipTest("Tkinter is unavailable")
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: %s" % error)
        self.root.withdraw()
        self.app = CoindexApp(self.root, demo=True, demo_data=demo_snapshot())

    def tearDown(self):
        if getattr(self, "root", None):
            try:
                self.root.update_idletasks()
                self.app.close()
            except tk.TclError:
                pass

    def test_demo_is_read_only_and_filters_task_list(self):
        self.assertIsNone(self.app.client)
        self.assertEqual(len(self.app.visible_task_ids), 3)
        self.app.kind_var.set("结果校对")
        self.app._render_tasks()
        self.assertEqual(len(self.app.visible_task_ids), 1)
        self.app.kind_var.set("全部类型")
        self.app.search_var.set("基准测试")
        self.app._render_tasks()
        self.assertEqual(len(self.app.visible_task_ids), 1)
        self.assertTrue(self.app.primary_button.instate(["disabled"]))
        self.assertTrue(self.app.settings_button.instate(["disabled"]))
        self.app.open_settings()
        self.assertFalse(any(isinstance(child, tk.Toplevel) for child in self.root.winfo_children()))

    def test_demo_snapshot_contains_separate_progress_and_action(self):
        task = demo_snapshot()["tasks"][0]
        self.assertTrue(task["progress"])
        self.assertTrue(task["next_action"])
        self.assertIn("本机 / Linux", [h["name"] for h in demo_snapshot()["hosts"]])

    def test_filter_selection_never_leaves_details_on_a_hidden_task(self):
        self.app._select_task("demo-task-0")
        self.app.search_var.set("基准测试")
        self.assertEqual(self.app.visible_task_ids, ["demo-task-2"])
        self.assertEqual(self.app.selected_task, "demo-task-2")
        self.app.search_var.set("no fictional task has this phrase")
        self.assertIsNone(self.app.selected_task)
        self.assertFalse(self.app.detail.winfo_manager())
        self.app._clear_filters()
        self.assertEqual(self.app.result_count, 3)
        self.assertTrue(self.app.detail.winfo_manager())

    def test_sidebar_filters_and_conversation_switch_restore_task_controls(self):
        self.app._choose_kind("结果校对")
        self.assertEqual(self.app.visible_task_ids, ["demo-task-0"])
        self.app._switch("conversations")
        self.assertFalse(self.app.primary_button.winfo_manager())
        self.assertFalse(self.app.task_filters.winfo_manager())
        self.app._choose_kind("全部类型")
        self.assertTrue(self.app.primary_button.winfo_manager())
        self.assertTrue(self.app.task_filters.winfo_manager())
        self.assertEqual(self.app.result_count, 3)
        self.app._choose_history()
        self.assertTrue(self.app.show_inactive)
        self.assertEqual(self.app.result_count, 0)

    def test_minimum_window_keeps_primary_controls_and_long_details_reachable(self):
        self.root.geometry("1000x680")
        self.root.deiconify()
        self.root.update()
        right = self.root.winfo_rootx() + self.root.winfo_width()
        for widget in (self.app.primary_button, self.app.update_button, self.app.host_box):
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right)
            self.assertGreater(widget.winfo_width(), 20)
        self.app.snapshot["tasks"][0]["evidence"] = "Fictional long evidence. " * 100
        self.app._select_task("demo-task-0")
        self.root.update_idletasks()
        self.assertLess(self.app.detail_canvas.yview()[1], 1)
        self.app.detail_canvas.yview_moveto(1)
        self.root.update_idletasks()
        self.assertAlmostEqual(self.app.detail_canvas.yview()[1], 1, places=2)

    def test_settings_save_failure_preserves_the_form(self):
        dialog = SettingsDialog(self.app)
        self.app._rpc = lambda _method, callback=None, **_values: callback({"error": "Fictional validation failure"})
        with patch("linux.app.messagebox.showerror") as error:
            dialog._save()
        self.assertTrue(dialog.win.winfo_exists())
        self.assertEqual(error.call_args.args[1], "Fictional validation failure")
        self.app._rpc = lambda _method, callback=None, **_values: callback({"result": demo_snapshot()})
        dialog._save()
        self.assertFalse(dialog.win.winfo_exists())

    def test_task_action_uses_stdio_rpc_transport(self):
        calls = []

        class Process:
            @staticmethod
            def poll():
                return None

        class Client:
            process = Process()
            closed = False

            def request(self, method, callback=None, **values):
                calls.append((method, values))
                return "request-id"

            @staticmethod
            def drain():
                pass

            def close(self):
                self.closed = True

        app = CoindexApp(self.root, demo=False, client_factory=lambda *_args: Client(), demo_data=demo_snapshot())
        app._act("complete", app.snapshot["tasks"][0])
        self.assertEqual(calls[-1][0], "act")
        self.assertEqual(calls[-1][1]["action"], "complete")
        self.assertEqual(calls[-1][1]["entity_id"], "demo-task-0")
        app.snapshot["schedule"]["off_duty"] = True
        app.toggle_workday()
        self.assertEqual(calls[-1][0], "resume_workday")
        app.snapshot["sync"]["running"] = True
        app._render()
        self.assertTrue(app.stop_button.winfo_manager())
        app.cancel_sync()
        self.assertEqual(calls[-1][0], "cancel_sync")
        app.client.close()

    def test_first_incomplete_snapshot_prompts_once_and_shows_health_details(self):
        class FakeClient:
            closed = False
            class process:
                @staticmethod
                def poll(): return None
            def request(self, method, callback=None, **values): return "rpc-id"
            def drain(self): pass
            def close(self): self.closed = True

        app = CoindexApp(self.root, demo=False, client_factory=lambda *_: FakeClient(), demo_data=demo_snapshot())
        prompted = []
        app.open_settings = lambda: prompted.append(True)
        data = demo_snapshot()
        data["hosts"].append({"id": "server", "name": "测试机", "status": "offline", "detail": "SSH 不可达"})
        data["model_error"] = "模型请求失败"
        app._snapshot_result({"result": data})
        self.root.update_idletasks()
        self.assertEqual(prompted, [True])
        self.assertIn("请先检查本机连接", app.sidebar_status.cget("text"))
        self.assertIn("模型请求失败", app.status_var.get())
        self.assertIn("SSH 不可达", app.status_var.get())
        app._snapshot_result({"result": data})
        self.root.update_idletasks()
        self.assertEqual(prompted, [True])
        app.client.close()

    def test_closed_task_is_history_and_has_no_task_reopen_action(self):
        calls = []

        class FakeClient:
            closed = False
            class process:
                @staticmethod
                def poll(): return None
            def request(self, method, callback=None, **values):
                calls.append((method, values))
                return "rpc-id"
            def drain(self): pass
            def close(self): self.closed = True

        data = demo_snapshot()
        data["tasks"][0]["status"] = "conversation_closed"
        data["tasks"][1]["status"] = "done"
        app = CoindexApp(self.root, demo=False, client_factory=lambda *_: FakeClient(), demo_data=data)
        app._render()
        self.assertEqual(app.visible_task_ids, ["demo-task-2"])
        data["tasks"][2]["snoozed_until"] = time.time() + 3600
        app.snapshot = data
        app.show_inactive = True
        app._render_tasks()
        self.assertEqual(set(app.visible_task_ids), {"demo-task-0", "demo-task-1", "demo-task-2"})
        app._select_task("demo-task-0")
        self.assertFalse(any(isinstance(w, ttk.Button) and w.cget("text") == "重新打开"
                             for w in self._descendants(app.detail_content)))
        app.client.close()

    @staticmethod
    def _descendants(widget):
        result = []
        for child in widget.winfo_children():
            result.append(child)
            result.extend(DemoUITests._descendants(child))
        return result

    def test_nudge_receipt_is_visible_and_pending_send_is_disabled(self):
        class FakeClient:
            closed = False
            class process:
                @staticmethod
                def poll(): return None
            def request(self, method, callback=None, **values): return "rpc-id"
            def drain(self): pass
            def close(self): self.closed = True

        data = demo_snapshot()
        data["nudges"] = [{"action_id": "action-1", "conversation_id": data["tasks"][0]["conversation_id"],
                           "status": "sending", "error": "", "attention": "正在与原对话连接", "updated_at": time.time()}]
        app = CoindexApp(self.root, demo=False, client_factory=lambda *_: FakeClient(), demo_data=data)
        app._select_task("demo-task-0")
        labels = [w.cget("text") for w in self._descendants(app.detail_content) if isinstance(w, tk.Label)]
        self.assertIn("正在发送\n正在与原对话连接", labels)
        buttons = [w for w in self._descendants(app.detail_content) if isinstance(w, ttk.Button)]
        nudge = next(w for w in buttons if w.cget("text") == "轻推原对话…")
        self.assertEqual(str(nudge.cget("state")), "disabled")
        app.client.close()

    def test_unknown_nudge_requires_confirmation_and_uses_new_action_id(self):
        import linux.app as ui
        calls = []

        class FakeClient:
            closed = False
            class process:
                @staticmethod
                def poll(): return None
            def request(self, method, callback=None, **values):
                calls.append((method, values))
                return "rpc-id"
            def drain(self): pass
            def close(self): self.closed = True

        data = demo_snapshot()
        task = data["tasks"][0]
        data["nudges"] = [{"action_id": "prior-action", "conversation_id": task["conversation_id"],
                           "status": "unknown", "error": "请核对原对话", "attention": "", "updated_at": time.time()}]
        app = CoindexApp(self.root, demo=False, client_factory=lambda *_: FakeClient(), demo_data=data)
        app._render()
        before = len(calls)
        original_ask = ui.messagebox.askyesno
        ui.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            app._nudge(task)
        finally:
            ui.messagebox.askyesno = original_ask
        self.assertEqual(len(calls), before + 1)
        method, values = calls[-1]
        self.assertEqual(method, "nudge")
        self.assertTrue(values["retry_unknown"])
        self.assertNotEqual(values["action_id"], "prior-action")
        uuid.UUID(values["action_id"])
        app.client.close()

    def test_claude_task_shows_source_badge_and_hides_nudge(self):
        data = demo_snapshot()
        data["tasks"].append(dict(data["tasks"][0], id="demo-task-claude", conversation_id="mac:demo-claude",
                                  thread_id="demo-claude", agent="claude", kind="continue"))
        data["conversations"].append(dict(data["conversations"][0], id="mac:demo-claude",
                                          thread_id="demo-claude", agent="claude"))
        app = CoindexApp(self.root, demo=True, demo_data=data)
        self.assertEqual(app._source_label({"host": "mac", "agent": "claude"}), "本机 · Claude")
        self.assertEqual(app._source_label({"host": "mac"}), "本机")
        app._select_task("demo-task-claude")
        labels = [w.cget("text") for w in self._descendants(app.detail_content) if isinstance(w, tk.Label)]
        self.assertIn("本机 · Claude", labels)
        buttons = [w.cget("text") for w in self._descendants(app.detail_content) if isinstance(w, ttk.Button)]
        self.assertNotIn("轻推原对话…", buttons)
        app._switch("conversations")
        values = app.conversations.item("mac:demo-claude", "values")
        self.assertIn("Claude", values[0])

    def test_claude_resume_copies_command_without_rpc(self):
        import linux.app as ui
        calls = []

        class FakeClient:
            closed = False
            class process:
                @staticmethod
                def poll(): return None
            def request(self, method, callback=None, **values):
                calls.append((method, values))
                return "rpc-id"
            def drain(self): pass
            def close(self): self.closed = True

        data = demo_snapshot()
        data["tasks"].append(dict(data["tasks"][0], id="demo-task-claude", conversation_id="mac:demo-claude",
                                  thread_id="demo-claude", agent="claude", kind="continue", cwd="/workspace/example"))
        app = CoindexApp(self.root, demo=False, client_factory=lambda *_: FakeClient(), demo_data=data)
        app._select_task("demo-task-claude")
        calls.clear()  # The client requests an initial snapshot on startup.
        with patch.object(ui.messagebox, "askyesno", return_value=True) as ask:
            app.open_conversation()
        self.assertTrue(ask.called)
        self.assertEqual(calls, [])
        self.assertEqual(self.root.clipboard_get(), "cd /workspace/example && claude --resume demo-claude")
        self.assertIn("已复制", app.status_var.get())
        with patch.object(ui.messagebox, "askyesno", return_value=True):
            app._claude_resume({"cwd": "/tmp/a b", "thread_id": "x'y"})
        self.assertEqual(self.root.clipboard_get(), "cd '/tmp/a b' && claude --resume 'x'\"'\"'y'")
        app.client.close()

    def test_settings_dialog_round_trips_claude_source(self):
        dialog = SettingsDialog(self.app)
        self.assertIn("claude_enabled", dialog.vars)
        self.assertIn("claude_home", dialog.vars)
        dialog.vars["claude_enabled"].set(True)
        dialog.vars["claude_home"].set("/tmp/claude-home")
        values = dialog._values()
        self.assertIs(values["claude_enabled"], True)
        self.assertEqual(values["claude_home"], "/tmp/claude-home")
        dialog.win.destroy()

    def test_connection_gate_requires_local_success_and_failed_retest_clears_it(self):
        import linux.app as ui
        calls = []

        class AppProxy:
            def _rpc(self, method, callback=None, **values):
                calls.append((method, values))
            @staticmethod
            def _mutation_result(_response):
                pass

        dialog = object.__new__(SettingsDialog)
        dialog.app = AppProxy()
        dialog.win = self.root
        dialog.saved = {"connection_setup_complete": False}
        dialog.vars = {key: tk.StringVar(master=self.root, value=value) for key, value in
                       (("codex_home", ""), ("codex_cli", ""), ("codex_app", ""))}
        dialog._local_connection_succeeded = False
        dialog._tested_local_paths = None
        original_showinfo, original_showerror = ui.messagebox.showinfo, ui.messagebox.showerror
        ui.messagebox.showinfo = lambda *args, **kwargs: None
        ui.messagebox.showerror = lambda *args, **kwargs: None
        try:
            dialog._checked({"result": {"ok": True, "detail": "SSH ok"}}, local=False)
            self.assertFalse(dialog.saved["connection_setup_complete"])
            self.assertEqual(calls, [])
            dialog._checked({"result": {"ok": True, "detail": "local ok"}}, local=True)
            self.assertTrue(dialog.saved["connection_setup_complete"])
            self.assertEqual(calls[-1], ("settings", {"values": {"connection_setup_complete": True}}))
            dialog._checked({"result": {"ok": False, "detail": "local failed"}}, local=True)
            self.assertFalse(dialog.saved["connection_setup_complete"])
            self.assertEqual(calls[-1], ("settings", {"values": {"connection_setup_complete": False}}))
            dialog._initial_local_paths = ("", "", "")
            dialog._local_connection_succeeded = False
            dialog.vars["codex_cli"].set("/changed/codex")
            self.assertFalse(dialog._values()["connection_setup_complete"])
            dialog._checking_local_paths = ("", "", "")
            dialog._checked({"result": {"ok": True, "detail": "old path ok"}}, local=True)
            self.assertFalse(dialog.saved["connection_setup_complete"])
            self.assertFalse(dialog._local_connection_succeeded)
            dialog.vars["work_start_minutes"] = tk.StringVar(master=self.root, value="09:30")
            self.assertEqual(dialog._values()["work_start_minutes"], 570)
            dialog.vars["work_start_minutes"].set("24:30")
            with self.assertRaisesRegex(ValueError, "HH:MM"):
                dialog._values()
        finally:
            ui.messagebox.showinfo, ui.messagebox.showerror = original_showinfo, original_showerror


class StdioClientTests(unittest.TestCase):
    def test_client_dispatches_on_caller_thread_and_reaps_after_eof(self):
        callback_errors, exits = [], []
        child = "import json,sys\nfor line in sys.stdin:\n r=json.loads(line); print(json.dumps({'id':r['id'],'result':{'ok':True}}),flush=True)\n"
        client = StdioClient([sys.executable, "-u", "-c", child], lambda _m: None,
                             lambda code: exits.append(code), callback_errors.append)
        caller = threading.get_ident()

        def broken_callback(_response):
            self.assertEqual(threading.get_ident(), caller)
            raise RuntimeError("callback test error")

        client.request("snapshot", broken_callback)
        self._drain_until(client, lambda: bool(callback_errors))
        self.assertIn("callback test error", str(callback_errors[0]))
        started = time.monotonic()
        client.close()
        self.assertLess(time.monotonic() - started, 0.2)
        client.process.wait(timeout=3)
        self._drain_until(client, lambda: bool(exits))
        self.assertEqual(client.process.returncode, 0)

    def test_process_exit_completes_pending_request_with_error(self):
        responses, exits = [], []
        child = "import time; time.sleep(10)"
        client = StdioClient([sys.executable, "-u", "-c", child], lambda _m: None,
                             lambda code: exits.append(code))
        client.request("snapshot", responses.append)
        client.process.terminate()
        client.close()
        self._drain_until(client, lambda: bool(responses) and bool(exits))
        self.assertIn("error", responses[0])
        self.assertIsNotNone(client.process.returncode)

    def test_invalid_response_object_surfaces_an_error_without_stopping_dispatch(self):
        errors = []
        child = "import sys\nprint('42',flush=True)\nsys.stdin.read()\n"
        client = StdioClient([sys.executable, "-u", "-c", child], lambda _m: None,
                             on_callback_error=errors.append)
        try:
            self._drain_until(client, lambda: bool(errors))
            self.assertIn("无法识别", str(errors[0]))
        finally:
            client.close()
            client.process.wait(timeout=3)

    @staticmethod
    def _drain_until(client, condition):
        deadline = time.monotonic() + 4
        while not condition() and time.monotonic() < deadline:
            client.drain()
            time.sleep(0.01)
        client.drain()
        if not condition():
            raise AssertionError("stdio client event did not arrive")


class StdioLifecycleTests(unittest.TestCase):
    def test_service_snapshot_manual_task_and_clean_eof_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="coindex-ui-test-") as folder:
            proc = subprocess.Popen([sys.executable, str(ROOT / "backend/service.py"), "--data-dir", folder, "serve"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, bufsize=1, start_new_session=True)
            try:
                proc.stdin.write('{"id":"s1","method":"snapshot"}\n')
                proc.stdin.flush()
                first = self._read_response(proc, "s1")
                self.assertIn("settings", first["result"])
                proc.stdin.write('{"id":"m1","method":"save_manual","title":"GUI lifecycle check","detail":"temporary data only","priority":2}\n')
                proc.stdin.flush()
                saved = self._read_response(proc, "m1")["result"]
                self.assertEqual(saved["snapshot"]["tasks"][-1]["title"], "GUI lifecycle check")
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

    @staticmethod
    def _read_response(proc, request_id):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise AssertionError("service closed its response stream")
            response = json.loads(line)
            if response.get("id") == request_id:
                if response.get("error"):
                    raise AssertionError(response["error"])
                return response
        raise AssertionError("timed out waiting for %s" % request_id)


if __name__ == "__main__":
    unittest.main()
