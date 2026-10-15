"""Summary range, coverage, cancellation and scheduling without real model calls."""
import datetime as dt
import json
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from store import Store
from schedule import ZONE, finish_workday, normalize_calendar, refresh_needed
import summaries
from test_backend import conversation, entry


def stamp(value):
    return dt.datetime.fromisoformat(value).replace(tzinfo=ZONE).timestamp()


def response(prompt, schema, **kwargs):
    data = json.loads(prompt.split("<untrusted_summary_data>")[1].split("</untrusted_summary_data>")[0])
    return {"items": [dict(id=t["id"], background="验证上传性能", problem="上传耗时过长", results="已提交实验，暂无结果记录",
                           conclusion="尚无可验证结论", relevance="work", relevance_reason="工作实验", evidence_indices=[0])
                      for t in data["tasks"]]}


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.now = stamp("2026-10-15T12:00")

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def manual(self, title="工作实验", when=None):
        with patch("store.time.time", return_value=when or self.now):
            return self.store.save_manual(title, "比较新旧方案")

    def test_active_contains_manual_snoozed_and_excludes_finished_and_archived(self):
        active = self.manual()
        snoozed = self.manual("稍后处理")
        self.store.act("snooze", snoozed, 60)
        done = self.manual("已完成")
        self.store.act("complete", done)
        conv = conversation(updated=self.now)
        self.store.ingest(dict(host="mac", files={}, conversations=[conv], total_files=1, remaining_files=0, root="/example"))
        self.store.reconcile([entry()], [conv])
        self.store.ingest(dict(host="mac", files={}, conversations=[], total_files=1, remaining_files=0, root="/example",
                               archive_states={conv["thread_id"]: True}))
        result = summaries.select_sources(self.store, summaries.options({"scope": "active"}, self.now))
        self.assertEqual({x["id"] for x in result}, {active, snoozed})

    def test_period_inclusive_beijing_boundaries_and_completed_records(self):
        before = self.manual("之前", stamp("2026-10-14T23:59:59"))
        first = self.manual("零点", stamp("2026-10-15T00:00"))
        last = self.manual("最后一秒", stamp("2026-10-15T23:59:59"))
        after = self.manual("之后", stamp("2026-10-16T00:00"))
        with patch("store.time.time", return_value=self.now):
            self.store.act("complete", before)
        selection = summaries.options({"scope": "period", "days": 1}, self.now)
        ids = {s["id"] for s in summaries.select_sources(self.store, selection)}
        self.assertEqual(ids, {before, first, last})
        self.assertNotIn(after, ids)

    def test_prior_period_retains_activity_after_later_updates(self):
        task_id = self.manual("长期实验", stamp("2026-10-01T12:00"))
        with patch("store.time.time", return_value=stamp("2026-10-12T12:00")):
            self.store.save_manual("长期实验", "周一的新进度", entity_id=task_id)
        with patch("store.time.time", return_value=self.now):
            self.store.save_manual("长期实验", "周四的新进度", entity_id=task_id)
        selected = summaries.select_sources(self.store, summaries.options({"scope": "period", "start_date": "2026-10-12", "end_date": "2026-10-12"}, self.now))
        self.assertEqual([x["id"] for x in selected], [task_id])
        self.assertEqual(selected[0]["detail"], "周四的新进度")

    def test_range_includes_archived_and_resolved_but_not_merged_duplicates(self):
        ids = [self.manual(str(i)) for i in range(3)]
        with self.store.db:
            for ident, status in zip(ids, ("conversation_archived", "resolved", "merged")):
                self.store.db.execute("UPDATE tasks SET status=? WHERE id=?", (status, ident))
        result = summaries.select_sources(self.store, summaries.options({"scope": "period", "days": 1}, self.now))
        self.assertEqual({s["id"] for s in result}, set(ids[:2]))

    def test_all_scope_includes_completed_and_archived_without_reopening_tasks(self):
        active = self.manual()
        completed = self.manual("已完成的工作")
        self.store.act("complete", completed)
        conv = conversation(updated=self.now)
        self.store.ingest(dict(host="mac", files={}, conversations=[conv], total_files=1, remaining_files=0, root="/example"))
        self.store.reconcile([entry()], [conv])
        self.store.ingest(dict(host="mac", files={}, conversations=[], total_files=1, remaining_files=0, root="/example",
                               archive_states={conv["thread_id"]: True}))
        before = [tuple(row) for row in self.store.db.execute("SELECT * FROM tasks ORDER BY id")]
        preview = summaries.preview(self.store, {"scope": "all"}, self.now)
        self.assertEqual(preview["task_count"], 3)
        self.assertEqual(preview["archived_count"], 1)
        sid = summaries.create(self.store, {"scope": "all"}, now=self.now)
        summaries.run(self.store, sid, response)
        result = summaries.detail(self.store, sid)
        self.assertEqual(result["status"], "completed")
        self.assertIn("归档", result["title"])
        self.assertEqual({s["id"] for s in result["sources"]} & {active, completed}, {active, completed})
        self.assertEqual(sum(s["conversation_archived"] for s in result["sources"]), 1)
        self.assertEqual(before, [tuple(row) for row in self.store.db.execute("SELECT * FROM tasks ORDER BY id")])
        summaries.save_schedule(self.store, {"scope": "all"}, self.now)
        self.assertEqual(summaries.schedule_settings(self.store)["scope"], "all")

    def test_schema_binds_evidence_to_each_task_instead_of_shared_integer_range(self):
        self.manual("只有待办记录")
        sources = summaries.select_sources(self.store, summaries.options({"scope": "all"}, self.now), True)
        extra = dict(sources[0], id="another-task", records=[{"index": 0}, {"index": 1}, {"index": 2}])
        branches = summaries.batch_schema(sources + [extra])["properties"]["items"]["items"]["anyOf"]
        allowed = {b["properties"]["id"]["enum"][0]: b["properties"]["evidence_indices"]["items"]["enum"] for b in branches}
        self.assertEqual(allowed, {sources[0]["id"]: [0], "another-task": [0, 1, 2]})

    def test_invalid_evidence_is_regenerated_and_never_silently_remapped(self):
        self.manual()
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        calls = []
        def corrected(prompt, schema, **kwargs):
            calls.append(prompt)
            value = response(prompt, schema, **kwargs)
            if len(calls) == 1:
                value["items"][0]["evidence_indices"] = [999]
                value["items"][0]["results"] = "本条无效输出不能被保存"
            return value
        summaries.run(self.store, sid, corrected)
        result = summaries.detail(self.store, sid)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(calls), 2)
        self.assertIn('"indices": [0]', calls[1])
        self.assertNotIn("本条无效输出不能被保存", result["content"])
        self.assertEqual(result["sources"][0]["evidence_indices"], [0])

    def test_cancelling_invalid_response_prevents_corrective_model_calls(self):
        self.manual()
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        def late(prompt, schema, **kwargs):
            summaries.cancel(self.store, sid)
            value = response(prompt, schema, **kwargs)
            value["items"][0]["evidence_indices"] = [999]
            return value
        with patch("summaries.generate_json", side_effect=late) as model:
            summaries.run(self.store, sid)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(summaries.detail(self.store, sid)["status"], "cancelled")

    def test_backfill_is_additive_and_idempotent(self):
        ident = self.manual(when=stamp("2026-10-01T12:00"))
        with patch("store.time.time", return_value=self.now):
            self.store.act("complete", ident)
        before = tuple(self.store.db.execute("SELECT * FROM tasks").fetchone())
        with self.store.db:
            self.store.db.execute("DELETE FROM task_activity")
            self.store.db.execute("DELETE FROM meta WHERE key='summary_activity_backfilled'")
        summaries.init_schema(self.store)
        summaries.init_schema(self.store)
        self.assertEqual(tuple(self.store.db.execute("SELECT * FROM tasks").fetchone()), before)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM task_activity").fetchone()[0], 2)

    def test_invalid_dates_and_settings_do_not_persist(self):
        for request in ({"scope": "invalid"}, {"scope": "period", "start_date": "2026-10-15"},
                        {"scope": "period", "days": True}, {"scope": "period", "days": 0},
                        {"scope": "period", "start_date": "2026-10-15", "end_date": "2026-10-14"},
                        {"scope": "period", "start_date": "2026-10-15", "end_date": "2026-10-16"},
                        {"scope": "active", "work_only": "yes"}):
            with self.assertRaises(ValueError):
                summaries.preview(self.store, request, self.now)
        for values in ({"frequency": "bad"}, {"time_minutes": 1440}, {"weekday": 7}, {"days": -1}, {"interval_hours": 0}):
            with self.assertRaises(ValueError):
                summaries.save_schedule(self.store, values, self.now)
        self.assertEqual(summaries.schedule_settings(self.store), summaries.DEFAULTS)

    def test_candidate_preview_does_not_use_model_or_mutate_todos(self):
        ident = self.manual()
        before = tuple(self.store.db.execute("SELECT * FROM tasks").fetchone())
        with patch("summaries.generate_json") as model:
            result = summaries.preview(self.store, {"scope": "active", "work_only": True}, self.now)
            model.assert_not_called()
        self.assertEqual(result["task_count"], 1)
        self.assertEqual(result["counts"], {"open": 1})
        self.assertEqual(tuple(self.store.db.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone()), before)

    def test_frozen_sources_manual_title_model_and_four_fields(self):
        ident = self.manual("自定义整体目标")
        summary_id = summaries.create(self.store, {"scope": "active"}, now=self.now)
        self.store.save_manual("修改后的标题", entity_id=ident)
        with patch("summaries.generate_json", side_effect=response) as model:
            summaries.run(self.store, summary_id)
        result = summaries.detail(self.store, summary_id)
        self.assertEqual(result["status"], "completed")
        self.assertIn("自定义整体目标", result["content"])
        self.assertNotIn("修改后的标题", result["content"])
        for label, _ in summaries.FIELDS.values():
            self.assertIn(label, result["content"])
        self.assertEqual(model.call_args.kwargs["settings"]["analysis_model"], "gpt-6-luna")
        self.assertEqual(model.call_args.kwargs["settings"]["analysis_effort"], "max")
        self.assertNotIn("content", summaries.history(self.store)[0])
        self.assertNotIn("sources", summaries.history(self.store)[0])

    def test_work_filter_exclusions_auditable_uncertain_retained(self):
        ids = [self.manual(title) for title in ("工作实验", "个人开源 App", "上下文不明")]
        summary_id = summaries.create(self.store, {"scope": "active", "work_only": True, "work_context": "实验属于工作"}, now=self.now)
        def classifier(*args, **kwargs):
            result = response(*args, **kwargs)
            for item in result["items"]:
                item["relevance"] = dict(zip(ids, ("work", "non_work", "uncertain")))[item["id"]]
                item["relevance_reason"] = "根据记录归属判断"
            return result
        summaries.run(self.store, summary_id, classifier)
        result = summaries.detail(self.store, summary_id)
        self.assertEqual(result["excluded_count"], 1)
        self.assertEqual(result["uncertain_count"], 1)
        self.assertIn("上下文不明", result["content"])
        self.assertNotIn("个人开源 App", result["content"])
        self.assertEqual(len(result["sources"]), 3)
        self.assertEqual({r[0] for r in self.store.db.execute("SELECT status FROM tasks")}, {"open"})

    def test_disabled_filter_cannot_silently_exclude(self):
        self.manual()
        summary_id = summaries.create(self.store, {"scope": "active"}, now=self.now)
        def classifier(*args, **kwargs):
            result = response(*args, **kwargs)
            result["items"][0]["relevance"] = "non_work"
            return result
        summaries.run(self.store, summary_id, classifier)
        self.assertEqual(summaries.detail(self.store, summary_id)["excluded_count"], 0)

    def test_incomplete_duplicate_fabricated_evidence_and_verbose_responses_fail(self):
        self.manual("A")
        self.manual("B")
        def missing(value): value["items"].pop()
        def duplicate(value): value["items"][1] = dict(value["items"][0])
        def invented(value): value["items"][0]["evidence_indices"] = [999]
        def verbose(value): value["items"][0]["results"] = "长" * 81
        for modify in (missing, duplicate, invented, verbose):
            summary_id = summaries.create(self.store, {"scope": "active"}, now=self.now)
            def invalid(*args, **kwargs):
                value = response(*args, **kwargs)
                modify(value)
                return value
            summaries.run(self.store, summary_id, invalid)
            result = summaries.detail(self.store, summary_id)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["content"], "")

    def test_batches_cover_every_todo_no_partial_success_on_later_error(self):
        for i in range(summaries.BATCH_SIZE + 1): self.manual(str(i))
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        with patch("summaries.generate_json", side_effect=response) as model:
            summaries.run(self.store, sid)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(summaries.detail(self.store, sid)["content"].count("**问题背景**"), summaries.BATCH_SIZE + 1)
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        calls = []
        def partial(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1: raise RuntimeError("fixture failed")
            return response(*args, **kwargs)
        summaries.run(self.store, sid, partial)
        self.assertEqual(summaries.detail(self.store, sid)["status"], "failed")
        self.assertEqual(summaries.detail(self.store, sid)["content"], "")

    def test_empty_range_skips_model_and_cancellation_cannot_be_overwritten(self):
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        with patch("summaries.generate_json") as model:
            summaries.run(self.store, sid)
            model.assert_not_called()
        self.assertEqual(summaries.detail(self.store, sid)["status"], "completed")
        self.manual()
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        def late(*args, **kwargs):
            summaries.cancel(self.store, sid)
            return response(*args, **kwargs)
        summaries.run(self.store, sid, late)
        self.assertEqual(summaries.detail(self.store, sid)["status"], "cancelled")
        self.assertEqual(summaries.detail(self.store, sid)["content"], "")

    def test_single_active_job_and_restart_recovery(self):
        self.manual()
        sid = summaries.create(self.store, {"scope": "active"}, now=self.now)
        with self.assertRaisesRegex(ValueError, "已有总结"):
            summaries.create(self.store, {"scope": "active"}, now=self.now)
        summaries.recover(self.store)
        self.assertEqual(summaries.detail(self.store, sid)["status"], "failed")
        self.assertNotEqual(summaries.create(self.store, {"scope": "active"}, now=self.now), sid)

    def test_schedule_persists_first_future_slot_and_consumes_failed_slot(self):
        config = summaries.save_schedule(self.store, {"enabled": True}, self.now)
        expected = stamp("2026-10-15T18:00")
        self.assertEqual(config["next_at"], expected)
        self.store.db.close()
        self.store = Store(self.tmp.name)
        self.assertFalse(summaries.schedule_state(self.store, expected - 1)["due"])
        self.assertTrue(summaries.schedule_state(self.store, expected)["due"])
        request = summaries.automatic_request(self.store, expected)
        sid = summaries.create(self.store, request, "automatic", expected)
        summaries.fail(self.store, sid, "fixture offline")
        self.assertFalse(summaries.schedule_state(self.store, expected + 5)["due"])
        self.assertEqual(summaries.schedule_state(self.store, expected)["next_at"], stamp("2026-10-16T18:00"))

    def test_weekly_interval_coalescing_and_save_without_changes(self):
        config = summaries.save_schedule(self.store, {"enabled": True, "frequency": "weekly", "weekday": 0}, self.now)
        self.assertEqual(config["next_at"], stamp("2026-10-19T18:00"))
        config = summaries.save_schedule(self.store, {"frequency": "interval", "interval_hours": 3}, self.now)
        self.assertEqual(config["next_at"], self.now + 3*3600)
        same = summaries.save_schedule(self.store, {"interval_hours": 3}, self.now + 3600)
        self.assertEqual(same["next_at"], config["next_at"])
        later = self.now + 7*86400
        sid = summaries.create(self.store, summaries.automatic_request(self.store, later), "automatic", later)
        summaries.run(self.store, sid)
        self.assertEqual(summaries.schedule_state(self.store, later)["next_at"], later + 3*3600)

    def test_off_duty_and_adjusted_workdays_and_missing_calendar(self):
        now = stamp("2026-10-10T09:00")
        summaries.save_schedule(self.store, {"enabled": True, "frequency": "interval", "interval_hours": 1, "workdays_only": True}, now-3600)
        self.assertIsNone(summaries.schedule_state(self.store, now)["next_at"])
        raw = json.loads((ROOT / "tests/fixtures/holidays-2026.json").read_text())
        self.store.put_meta("calendar_2026", normalize_calendar(raw, 2026))
        self.assertTrue(summaries.schedule_state(self.store, now)["due"])
        sunday = stamp("2026-10-11T09:00")
        self.assertFalse(summaries.schedule_state(self.store, sunday)["due"])
        finish_workday(self.store, now)
        self.assertFalse(summaries.schedule_state(self.store, now)["due"])
        self.store.save_settings({"workdays_only": False})
        self.store.put_meta("off_duty_until", 0)
        self.assertTrue(refresh_needed(self.store, now))


class SummaryRPCTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.tmp.name)
        self.marker = self.folder / "fixture-started"
        self.fixture = self.folder / "fake-codex"
        self.fixture.write_text("#!" + sys.executable + "\n" + '''import json,pathlib,sys,time
prompt=sys.stdin.read()
data=json.loads(prompt.split('<untrusted_summary_data>')[1].split('</untrusted_summary_data>')[0])
pathlib.Path(MARKER).touch()
if any(t['title']=='slow fixture' for t in data['tasks']): time.sleep(30)
items=[dict(id=t['id'],background='工作验证',problem='性能不足',results='暂无实验结果记录',conclusion='尚无可验证结论',relevance='work',relevance_reason='工作实验',evidence_indices=[0]) for t in data['tasks']]
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps({'items':items}))
'''.replace("MARKER", repr(str(self.marker))))
        self.fixture.chmod(0o700)
        self.store = Store(self.folder / "data")
        self.store.save_settings({"automatic": False, "workdays_only": False, "codex_cli": str(self.fixture)})
        self.proc = None

    def start(self):
        env = dict(os.environ, CODEX_TODO_CODEX=str(self.fixture), PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "backend/service.py"), "--data-dir", str(self.folder / "data"), "serve"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

    def request(self, method, **values):
        self.proc.stdin.write(json.dumps(dict(method=method, id=1, **values)) + "\n")
        self.proc.stdin.flush()
        self.assertTrue(select.select([self.proc.stdout], [], [], 8)[0], "RPC response timed out")
        response = json.loads(self.proc.stdout.readline())
        self.assertNotIn("error", response, response)
        return response["result"]

    def until(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate():
            if time.monotonic() > deadline: self.fail("fixture timed out")
            time.sleep(.03)

    def tearDown(self):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                pipe.close()
        self.store.db.close()
        self.tmp.cleanup()

    def test_real_rpc_worker_generates_report_and_snapshot_remains_responsive(self):
        self.store.save_manual("虚构工作")
        self.start()
        self.assertEqual(self.request("summary_preview", scope="active")["task_count"], 1)
        result = self.request("summary_generate", scope="active")
        sid = result["summary_id"]
        self.until(lambda: self.request("summary_detail", summary_id=sid)["status"] not in summaries.ACTIVE)
        self.assertEqual(self.request("summary_detail", summary_id=sid)["status"], "completed")
        self.assertEqual(len(self.request("snapshot")["summaries"]), 1)

    def test_cancel_and_finish_workday_stop_actual_child_without_closing_todo(self):
        self.store.save_manual("slow fixture")
        self.start()
        for action in ("summary_cancel", "finish_workday"):
            self.marker.unlink(missing_ok=True)
            sid = self.request("summary_generate", scope="active")["summary_id"]
            self.until(self.marker.exists)
            started = time.monotonic()
            result = self.request(action, summary_id=sid)
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(result["summaries"][0]["status"], "cancelled")
            self.assertEqual(result["tasks"][0]["status"], "open")
            self.assertEqual(self.request("summary_detail", summary_id=sid)["content"], "")

    def test_due_automatic_report_fires_once_and_uses_saved_filter(self):
        self.store.save_manual("虚构工作")
        summaries.save_schedule(self.store, {"enabled": True, "frequency": "interval", "interval_hours": 1,
                                           "work_only": True, "work_context": "虚构工作"}, time.time()-4000)
        self.start()
        snapshot = self.request("snapshot")
        self.assertEqual(len(snapshot["summaries"]), 1)
        sid = snapshot["summaries"][0]["id"]
        self.until(lambda: self.request("summary_detail", summary_id=sid)["status"] == "completed")
        for _ in range(3): self.assertEqual(len(self.request("snapshot")["summaries"]), 1)
        result = self.request("summary_detail", summary_id=sid)
        self.assertEqual(result["origin"], "automatic")
        self.assertTrue(result["work_only"])


if __name__ == '__main__':
    unittest.main()
