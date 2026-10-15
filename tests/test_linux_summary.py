"""Linux summary UI regression checks with synthetic service responses."""
import copy
import pathlib
import tempfile
import unittest
from unittest.mock import patch

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None

from linux.app import CoindexApp, demo_snapshot
from linux.summaries import SummaryScheduleDialog, SummaryWizard, range_request


def summary_row(identifier="report-1", status="completed"):
    return {"id": identifier, "title": "近三天的工作总结", "status": status, "scope": "period",
            "start_date": "2026-10-13", "end_date": "2026-10-15", "created_at": 1792040000,
            "finished_at": 1792040010 if status == "completed" else 0, "task_count": 3,
            "origin": "manual", "model": "fixture", "effort": "max", "error": "",
            "work_only": True, "excluded_count": 1, "uncertain_count": 1}


class SummaryRangeTests(unittest.TestCase):
    @patch("linux.summaries.today_string", return_value="2026-10-15")
    def test_presets_are_calendar_ranges_and_active_ignores_hidden_dates(self, _today):
        self.assertEqual(range_request("active", "自定义日期", "invalid", "invalid"), {"scope": "active"})
        self.assertEqual(range_request("all", "自定义日期", "invalid", "invalid"), {"scope": "all"})
        for label, days in (("今天", 1), ("近三天", 3), ("近一周", 7)):
            self.assertEqual(range_request("period", label, "", ""), {"scope": "period", "days": days})
        self.assertEqual(range_request("period", "自定义日期", "2026-10-15", "2026-10-15"),
                         {"scope": "period", "start_date": "2026-10-15", "end_date": "2026-10-15"})
        for start, end in (("2026-10-16", "2026-10-15"), ("2026-02-30", "2026-03-01"),
                           ("2026-10-15", "2026-10-16"), ("20261014", "2026-10-15")):
            with self.assertRaises(ValueError):
                range_request("period", "自定义日期", start, end)


class SummaryUITests(unittest.TestCase):
    def setUp(self):
        today = patch("linux.summaries.today_string", return_value="2026-10-15")
        today.start()
        self.addCleanup(today.stop)
        if tk is None:
            self.skipTest("Tkinter is unavailable")
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: %s" % error)
        self.root.geometry("1240x820")
        data = demo_snapshot()
        data["summaries"] = [summary_row()]
        data["summary_schedule"] = {"enabled": False, "frequency": "daily", "scope": "period", "days": 1}
        self.app = CoindexApp(self.root, demo=True, demo_data=data)
        self.app.demo = False
        self.page = self.app.summary_page
        self.calls = []
        self.app._rpc = self.rpc
        self.app._switch("summaries")
        self.root.update()

    def rpc(self, method, callback=None, **values):
        self.calls.append((method, values, callback))
        return "fixture-request"

    def tearDown(self):
        if getattr(self, "root", None):
            try:
                self.app.close()
            except tk.TclError:
                pass

    def last(self, method):
        return next(call for call in reversed(self.calls) if call[0] == method)

    def complete_detail(self, row=None):
        row = row or summary_row()
        detail = dict(row, content="## 示例目标\n" + "**问题背景**：虚构背景。\n具体问题：虚构问题。\n目前实验结果：未记录。\n实验结论：尚无结论。\n" * 45,
                      sources=[{"title": "虚构个人项目", "relevance": "non_work", "relevance_reason": "个人开源应用"},
                               {"title": "虚构待确认事项", "relevance": "uncertain", "relevance_reason": "缺少项目归属"}])
        self.last("summary_detail")[2]({"result": detail})
        self.root.update()
        return detail

    def preview(self, wizard, **result):
        if wizard.timer:
            wizard.win.after_cancel(wizard.timer)
            wizard.timer = None
        wizard._preview(wizard._request(), wizard.preview_serial)
        self.last("summary_preview")[2]({"result": {"task_count": 3, "start_date": "2026-10-13", "end_date": "2026-10-15", **result}})

    def test_navigation_and_unchanged_refresh_preserve_detail_selection_scroll(self):
        self.complete_detail()
        self.assertEqual(self.app.heading_var.get(), "总结")
        self.assertFalse(self.app.task_filters.winfo_manager())
        self.assertFalse(self.app.primary_button.winfo_manager())
        self.page.text.yview_moveto(.45)
        self.page.text.tag_add("sel", "5.0", "5.6")
        self.page.text.focus_set()
        self.root.update()
        scroll, selection = self.page.text.yview(), self.page.text.tag_ranges("sel")
        before = len([call for call in self.calls if call[0] == "summary_detail"])
        self.app.snapshot = copy.deepcopy(self.app.snapshot)
        self.app.snapshot["last_sync"] += 60
        self.app._render()
        self.root.update()
        self.assertEqual(self.page.selected_id, "report-1")
        self.assertEqual(self.page.text.yview(), scroll)
        self.assertEqual(self.page.text.tag_ranges("sel"), selection)
        self.assertEqual(len([call for call in self.calls if call[0] == "summary_detail"]), before)
        self.app._switch("conversations")
        self.assertFalse(self.page.winfo_manager())
        self.app._choose_kind("全部类型")
        self.assertTrue(self.app.primary_button.winfo_manager())
        self.assertTrue(self.app.task_filters.winfo_manager())

    def test_old_detail_response_never_overwrites_completed_report(self):
        self.app.snapshot["summaries"] = [summary_row("changing-report", "running")]
        self.app._render()
        old_callback = self.last("summary_detail")[2]
        self.app.snapshot["summaries"] = [summary_row("changing-report")]
        self.app._render()
        detail = self.complete_detail(summary_row("changing-report"))
        old_callback({"result": dict(summary_row("changing-report", "running"), content="旧响应")})
        self.assertEqual(self.page.current_content, detail["content"])
        self.assertNotIn("旧响应", self.page.text.get("1.0", "end"))

    def test_preview_discards_outdated_range_and_generation_is_single_submission(self):
        wizard = SummaryWizard(self.page)
        self.preview(wizard)
        stale = self.last("summary_preview")[2]
        wizard.scope.set("period")
        wizard.preset.set("近三天")
        wizard.work_only.set(True)
        wizard.work_context.set("虚构工作项目")
        stale({"result": {"task_count": 99}})
        self.assertIsNone(wizard.preview)
        self.preview(wizard)
        self.assertIn("候选待办", wizard.preview_text.get())
        self.assertEqual(self.last("summary_preview")[1], {"scope": "period", "days": 3,
                                                          "work_only": True, "work_context": "虚构工作项目"})
        wizard.generate()
        wizard.generate()
        self.assertEqual(len([call for call in self.calls if call[0] == "summary_generate"]), 1)
        self.assertTrue(wizard.win.winfo_exists())
        snapshot = copy.deepcopy(self.app.snapshot)
        snapshot["summaries"].insert(0, summary_row("new-report", "queued"))
        self.last("summary_generate")[2]({"result": {"summary_id": "new-report", "snapshot": snapshot}})
        self.assertFalse(wizard.win.winfo_exists())

    def test_all_saved_scope_includes_archive_preview_and_round_trips_schedule(self):
        wizard = SummaryWizard(self.page)
        wizard.scope.set("all")
        wizard.start.set("invalid hidden date")
        self.preview(wizard, archived_count=2)
        self.assertEqual(self.last("summary_preview")[1]["scope"], "all")
        self.assertIn("归档", wizard.preview_text.get())
        self.assertIn("2 条", wizard.preview_text.get())
        wizard.win.destroy()
        self.app.snapshot["summary_schedule"]["scope"] = "all"
        editor = SummaryScheduleDialog(self.page)
        self.assertEqual(editor.values()["scope"], "all")
        editor.win.destroy()
        self.assertEqual(self.page.selected_id, "new-report")
        self.page.cancel()
        self.assertEqual(self.last("summary_cancel")[1], {"summary_id": "new-report"})

    def test_snapshot_polling_keeps_draft_and_schedule_save_failure_retains_input(self):
        wizard = SummaryWizard(self.page)
        wizard.scope.set("period")
        wizard.preset.set("自定义日期")
        wizard.start.set("2026-10-01")
        wizard.end.set("2026-10-15")
        dialog = SummaryScheduleDialog(self.page)
        dialog.enabled.set(True)
        dialog.frequency.set("每周")
        dialog.weekday.set("周五")
        dialog.time.set("17:45")
        dialog.work_only.set(True)
        dialog.work_context.set("虚构工作")
        self.app.snapshot["summary_schedule"]["frequency"] = "interval"
        self.app._render()
        self.assertEqual(wizard.start.get(), "2026-10-01")
        self.assertEqual(dialog.frequency.get(), "每周")
        dialog.save()
        sent = self.last("summary_settings")[1]["values"]
        self.assertEqual((sent["frequency"], sent["weekday"], sent["time_minutes"]), ("weekly", 4, 1065))
        self.assertTrue(sent["work_only"])
        self.last("summary_settings")[2]({"error": "虚构保存失败"})
        self.assertTrue(dialog.win.winfo_exists())
        self.assertEqual(dialog.error.get(), "虚构保存失败")
        self.assertFalse(dialog.saving)
        dialog.save()
        self.last("summary_settings")[2]({"result": self.app.snapshot})
        self.assertFalse(dialog.win.winfo_exists())

    def test_empty_preview_blocks_generation_and_closed_wizard_ignores_response(self):
        wizard = SummaryWizard(self.page)
        self.preview(wizard, task_count=0)
        wizard.generate()
        self.assertFalse(any(call[0] == "summary_generate" for call in self.calls))
        callback = self.last("summary_preview")[2]
        wizard.win.destroy()
        callback({"result": {"task_count": 4}})

    def test_minimum_window_keeps_summary_and_footer_actions_reachable(self):
        self.complete_detail()
        self.root.geometry("1000x680")
        self.root.update()
        bottom = self.root.winfo_rooty() + self.root.winfo_height()
        right = self.root.winfo_rootx() + self.root.winfo_width()
        for widget in (self.app.nav_summaries, self.app.settings_button, self.app.check_updates_button,
                       self.app.workday_button, self.page.copy_button, self.page.audit_button, self.page.export_button):
            self.assertTrue(widget.winfo_ismapped(), str(widget))
            self.assertGreater(widget.winfo_height(), 20)
            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(),
                                    str(widget) + " must show its full label")
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right)

    def test_large_navigation_font_scrolls_without_hiding_persistent_actions(self):
        self.root.geometry("1000x680")
        style = ttk.Style(self.root)
        for name in ("Nav.TButton", "Selected.Nav.TButton"):
            style.configure(name, font=(self.app.font_family, 18))
        self.root.update()
        canvas = self.app.sidebar_canvas
        self.assertLess(canvas.yview()[1], 1)
        for button in (self.app.nav_summaries, self.app.settings_button, self.app.check_updates_button, self.app.workday_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
        self.app.history_button.focus_force()
        self.root.update()
        self.assertLessEqual(self.app.history_button.winfo_rooty() + self.app.history_button.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height() + 1)

    def test_short_display_keeps_dialog_actions_visible_and_form_scrollable(self):
        wizard = SummaryWizard(self.page)
        settings = SummaryScheduleDialog(self.page)
        for dialog, action in ((wizard, wizard.generate_button), (settings, settings.save_button)):
            dialog.win.geometry("620x520")
            self.root.update()
            self.assertLessEqual(action.winfo_rooty() + action.winfo_height(),
                                 dialog.win.winfo_rooty() + dialog.win.winfo_height())
            self.assertGreater(action.winfo_width(), 50)
            self.assertLess(dialog.canvas.yview()[1], 1)
            dialog.canvas.yview_moveto(1)
            self.root.update_idletasks()
            self.assertAlmostEqual(dialog.canvas.yview()[1], 1, places=2)

    def test_copy_export_keeps_markdown_and_work_filter_audit_explains_exclusions(self):
        detail = self.complete_detail()
        with patch.object(self.page, "clipboard_clear") as clear, patch.object(self.page, "clipboard_append") as append:
            self.page.copy_content()
        clear.assert_called_once()
        append.assert_called_once_with(detail["content"])
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "report.md"
            with patch("linux.summaries.filedialog.asksaveasfilename", return_value=str(destination)):
                self.page.export_content()
            self.assertEqual(destination.read_text(), detail["content"] + "\n")
        self.assertTrue(self.page.audit_button.winfo_manager())
        self.page.show_audit()
        windows = [child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel)]
        self.assertTrue(windows)
        def texts(widget):
            found = [widget.get("1.0", "end")] if isinstance(widget, tk.Text) else []
            for child in widget.winfo_children():
                found.extend(texts(child))
            return found
        audit = "".join(texts(windows[-1]))
        self.assertIn("个人项目 · 已排除", audit)
        self.assertIn("缺少项目归属", audit)
        self.assertIn("范围待确认 · 已保留", audit)


if __name__ == "__main__":
    unittest.main()
