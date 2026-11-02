import copy
import os
import pathlib
import subprocess
import unittest
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:
    tk = None

from linux.app import CoindexApp, load_demo_snapshot
from taskmap import demo_document


class TaskMapUITests(unittest.TestCase):
    def setUp(self):
        if tk is None: self.skipTest("Tkinter is unavailable")
        try: self.root = tk.Tk()
        except tk.TclError as error: self.skipTest(str(error))
        self.root.geometry("1240x820")
        self.app = CoindexApp(self.root, demo=True, demo_data=load_demo_snapshot())
        self.page = self.app.map_page
        self.app._switch("task-map")
        self.root.update()

    def tearDown(self):
        if getattr(self, "root", None): self.app.close()

    def test_map_is_additive_and_switching_preserves_original_list(self):
        before = copy.deepcopy(self.app.snapshot["tasks"])
        self.assertTrue(self.page.winfo_manager())
        self.assertFalse(self.app.task_page.winfo_manager())
        self.assertEqual(self.page.document["task_count"], len(before))
        self.assertEqual(len({n["topic"] for n in self.page.document["nodes"]}), 1)
        if os.environ.get("COINDEX_TASK_MAP_EVIDENCE"):
            folder = pathlib.Path(os.environ["COINDEX_TASK_MAP_EVIDENCE"])
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["scrot", str(folder / "task-map-linux.png")], check=True)
        self.page.select(before[0]["id"])
        self.assertIn(before[0]["title"], self.page.text.get("1.0", "end"))
        self.assertIn(before[0]["next_action"], self.page.text.get("1.0", "end"))
        self.page.show_in_list()
        self.assertEqual(self.app.tab, "tasks")
        self.assertEqual(self.app.selected_task, before[0]["id"])
        self.assertEqual(self.app.snapshot["tasks"], before)
        self.assertFalse(self.page.winfo_manager())

    def test_zoom_search_and_polling_preserve_selection_and_view(self):
        ident = self.page.document["nodes"][0]["id"]
        self.page.select(ident)
        self.page.set_zoom(1.2)
        self.page.canvas.yview_moveto(.3)
        scroll = self.page.canvas.yview()
        self.page.refresh()
        self.assertEqual(self.page.selected_id, ident)
        self.assertEqual(self.page.zoom, 1.2)
        self.assertEqual(self.page.canvas.yview(), scroll)
        self.page.search.set("no such task")
        self.assertIn("本图 0 项", self.page.counter.get())
        self.page.search.set("")
        self.assertGreater(len(self.page.canvas.find_all()), 0)

    def test_outdated_async_response_cannot_replace_new_scope(self):
        self.app.demo = False
        calls = []
        self.app._rpc = lambda method, callback, **values: (calls.append((method, callback, values)) or "fixture")
        self.page.refresh()
        old = calls[-1][1]
        self.page.scope.set("全部（含完成、归档）")
        self.page.change_scope()
        self.assertEqual(calls[-1][2]["scope"], "all")
        current = dict(demo_document(self.app.snapshot["tasks"]), scope="all")
        calls[-1][1]({"result": current})
        old({"result": dict(current, scope="active", nodes=[])})
        self.assertEqual(self.page.document["scope"], "all")
        self.assertTrue(self.page.document["nodes"])

    def test_problem_selector_switches_independent_graphs_instead_of_stage_groups(self):
        first = self.page.document
        self.assertEqual(len({n["topic"] for n in first["nodes"]}), 1)
        self.assertGreater(len({n["kind"] for n in first["nodes"]}), 1)
        target = next(t for t in first["topics"] if t["title"] == "图片上传")
        self.page.choose_topic(target["id"])
        self.assertEqual({n["topic"] for n in self.page.document["nodes"]}, {"图片上传"})
        self.assertEqual(len({n["kind"] for n in self.page.document["nodes"]}), 2)
        self.assertEqual(self.page.document["task_count"], first["task_count"])


if __name__ == "__main__": unittest.main()
