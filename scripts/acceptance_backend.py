#!/usr/bin/env python3
"""Exercise an extracted release backend with synthetic, isolated legacy data only."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch


def require(condition, message):
    if not condition:
        raise AssertionError(message)



def linux_ui(backend, evidence, report):
    import subprocess
    import tkinter as tk
    import time
    package = backend.parent
    require((package / "linux/app.py").is_file() and (package / "demo.json").is_file(), "Installed Linux package/fixture missing")
    sys.path.insert(0, str(package))
    frontend = importlib.import_module("linux.app")
    require(Path(frontend.__file__).resolve() == (package / "linux/app.py").resolve(), "Wrong frontend imported")
    report["scope"] = "Synthetic legacy database and summary persistence plus installed Linux demo Tk widget actions; no real user data or model."
    report["frontend_sha256"] = hashlib.sha256((package / "linux/app.py").read_bytes()).hexdigest()
    evidence.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *error: errors.append(str(error))
    app = None
    def forbidden(*args, **kwargs):
        raise AssertionError("Real service forbidden")
    def snapshot(name):
        root.update()
        require(not errors, "Tk callback errors: " + repr(errors))
        require(root.winfo_viewable(), "Tk window not visible")
        lines = []
        def walk(widget):
            text = str(widget.cget("text")) if "text" in widget.keys() else ""
            lines.append(f"{widget.winfo_class()} visible={widget.winfo_viewable()} text={text}")
            for child in widget.winfo_children():
                walk(child)
        walk(root)
        (evidence / (name + ".widgets.txt")).write_text("\n".join(lines))
        image = evidence / (name + ".png")
        subprocess.run(["scrot", str(image)], check=True, timeout=15)
        raw = image.read_bytes()
        require(len(raw) > 100 and raw[:8] == b"\x89PNG\r\n\x1a\n", "Screenshot invalid")
    try:
        with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
            app = frontend.CoindexApp(root, data_dir=os.environ["CODEX_TODO_DATA_DIR"], demo=True, client_factory=forbidden)
            root.geometry("1240x820")
            root.deiconify()
            root.update()
            require(app.client is None, "Demo created service")
            rows = app.snapshot["tasks"]
            expected = {r["id"] for r in rows if r.get("status", "open") == "open" and r.get("snoozed_until", 0) <= time.time()}
            require(expected and set(app.visible_task_ids) == expected, "Initial demo tasks mismatch")
            snapshot("linux-01-demo")
            app.category_buttons["结果校对"][0].invoke()
            root.update()
            require(set(app.visible_task_ids) == {r["id"] for r in rows if r["id"] in expected and r["kind"] == "review"}, "Category UI mismatch")
            snapshot("linux-02-review")
            app.nav_tasks.invoke()
            root.update()
            require(set(app.visible_task_ids) == expected, "All-tasks navigation failed")
            host = next(r["host"] for r in rows if r["id"] in expected)
            label = next(label for label, key in app.host_values.items() if key == host)
            app.host_box.set(label)
            app.host_box.event_generate("<<ComboboxSelected>>")
            root.update()
            require(set(app.visible_task_ids) == {r["id"] for r in rows if r["id"] in expected and r["host"] == host}, "Source UI mismatch")
            snapshot("linux-03-source")
            app.host_box.set("全部来源")
            app.host_box.event_generate("<<ComboboxSelected>>")
            app.search_entry.delete(0, "end")
            app.search_entry.insert(0, "zz-coindex-no-match")
            root.update()
            require(not app.visible_task_ids and app.result_count == 0, "No-match search failed")
            snapshot("linux-04-search")
            app.search_entry.delete(0, "end")
            root.update()
            require(set(app.visible_task_ids) == expected, "Clear search failed")
            app.nav_summaries.invoke()
            root.update()
            require(app.summary_page.winfo_viewable(), "Summary navigation failed")
            require(app.summary_page.new_button.instate(["disabled"]) and app.summary_page.schedule_button.instate(["disabled"]), "Demo summary controls unexpectedly enabled")
            snapshot("linux-05-summary")
            report["checks"].append("Installed Linux Tk demo: category/source/search controls, visible summary page and disabled generation/schedule controls, PNG screenshots")
            report["linux_ui_limit"] = "Demo disables summary composer/schedule opening. No UI persistence/generation or physical mouse/keyboard acceptance is claimed; Tk widgets invoked directly."
    finally:
        if app is not None:
            app.close()
        else:
            root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--linux-ui", action="store_true", help="Exercise installed Tk UI under Xvfb; requires scrot")
    args = parser.parse_args()
    backend = args.backend.resolve(strict=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(backend))
    report = {"backend": str(backend), "passed": False, "checks": [],
              "scope": "Synthetic legacy SQLite upgrade and backend summary settings; no GUI, real user database, or real model acceptance."}
    report["sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in backend.glob("*.py")}
    try:
        with tempfile.TemporaryDirectory(prefix="coindex-acceptance-") as temp:
            root = Path(temp)
            env = {"HOME": str(root), "CODEX_HOME": str(root / "empty-codex"),
                   "CODEX_TODO_DATA_DIR": str(root / "data"), "CODEX_TODO_CODEX": "/usr/bin/false",
                   "COINDEX_DISABLE_UPDATE_CHECK": "1"}
            with patch.dict(os.environ, env), patch("subprocess.Popen", side_effect=AssertionError("Subprocess forbidden")), patch("socket.socket", side_effect=AssertionError("Network forbidden")):
                store_module = importlib.import_module("store")
                summaries = importlib.import_module("summaries")
                for module in (store_module, summaries):
                    require(Path(module.__file__).resolve().parent == backend, "Wrong backend imported")
                data = root / "data"
                data.mkdir()
                db = sqlite3.connect(data / "todos.sqlite")
                db.executescript('''
                CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE conversations(id TEXT PRIMARY KEY,host TEXT NOT NULL,thread_id TEXT NOT NULL,title TEXT NOT NULL,cwd TEXT NOT NULL,path TEXT NOT NULL,updated_at REAL NOT NULL,payload TEXT NOT NULL,fingerprint TEXT NOT NULL,analyzed_fingerprint TEXT,analyzed_at REAL,analysis_state TEXT,summary TEXT NOT NULL DEFAULT '',closed INTEGER NOT NULL DEFAULT 0,closed_at REAL);
                CREATE TABLE tasks(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,semantic_key TEXT NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,detail TEXT NOT NULL,evidence TEXT NOT NULL,next_action TEXT NOT NULL,artifact TEXT NOT NULL,priority INTEGER NOT NULL,confidence REAL NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at REAL NOT NULL,updated_at REAL NOT NULL,completed_at REAL,snoozed_until REAL NOT NULL DEFAULT 0,UNIQUE(conversation_id,semantic_key));
                CREATE TABLE nudges(action_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,conversation_id TEXT NOT NULL,status TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT NOT NULL DEFAULT '',result TEXT NOT NULL DEFAULT '{}');
                ''')
                db.execute("INSERT INTO meta VALUES('settings',?)", (json.dumps({"automatic": False, "enabled_hosts": ["mac"], "interval_seconds": 300}),))
                for ident, status, archived in (("open", "open", False), ("done", "done", False), ("archived", "open", True)):
                    path = "/fixture/archived_sessions/test.jsonl" if archived else "/fixture/sessions/test.jsonl"
                    db.execute("INSERT INTO conversations(id,host,thread_id,title,cwd,path,updated_at,payload,fingerprint,analyzed_fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?)", (ident,"lab-old",ident,"Synthetic conversation","/fixture",path,100,"{}","v1","v1"))
                    db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ident,ident,"goal-"+ident,"review","Synthetic "+ident,"detail","evidence","next","",2,0.9,status,10,100,100 if status == "done" else None,200 if ident == "open" else 0))
                db.execute("INSERT INTO nudges VALUES('n','open','open','delivered',10,20,'','{}')")
                before = {r[0]: r for r in db.execute("SELECT * FROM tasks")}
                db.commit()
                db.close()
                store = store_module.Store(data)
                try:
                    rows = {r["id"]: dict(r) for r in store.db.execute("SELECT * FROM tasks")}
                    require(set(rows) == set(before), "Migration changed task identities")
                    old_columns = ["id","conversation_id","semantic_key","kind","title","detail","evidence","next_action","artifact","priority","confidence","status","created_at","updated_at","completed_at","snoozed_until"]
                    for ident, row in rows.items():
                        for key, value in zip(old_columns, before[ident]):
                            expected = "conversation_archived" if ident == "archived" and key == "status" else value
                            require(row[key] == expected, "Legacy field changed: " + ident + ":" + key)
                        require(row["base_key"] == "goal-" + ident, "base_key backfill failed")
                    require(rows["done"]["observed_at"] == 10 and rows["open"]["observed_at"] == 100, "Observation backfill failed")
                    require(store.db.execute("SELECT attention FROM nudges WHERE action_id='n'").fetchone()[0] == "", "Nudge migration failed")
                    settings = store.settings()
                    require(settings["enabled_hosts"] == ["mac"] and settings["automatic"] is False and settings["interval_seconds"] == 300, "Settings changed during upgrade")
                    require("lab-old" in [r["id"] for r in settings["remote_hosts"]], "Legacy host not migrated")
                    report["checks"].append("Legacy schema upgraded; IDs, completion, snooze, fields, nudge and enabled sources preserved; archived status migrated intentionally")
                    saved_rows = [tuple(r) for r in store.db.execute("SELECT * FROM tasks ORDER BY id")]
                    activity = store.db.execute("SELECT COUNT(*) FROM task_activity").fetchone()[0]
                    summaries.init_schema(store)
                    summaries.init_schema(store)
                    require(store.db.execute("SELECT COUNT(*) FROM task_activity").fetchone()[0] == activity, "Activity duplicated")
                    values = {"enabled": True,"frequency": "interval","interval_hours": 3,"scope": "all","work_only": True,"work_context": "synthetic fixture only","workdays_only": False}
                    now = 1792051200
                    with patch.object(summaries, "generate_json", side_effect=AssertionError("Model forbidden")):
                        summaries.save_schedule(store, values, now)
                        next_at = store.meta("summary_next_at")
                        require(next_at == now + 10800, "Wrong interval slot")
                        store.db.close()
                        store = store_module.Store(data)
                        for key, value in values.items():
                            require(summaries.schedule_settings(store)[key] == value, "Setting not persisted: " + key)
                        require(store.meta("summary_next_at") == next_at, "Next slot not persisted")
                        summaries.save_schedule(store, values, now + 60)
                        require(store.meta("summary_next_at") == next_at, "Unchanged settings moved slot")
                        prior = summaries.schedule_settings(store)
                        for invalid in ({"frequency": "bad"}, {"interval_hours": 0}, {"days": -1}):
                            try:
                                summaries.save_schedule(store, invalid, now)
                            except ValueError:
                                pass
                            else:
                                raise AssertionError("Invalid setting accepted")
                            require(summaries.schedule_settings(store) == prior, "Invalid settings persisted")
                        require([tuple(r) for r in store.db.execute("SELECT * FROM tasks ORDER BY id")] == saved_rows, "Restart/settings changed tasks")
                        require(store.db.execute("SELECT COUNT(*) FROM task_activity").fetchone()[0] == activity, "Restart duplicated activity")
                    report["checks"].append("Summary config and next slot survive reopen; unchanged save stable; invalid inputs rejected; migration/backfill idempotent")
                finally:
                    store.db.close()
            if args.linux_ui:
                with patch.dict(os.environ, env):
                    linux_ui(backend, args.evidence.parent, report)
            report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
