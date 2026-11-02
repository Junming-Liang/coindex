"""Exercise real map worker isolation and cancellation with a synthetic model."""
import os
import pathlib
import sys
import unittest

import test_summaries as fixtures


class TaskMapRPCTests(unittest.TestCase):
    start = fixtures.SummaryRPCTests.start
    request = fixtures.SummaryRPCTests.request
    until = fixtures.SummaryRPCTests.until
    tearDown = fixtures.SummaryRPCTests.tearDown

    def setUp(self):
        fixtures.SummaryRPCTests.setUp(self)
        self.fixture.write_text("#!"+sys.executable+"\n"+'''import json,os,pathlib,sys,time
prompt=sys.stdin.read()
data=json.loads(prompt.split('<untrusted_task_map>')[1].split('</untrusted_task_map>')[0])
pathlib.Path(MARKER).write_text(str(os.getpid()))
if any(t['title']=='slow map' for t in data['context']): time.sleep(30)
items=[{'id':ident,'topic':'示例问题'} for ident in data['batch_ids']]
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps({'nodes':items,'edges':[]}))
'''.replace("MARKER", repr(str(self.marker))))

    def test_worker_keeps_snapshot_responsive_and_never_changes_tasks(self):
        ident = self.store.save_manual("工作验证", "核对指标")
        before = tuple(self.store.db.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone())
        self.start()
        result = self.request("task_map_analyze", scope="active")
        self.assertTrue(result["job_id"])
        self.assertEqual(len(self.request("snapshot")["tasks"]), 1)
        self.until(lambda: self.request("task_map_detail", scope="active")["status"] == "completed")
        result = self.request("task_map_detail", scope="active")
        self.assertTrue(result["analysed"])
        self.assertEqual(result["nodes"][0]["topic"], "示例问题")
        self.assertEqual(before, tuple(self.store.db.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone()))

    def test_cancel_terminates_owned_model_and_keeps_todo_open(self):
        ident = self.store.save_manual("slow map", "等待中止")
        self.start()
        result = self.request("task_map_analyze", scope="active")
        self.until(lambda: self.marker.is_file())
        pid = int(self.marker.read_text())
        cancelled = self.request("task_map_cancel", scope="active", job_id=result["job_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        def stopped():
            try: os.kill(pid, 0)
            except ProcessLookupError: return True
            return False
        self.until(stopped)
        self.assertEqual(self.store.db.execute("SELECT status FROM tasks WHERE id=?", (ident,)).fetchone()[0], "open")


if __name__ == "__main__": unittest.main()
