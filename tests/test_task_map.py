"""Task maps are optional, complete, source-bound, cancellable and read-only."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from store import Store
import taskmap


def response(prompt, schema, **kwargs):
    data = json.loads(prompt.split("<untrusted_task_map>")[1].split("</untrusted_task_map>")[0])
    return {"nodes": [{"id": ident, "topic": "搜索性能优化"} for ident in data["batch_ids"]], "edges": []}


def edge(a, b, kind="progression"):
    return {"source": a["id"], "target": b["id"], "kind": kind, "reason": "定位问题后进入验证",
            "source_field": "title", "source_quote": a["title"], "target_field": "title", "target_quote": b["title"]}


class TaskMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.ids = [self.store.save_manual("搜索问题"+str(i), "定位并验证搜索性能") for i in range(3)]

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def tasks(self):
        return [tuple(r) for r in self.store.db.execute("SELECT * FROM tasks ORDER BY id")]

    def analyse(self, generator=response, scope="active"):
        ident = taskmap.create(self.store, {"scope": scope})
        taskmap.run(self.store, ident, generator)
        return taskmap.detail(self.store, {"scope": scope})

    def test_default_map_is_available_without_model_and_does_not_change_list(self):
        before = self.tasks()
        doc = taskmap.detail(self.store, {})
        self.assertEqual({n["id"] for n in doc["nodes"]}, set(self.ids))
        self.assertFalse(doc["analysed"])
        self.assertEqual(doc["edges"], [])
        self.assertEqual([group["title"] for group in doc["groups"]], [taskmap.UNCLASSIFIED])
        self.assertEqual(before, self.tasks())

    def test_all_scope_includes_completed_and_archived_while_active_excludes_them(self):
        self.store.act("complete", self.ids[0])
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET status='conversation_archived' WHERE id=?", (self.ids[1],))
        self.assertEqual(len(taskmap.detail(self.store, {})["nodes"]), 1)
        self.assertEqual(len(taskmap.detail(self.store, {"scope": "all"})["nodes"]), 3)

    def test_model_covers_every_node_without_changing_titles_or_states(self):
        before = self.tasks()
        doc = self.analyse()
        self.assertEqual(doc["status"], "completed")
        self.assertTrue(doc["analysed"])
        self.assertEqual({n["id"] for n in doc["nodes"]}, set(self.ids))
        self.assertEqual({n["topic"] for n in doc["nodes"]}, {"搜索性能优化"})
        self.assertEqual(before, self.tasks())

    def test_progression_moves_left_to_right_and_nodes_never_overlap(self):
        def related(prompt, schema, **kwargs):
            result = response(prompt, schema)
            data = json.loads(prompt.split("<untrusted_task_map>")[1].split("</untrusted_task_map>")[0])
            a, b, c = data["context"][:3]
            result["edges"] = [edge(a, b), edge(b, c), edge(a, c, "related")]
            return result
        doc = self.analyse(related)
        nodes = {n["id"]: n for n in doc["nodes"]}
        for link in doc["edges"]:
            if link["kind"] == "progression":
                self.assertLess(nodes[link["source"]]["x"], nodes[link["target"]]["x"])
                self.assertEqual(nodes[link["source"]]["y"], nodes[link["target"]]["y"])
            for a, b in zip(link["points"], link["points"][1:]):
                self.assertTrue(a[0] == b[0] or a[1] == b[1], "Connections must be horizontal or vertical")
        for i, a in enumerate(doc["nodes"]):
            for b in doc["nodes"][i+1:]:
                self.assertTrue(abs(a["x"]-b["x"]) >= doc["node_width"] or abs(a["y"]-b["y"]) >= doc["node_height"])
        self.assertEqual(len(doc["edges"]), 3)

    def test_missing_nodes_bad_quotes_self_edges_and_cycles_are_rejected(self):
        sources = [taskmap.compact(s) for s in taskmap.sources_for(self.store, taskmap.selection({}))]
        a, b, _ = sources
        for mutation in (lambda v: v["nodes"].pop(),
                         lambda v: v["edges"][0].update(target="invented"),
                         lambda v: v["edges"][0].update(source_quote="fabricated quote"),
                         lambda v: v["edges"][0].update(target=a["id"]),
                         lambda v: v["edges"].append(edge(b, a))):
            value = {"nodes": [{"id": s["id"], "topic": "搜索优化"} for s in sources], "edges": [edge(a, b)]}
            mutation(value)
            with self.assertRaises(ValueError): taskmap.validate(value, sources, sources, [])

    def test_cross_topic_progression_still_moves_left_to_right(self):
        sources = taskmap.sources_for(self.store, taskmap.selection({}))
        a, b, c = sources
        links = [edge(a, c), edge(b, c)]
        data = {"topics": {a["id"]: "前置定位", b["id"]: "前置定位", c["id"]: "后续验证"}, "edges": links}
        doc = taskmap.layout(sources, data)
        positions = {n["id"]: n for n in doc["nodes"]}
        for link in doc["edges"]:
            self.assertLess(positions[link["source"]]["x"], positions[link["target"]]["x"])

    def test_invalid_model_output_is_corrected_and_persistent_failure_preserves_good_map(self):
        self.analyse()
        calls = []
        def correcting(prompt, schema, **kwargs):
            calls.append(prompt)
            value = response(prompt, schema)
            if len(calls) == 1: value["nodes"].pop()
            return value
        self.assertEqual(self.analyse(correcting)["status"], "completed")
        self.assertEqual(len(calls), 2)
        def invalid(*args, **kwargs): return {"nodes": [], "edges": []}
        doc = self.analyse(invalid)
        self.assertEqual(doc["status"], "failed")
        self.assertTrue(doc["analysed"])
        self.assertEqual(len(doc["nodes"]), 3)

    def test_cancellation_ignores_late_response_and_stops_retry(self):
        ident = taskmap.create(self.store, {})
        calls = []
        def late(*args, **kwargs):
            calls.append(1)
            taskmap.cancel(self.store, ident)
            return {"nodes": [], "edges": []}
        taskmap.run(self.store, ident, late)
        doc = taskmap.detail(self.store, {})
        self.assertEqual(doc["status"], "cancelled")
        self.assertFalse(doc["analysed"])
        self.assertEqual(len(calls), 1)

    def test_task_changes_are_live_and_cached_edges_to_removed_nodes_disappear(self):
        self.analyse()
        self.store.save_manual("手动固定的新标题", "新的进度", entity_id=self.ids[0])
        doc = taskmap.detail(self.store, {})
        self.assertTrue(doc["outdated"])
        self.assertIn("手动固定的新标题", {n["title"] for n in doc["nodes"]})
        self.store.act("complete", self.ids[0])
        self.assertNotIn(self.ids[0], {n["id"] for n in taskmap.detail(self.store, {})["nodes"]})

    def test_changing_quoted_evidence_hides_stale_edges_instead_of_inventing_citations(self):
        def linked(prompt, schema, **kwargs):
            data = json.loads(prompt.split("<untrusted_task_map>")[1].split("</untrusted_task_map>")[0])
            value = response(prompt, schema)
            value["edges"] = [edge(*data["context"][:2])]
            return value
        doc = self.analyse(linked)
        self.assertEqual(len(doc["edges"]), 1)
        changed = doc["edges"][0]["source"]
        self.store.save_manual("用户重新命名的整体目标", entity_id=changed)
        updated = taskmap.detail(self.store, {})
        self.assertTrue(updated["outdated"])
        self.assertEqual(updated["edges"], [])

    def test_every_task_survives_multiple_batches_and_candidates_remain_bounded(self):
        for i in range(80): self.store.save_manual("跨主机工作"+str(i), "数据集核验")
        doc = self.analyse()
        self.assertEqual(len(doc["nodes"]), 83)
        self.assertEqual(len({n["id"] for n in doc["nodes"]}), 83)
        sources = taskmap.sources_for(self.store, taskmap.selection({}))
        self.assertLessEqual(len(taskmap.candidates(sources, sources[:12])), 64)

    def test_only_one_model_job_and_restart_recovery_keeps_previous_graph(self):
        self.analyse()
        taskmap.create(self.store, {})
        with self.assertRaises(ValueError): taskmap.create(self.store, {"scope": "all"})
        taskmap.recover(self.store)
        doc = taskmap.detail(self.store, {})
        self.assertEqual(doc["status"], "failed")
        self.assertTrue(doc["analysed"])
        self.assertFalse(doc["busy"])

    def test_same_problem_across_stages_shares_a_graph_but_same_stage_different_problem_does_not(self):
        upload = self.store.save_manual("图片上传基准测试", "比较上传分片方案")
        with self.store.db:
            for ident, kind in zip(self.ids, ("continue", "wait", "review")):
                self.store.db.execute("UPDATE tasks SET kind=? WHERE id=?", (kind, ident))
            self.store.db.execute("UPDATE tasks SET kind='review' WHERE id=?", (upload,))
        def classifier(prompt, schema, **kwargs):
            if "<untrusted_topic_catalog>" in prompt:
                names = json.loads(prompt.split("<untrusted_topic_catalog>")[1].split("</untrusted_topic_catalog>")[0])
                return {"topics": [{"topic": name, "canonical": name} for name in names]}
            value = response(prompt, schema)
            for item in value["nodes"]: item["topic"] = "图片上传性能" if item["id"] == upload else "搜索性能"
            return value
        before = self.tasks()
        doc = self.analyse(classifier)
        self.assertEqual(doc["task_count"], 4)
        self.assertEqual({n["id"] for n in doc["nodes"]}, set(self.ids))
        self.assertEqual({n["kind"] for n in doc["nodes"]}, {"continue", "wait", "review"})
        other = next(t for t in doc["topics"] if t["title"] == "图片上传性能")
        switched = taskmap.detail(self.store, {"scope": "active", "topic_id": other["id"]})
        self.assertEqual({n["id"] for n in switched["nodes"]}, {upload})
        self.assertEqual(len(switched["groups"]), 1)
        self.assertEqual(self.tasks(), before)

    def test_model_cannot_name_a_problem_type_after_a_stage(self):
        sources = [taskmap.compact(s) for s in taskmap.sources_for(self.store, taskmap.selection({}))]
        self.assertTrue(all("kind" not in s and "status" not in s for s in sources))
        for name in ("等待结果", "结果校对", "进行中", "验证"):
            value = {"nodes": [{"id": s["id"], "topic": name} for s in sources], "edges": []}
            with self.assertRaisesRegex(ValueError, "阶段"):
                taskmap.validate(value, sources, sources, [])

    def test_synonymous_topics_are_consolidated_without_merging_different_problems(self):
        def model(prompt, schema, **kwargs):
            if "<untrusted_topic_catalog>" in prompt:
                names = json.loads(prompt.split("<untrusted_topic_catalog>")[1].split("</untrusted_topic_catalog>")[0])
                return {"topics": [{"topic": name, "canonical": "搜索性能" if name == "检索延迟" else name} for name in names]}
            value = response(prompt, schema)
            for item in value["nodes"]: item["topic"] = dict(zip(self.ids, ("搜索性能", "检索延迟", "图片上传")))[item["id"]]
            return value
        doc = self.analyse(model)
        self.assertEqual({t["title"] for t in doc["topics"]}, {"搜索性能", "图片上传"})
        self.assertEqual(len(doc["nodes"]), 2)
        self.assertEqual(sum(t["count"] for t in doc["topics"]), 3)

    def test_legacy_stage_cache_is_not_presented_as_problem_classification(self):
        self.analyse()
        with self.store.db:
            self.store.db.execute("UPDATE task_maps SET data=?", (json.dumps({"topics": {ident: "等待结果" for ident in self.ids}, "edges": []}),))
        doc = taskmap.detail(self.store, {})
        self.assertTrue(doc["classification_required"])
        self.assertFalse(doc["analysed"])
        self.assertEqual({t["title"] for t in doc["topics"]}, {taskmap.UNCLASSIFIED})

    def test_cross_problem_links_stay_outside_canvas_and_point_to_the_other_graph(self):
        sources = taskmap.sources_for(self.store, taskmap.selection({}))
        a, b, c = sources
        data = {"topics": {a["id"]: "搜索性能", b["id"]: "搜索性能", c["id"]: "数据质量"}, "edges": [edge(a, c)]}
        doc = taskmap.problem_document(sources, data)
        self.assertEqual(len(doc["nodes"]), 2)
        self.assertEqual(doc["edges"], [])
        self.assertEqual(doc["external_links"][0]["topic_title"], "数据质量")
        other = taskmap.problem_document(sources, data, doc["external_links"][0]["topic_id"])
        self.assertEqual(other["nodes"][0]["id"], c["id"])


if __name__ == "__main__": unittest.main()
