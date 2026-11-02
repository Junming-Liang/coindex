import json
import hashlib
import os
import pathlib
import sqlite3
import time
import uuid

from analyzer import COPY_VERSION, TASK_POLICY_VERSION
from connections import normalize_settings, normalize_remote
from platform_paths import local_host_name

DEFAULT_SETTINGS = {"automatic": True, "interval_seconds": 1800, "idle_minutes": 10, "batch_size": 6,
                    "history_days": 0, "enabled_hosts": ["mac"], "source_limit": 120,
                    "workdays_only": True, "work_hours_enabled": False,
                    "work_start_minutes": 540, "work_end_minutes": 1080,
                    "codex_home": "", "codex_cli": "", "codex_app": "", "remote_hosts": [],
                    "analysis_model": "gpt-6-luna", "analysis_effort": "max", "connection_setup_complete": False}


class Store:
    def __init__(self, folder):
        self.folder = pathlib.Path(folder).expanduser()
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        self.path = self.folder / "todos.sqlite"
        self.db = sqlite3.connect(str(self.path), timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        os.chmod(self.path, 0o600)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files(host TEXT, path TEXT, signature TEXT, PRIMARY KEY(host,path));
        CREATE TABLE IF NOT EXISTS conversations(
          id TEXT PRIMARY KEY, host TEXT NOT NULL, thread_id TEXT NOT NULL, title TEXT NOT NULL,
          cwd TEXT NOT NULL, path TEXT NOT NULL, updated_at REAL NOT NULL, payload TEXT NOT NULL,
          fingerprint TEXT NOT NULL, analyzed_fingerprint TEXT, analyzed_at REAL, analysis_state TEXT,
          summary TEXT NOT NULL DEFAULT '', closed INTEGER NOT NULL DEFAULT 0, closed_at REAL);
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, semantic_key TEXT NOT NULL,
          kind TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, evidence TEXT NOT NULL,
          next_action TEXT NOT NULL, artifact TEXT NOT NULL, priority INTEGER NOT NULL,
          confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL,
          updated_at REAL NOT NULL, completed_at REAL, snoozed_until REAL NOT NULL DEFAULT 0,
          UNIQUE(conversation_id,semantic_key));
        CREATE TABLE IF NOT EXISTS hosts(id TEXT PRIMARY KEY, status TEXT, detail TEXT, checked_at REAL,
          total_files INTEGER DEFAULT 0, remaining_files INTEGER DEFAULT 0, root TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS tasks_conversation ON tasks(conversation_id);
        CREATE TABLE IF NOT EXISTS nudges(
          action_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
          status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          error TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '{}', attention TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS nudges_conversation ON nudges(conversation_id,created_at);
        """)
        conversation_columns = {r[1] for r in self.db.execute("PRAGMA table_info(conversations)")}
        if "attention" not in {r[1] for r in self.db.execute("PRAGMA table_info(nudges)")}:
            self.db.execute("ALTER TABLE nudges ADD COLUMN attention TEXT NOT NULL DEFAULT ''")
        if "analyzed_phase" not in conversation_columns:
            self.db.execute("ALTER TABLE conversations ADD COLUMN analyzed_phase TEXT")
        if "archived" not in conversation_columns:
            self.db.execute("ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            self.db.execute("UPDATE conversations SET archived=1 WHERE path LIKE '%/archived_sessions/%'")
            self.db.execute("UPDATE tasks SET status='conversation_archived' WHERE status='open' AND conversation_id IN (SELECT id FROM conversations WHERE archived=1)")
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}
        for name, declaration in (("progress", "TEXT NOT NULL DEFAULT ''"),
                                  ("copy_version", "INTEGER NOT NULL DEFAULT 0"),
                                  ("base_key", "TEXT NOT NULL DEFAULT ''"),
                                  ("work_at", "REAL NOT NULL DEFAULT 0"),
                                  ("work_token", "TEXT NOT NULL DEFAULT ''"),
                                  ("observed_at", "REAL NOT NULL DEFAULT 0"),
                                  ("goal_key", "TEXT NOT NULL DEFAULT ''"),
                                  ("merged_into", "TEXT NOT NULL DEFAULT ''"),
                                  ("title_override", "TEXT NOT NULL DEFAULT ''"),
                                  ("title_edited_at", "REAL NOT NULL DEFAULT 0")):
            if name not in columns:
                self.db.execute("ALTER TABLE tasks ADD COLUMN " + name + " " + declaration)
        self.db.execute("UPDATE tasks SET base_key=semantic_key WHERE base_key=''")
        self.db.execute("UPDATE tasks SET goal_key=base_key WHERE goal_key='' AND kind<>'manual'")
        if "observed_at" not in columns:
            # Completion overwrote updated_at in legacy rows. Use their original
            # generation boundary rather than incorrectly acknowledging unseen work.
            # Open rows still have their last semantic update boundary.
            self.db.execute("""UPDATE tasks SET observed_at=CASE
                WHEN status IN ('done','dismissed') THEN created_at
                ELSE updated_at END""")
            self.db.execute("""UPDATE conversations SET analyzed_fingerprint=NULL WHERE closed=0 AND EXISTS(
                SELECT 1 FROM tasks WHERE tasks.conversation_id=conversations.id AND tasks.status IN ('done','dismissed')
                AND conversations.updated_at>tasks.observed_at)""")
        if "base_key" not in columns:
            # Revisit work that arrived after a legacy completion and may have been suppressed.
            self.db.execute("""UPDATE conversations SET analyzed_fingerprint=NULL WHERE closed=0 AND EXISTS(
                SELECT 1 FROM tasks WHERE tasks.conversation_id=conversations.id AND tasks.status IN ('done','dismissed')
                AND tasks.completed_at IS NOT NULL AND conversations.updated_at>tasks.completed_at)""")
        saved = self.meta("settings", {})
        if "remote_hosts" not in saved:
            # Migrate from the user's own database, never a developer machine inventory.
            legacy = {r[0] for r in self.db.execute("SELECT id FROM hosts UNION SELECT host FROM conversations")}
            legacy.update(saved.get("enabled_hosts", []))
            remotes = []
            for host in sorted(legacy - {"mac", "manual"}):
                try:
                    remotes.append(normalize_remote({"id": host}))
                except ValueError:
                    continue
            saved["remote_hosts"] = remotes
            saved.setdefault("enabled_hosts", ["mac"] + [r["id"] for r in remotes])
            saved.setdefault("connection_setup_complete", bool(legacy))
            self.db.execute("INSERT INTO meta VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(saved),))
        for host in ["mac"] + [r["id"] for r in saved["remote_hosts"]]:
            self.db.execute("INSERT OR IGNORE INTO hosts(id,status,detail,checked_at) VALUES(?,'unknown','尚未同步',0)", (host,))
        if self.meta("task_policy_version", 0) != TASK_POLICY_VERSION:
            # Reclassify live legacy goals once; completed/archived history stays idle.
            self.db.execute("""UPDATE conversations SET analyzed_fingerprint=NULL WHERE closed=0 AND archived=0
                AND EXISTS(SELECT 1 FROM tasks WHERE conversation_id=conversations.id AND status='open')""")
            self.db.execute("INSERT INTO meta VALUES('task_policy_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(TASK_POLICY_VERSION),))
        self.db.commit()
        from summaries import init_schema
        init_schema(self)
        from taskmap import init_schema as init_task_map
        init_task_map(self)

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put_meta(self, key, value):
        self.db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def settings(self):
        return json.loads(json.dumps(dict(DEFAULT_SETTINGS, **self.meta("settings", {}))))

    def save_settings(self, values):
        previous = self.settings()
        settings = self.settings()
        for key in DEFAULT_SETTINGS:
            if key in values:
                settings[key] = values[key]
        settings["automatic"] = bool(settings["automatic"])
        settings["workdays_only"] = bool(settings["workdays_only"])
        settings["work_hours_enabled"] = bool(settings["work_hours_enabled"])
        settings["work_start_minutes"] = min(max(int(settings["work_start_minutes"]), 0), 1439)
        settings["work_end_minutes"] = min(max(int(settings["work_end_minutes"]), 0), 1439)
        if settings["work_hours_enabled"] and settings["work_start_minutes"] == settings["work_end_minutes"]:
            raise ValueError("开始和结束时间不能相同；全天检测请关闭限定时段")
        settings["interval_seconds"] = min(max(int(settings["interval_seconds"]), 30), 3600)
        settings["idle_minutes"] = min(max(int(settings["idle_minutes"]), 1), 1440)
        settings["batch_size"] = min(max(int(settings["batch_size"]), 1), 8)
        settings["source_limit"] = min(max(int(settings["source_limit"]), 20), 300)
        settings["history_days"] = max(0, int(settings["history_days"]))
        settings["connection_setup_complete"] = bool(settings["connection_setup_complete"])
        normalize_settings(settings)
        # Clear only changed collection cursors; keep every existing conversation/task.
        old_profiles = {r["id"]: r for r in previous["remote_hosts"]}
        changed = []
        if previous["codex_home"] != settings["codex_home"]:
            changed.append("mac")
        for remote in settings["remote_hosts"]:
            old = old_profiles.get(remote["id"], {})
            if any(old.get(k) != remote.get(k) for k in ("hostname", "user", "port", "identity_file", "codex_home", "python")):
                changed.append(remote["id"])
        with self.db:
            for host in ["mac"] + [r["id"] for r in settings["remote_hosts"]]:
                self.db.execute("INSERT OR IGNORE INTO hosts(id,status,detail,checked_at) VALUES(?,'unknown','尚未同步',0)", (host,))
            for host in changed:
                self.db.execute("DELETE FROM files WHERE host=?", (host,))
                self.db.execute("UPDATE hosts SET status='unknown',detail='连接设置已变更，等待同步',checked_at=0 WHERE id=?", (host,))
            self.db.execute("INSERT INTO meta VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(settings, ensure_ascii=False),))

    def known(self, host):
        return {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT path,signature FROM files WHERE host=?", (host,))}

    def ingest(self, result):
        host = result["host"]
        now = time.time()
        with self.db:
            for path, signature in result["files"].items():
                self.db.execute("INSERT INTO files VALUES(?,?,?) ON CONFLICT(host,path) DO UPDATE SET signature=excluded.signature", (host, path, json.dumps(signature)))
            for conv in result["conversations"]:
                self.db.execute("""INSERT INTO conversations(id,host,thread_id,title,cwd,path,updated_at,payload,fingerprint)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,cwd=excluded.cwd,path=excluded.path,
                updated_at=excluded.updated_at,payload=excluded.payload,fingerprint=excluded.fingerprint
                WHERE excluded.updated_at>=conversations.updated_at""",
                (conv["id"], host, conv["thread_id"], conv["title"], conv["cwd"], conv["path"], conv["updated_at"], json.dumps(conv, ensure_ascii=False), conv["fingerprint"]))
            for thread_id, archived in result.get("archive_states", {}).items():
                if type(archived) is not bool:
                    continue
                cid = host + ":" + thread_id
                previous = self.db.execute("SELECT archived,closed FROM conversations WHERE id=?", (cid,)).fetchone()
                if not previous:
                    continue
                self.db.execute("UPDATE conversations SET archived=? WHERE id=?", (int(archived), cid))
                if archived:
                    self.db.execute("UPDATE tasks SET status='conversation_archived' WHERE conversation_id=? AND status='open'", (cid,))
                elif previous["archived"] and not previous["closed"]:
                    self.db.execute("UPDATE tasks SET status='open' WHERE conversation_id=? AND status='conversation_archived'", (cid,))
                    self.db.execute("UPDATE conversations SET analyzed_fingerprint=NULL WHERE id=?", (cid,))
            errors = result.get("read_errors", [])
            detail = "已读取 %d 个对话 · %d 个记录文件" % (len(result["conversations"]), result["total_files"])
            if errors:
                detail += " · %d 个文件未读成功" % len(errors)
            self.db.execute("UPDATE hosts SET status=?,detail=?,checked_at=?,total_files=?,remaining_files=?,root=? WHERE id=?",
                            ("partial" if errors else "online", detail, now, result["total_files"], result["remaining_files"], result["root"], host))

    def host_error(self, host, error):
        with self.db:
            self.db.execute("UPDATE hosts SET status='offline',detail=?,checked_at=? WHERE id=?", (str(error)[:500], time.time(), host))

    def execution_state(self, conv, now=None):
        if not conv["active"]:
            return "stopped"
        age = (time.time() if now is None else now) - conv["updated_at"]
        return "running" if age < self.settings()["idle_minutes"] * 60 else "idle"

    def eligible(self):
        settings = self.settings()
        enabled = set(settings["enabled_hosts"])
        now = time.time()
        rows = self.db.execute("""SELECT * FROM conversations WHERE closed=0 AND archived=0 AND
            (analyzed_fingerprint IS NULL OR analyzed_fingerprint<>fingerprint OR analyzed_phase='running')
            ORDER BY updated_at DESC""").fetchall()
        result = []
        for row in rows:
            conv = json.loads(row["payload"])
            if row["host"] not in enabled:
                continue
            if settings["history_days"] and now - conv["updated_at"] > settings["history_days"] * 86400:
                continue
            phase = self.execution_state(conv, now)
            if row["analyzed_fingerprint"] == row["fingerprint"]:
                # An unfinished run can become idle without another message.
                # Revisit that transition once, only while its running task is open.
                if phase != "idle" or row["analyzed_phase"] != "running":
                    continue
                if not self.db.execute("SELECT 1 FROM tasks WHERE conversation_id=? AND kind='running' AND status='open'", (row["id"],)).fetchone():
                    continue
            conv["execution_state"] = phase
            result.append(conv)
        return result

    def existing(self, ids):
        result = {}
        for cid in ids:
            result[cid] = [{"id": r["id"], "key": r["goal_key"] or r["base_key"], "goal_key": r["goal_key"], "created_at": r["created_at"],
                            "kind": r["kind"], "title": r["title"], "title_is_manual": bool(r["title_override"]), "detail": r["detail"], "copy_version": r["copy_version"], "next_action": r["next_action"], "status": r["status"], "artifact": r["artifact"],
                            "completed_at": r["completed_at"], "work_at": r["work_at"], "observed_at": r["observed_at"],
                            "progress": r["progress"], "evidence": r["evidence"]}
                           for r in self.db.execute("SELECT * FROM tasks WHERE conversation_id=? AND status<>'merged' ORDER BY created_at", (cid,))]
        return result

    def reconcile(self, entries, conversations):
        inputs = {c["id"]: c for c in conversations}
        now = time.time()
        with self.db:
            for entry in entries:
                cid = entry["id"]
                row = self.db.execute("SELECT closed,archived,fingerprint FROM conversations WHERE id=?", (cid,)).fetchone()
                if not row or row["closed"] or row["archived"] or row["fingerprint"] != inputs[cid]["fingerprint"]:
                    continue
                self.db.execute("UPDATE conversations SET analyzed_fingerprint=?,analyzed_at=?,analyzed_phase=?,analysis_state=?,summary=? WHERE id=?",
                                (inputs[cid]["fingerprint"], now, inputs[cid].get("execution_state") or self.execution_state(inputs[cid], now), entry["state"], entry["summary"][:600], cid))
                evidence_text = "\n".join(m["text"] for m in inputs[cid]["messages"])
                observed_at = max((m["at"] for m in inputs[cid]["messages"]), default=0)
                retained = set()
                for task in entry["tasks"]:
                    # A fabricated quote cannot be used as supporting evidence.
                    quote = task["evidence"].strip().strip('“”"')
                    if quote not in evidence_text:
                        continue
                    work_index = task.get("work_index", 0)
                    work = inputs[cid]["messages"][work_index]
                    work_at = task.get("_work_at", work["at"])
                    work_token = task.get("_work_token") or hashlib.sha256(json.dumps([work["at"], work["role"], work["text"]], ensure_ascii=False).encode()).hexdigest()[:16]
                    evidence_at = task.get("_evidence_at", inputs[cid]["messages"][task.get("evidence_index", work_index)]["at"])
                    related_ids = set(task.get("related_task_ids", []))
                    candidates = self.db.execute("SELECT * FROM tasks WHERE conversation_id=? AND status<>'merged' ORDER BY created_at,id", (cid,)).fetchall()
                    matches = [r for r in candidates if r["id"] in related_ids or (r["goal_key"] or r["base_key"]) == task["key"] or r["base_key"] == task["key"]]
                    # Preserve the legacy guard against rewording already-acknowledged evidence.
                    if not matches:
                        matches = [r for r in candidates if r["status"] in ("done","dismissed","resolved") and r["kind"] == task["kind"]
                                   and max(work_at,evidence_at) <= r["observed_at"]
                                   and ((task["artifact"] and r["artifact"] == task["artifact"]) or r["evidence"] == quote)]
                    opens = [r for r in matches if r["status"] == "open"]
                    canonical = (opens or matches or [None])[0]
                    goal_key = (canonical["goal_key"] or canonical["base_key"]) if canonical else task["key"]
                    # Fold all live siblings of the matched goal, including a concurrent reopen.
                    opens = [r for r in candidates if r["status"] == "open" and (r in opens or r["goal_key"] == goal_key)]
                    # Goal wording stays stable while phases, evidence and artifacts
                    # advance. A new wording policy can refresh legacy titles once.
                    identities = [r for r in (opens or matches) if r["copy_version"] >= COPY_VERSION]
                    identity = min(identities, key=lambda r: (r["created_at"],r["id"])) if identities else None
                    overrides = [r for r in (opens or matches) if r["title_override"]]
                    override = max(overrides, key=lambda r: (r["title_edited_at"],r["id"])) if overrides else None
                    title_override = override["title_override"] if override else ''
                    title_edited_at = override["title_edited_at"] if override else 0
                    title = title_override or (identity["title"] if identity else task["title"][:30])
                    detail = identity["detail"] if identity else task["detail"][:60]
                    values = (task["kind"], title, detail, task.get("progress", "")[:54], quote[:1000],
                              task["next_action"][:54], task["artifact"][:1000], task["priority"], task["confidence"], now, COPY_VERSION)
                    if opens:
                        canonical = opens[0]
                        task_id = canonical["id"]
                        self.db.execute("""UPDATE tasks SET kind=?,title=?,detail=?,progress=?,evidence=?,next_action=?,artifact=?,priority=?,confidence=?,updated_at=?,copy_version=?,
                            observed_at=MAX(observed_at,?),goal_key=?,snoozed_until=?,title_override=?,title_edited_at=? WHERE id=? AND status='open'""",
                            values + (observed_at, goal_key, max(r["snoozed_until"] for r in opens), title_override, title_edited_at, task_id))
                        for duplicate in opens[1:]:
                            self.db.execute("UPDATE tasks SET status='merged',merged_into=? WHERE id=? AND status='open'", (task_id, duplicate["id"]))
                            self.db.execute("UPDATE nudges SET task_id=? WHERE task_id=?", (task_id, duplicate["id"]))
                    else:
                        boundaries = [r["observed_at"] for r in matches if r["status"] in ("done","dismissed","resolved")]
                        if boundaries and max(work_at,evidence_at) <= max(boundaries):
                            continue
                        # Every post-completion occurrence gets its own identity, even
                        # when phase, artifact and original work anchor are unchanged.
                        occurrence = hashlib.sha256(json.dumps([work_token,evidence_at,quote,observed_at],ensure_ascii=False).encode()).hexdigest()[:16]
                        key = goal_key
                        if self.db.execute("SELECT 1 FROM tasks WHERE conversation_id=? AND semantic_key=?", (cid,key)).fetchone():
                            key += "@" + occurrence
                        task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, cid + ":" + key))
                        self.db.execute("""INSERT INTO tasks(id,conversation_id,semantic_key,base_key,goal_key,work_at,work_token,kind,title,detail,progress,evidence,next_action,artifact,priority,confidence,updated_at,copy_version,created_at,observed_at,title_override,title_edited_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (task_id,cid,key,goal_key,goal_key,work_at,work_token) + values + (now,observed_at,title_override,title_edited_at))
                    retained.add(task_id)
                    for previous in matches:
                        self.db.execute("UPDATE tasks SET goal_key=? WHERE id=?", (goal_key,previous["id"]))
                # Completion of an intermediate step must not retire the same live goal.
                for key in entry.get("resolved_keys", []):
                    for old in self.db.execute("SELECT id FROM tasks WHERE conversation_id=? AND (goal_key=? OR base_key=?) AND status='open'", (cid,key,key)).fetchall():
                        if old["id"] not in retained:
                            self.db.execute("UPDATE tasks SET status='resolved',completed_at=?,updated_at=? WHERE id=?", (now,now,old["id"]))

    def copy_pending(self):
        rows = self.db.execute("""SELECT tasks.*,conversations.payload FROM tasks JOIN conversations
            ON tasks.conversation_id=conversations.id WHERE tasks.status='open' AND conversations.closed=0 AND conversations.archived=0
            AND tasks.copy_version<? ORDER BY tasks.priority,tasks.updated_at DESC""", (COPY_VERSION,)).fetchall()
        enabled = set(self.settings()["enabled_hosts"])
        result = [dict(dict(r), conversation=json.loads(r["payload"])) for r in rows]
        return [item for item in result if item["conversation"]["host"] in enabled]

    def apply_copy(self, entries, originals):
        inputs = {t["id"]: t for t in originals}
        updated = 0
        with self.db:
            for item in entries:
                source = inputs[item["id"]]
                cursor = self.db.execute("""UPDATE tasks SET title=CASE WHEN title_override<>'' THEN title_override ELSE ? END,detail=?,progress=?,next_action=?,copy_version=?
                    WHERE id=? AND status='open' AND updated_at=? AND copy_version=? AND EXISTS(
                    SELECT 1 FROM conversations WHERE conversations.id=tasks.conversation_id AND closed=0 AND archived=0 AND fingerprint=?)""",
                    (item["title"], item["detail"], item["progress"], item["next_action"], COPY_VERSION,
                     item["id"], source["updated_at"], source["copy_version"], source["conversation"]["fingerprint"]))
                updated += cursor.rowcount
        return updated

    def rename_task(self, entity_id, title):
        if not isinstance(title, str):
            raise ValueError("请填写 1–100 字的单行标题")
        title = title.strip()
        if not title or len(title) > 100 or '\n' in title or '\r' in title:
            raise ValueError("请填写 1–100 字的单行标题")
        # Serialize with background reconciliation so editing a just-merged card
        # locks the surviving task rather than an obsolete sibling.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            entity_id = self.canonical_task_id(entity_id)
            row = self.db.execute("SELECT kind FROM tasks WHERE id=?", (entity_id,)).fetchone()
            if not row:
                raise ValueError("待办不存在，请刷新列表后重试")
            now = time.time()
            self.db.execute("UPDATE tasks SET title=?,title_override=?,title_edited_at=?,updated_at=? WHERE id=?",
                            (title, title if row['kind'] != 'manual' else '', now if row['kind'] != 'manual' else 0, now, entity_id))
            self.db.commit()
            return entity_id
        except Exception:
            self.db.rollback()
            raise

    def act(self, action, entity_id, value=None):
        now = time.time()
        with self.db:
            if action in ("complete", "dismiss", "reopen", "snooze"):
                entity_id = self.canonical_task_id(entity_id)
                if action == "reopen":
                    old = self.db.execute("SELECT * FROM tasks WHERE id=?", (entity_id,)).fetchone()
                    if old and old["kind"] != "manual":
                        conv = self.db.execute("SELECT archived,closed FROM conversations WHERE id=?", (old["conversation_id"],)).fetchone()
                        if conv and (conv["archived"] or conv["closed"]):
                            raise ValueError("对话已归档或结束，不能恢复活跃待办")
                        active = self.db.execute("SELECT id FROM tasks WHERE conversation_id=? AND goal_key=? AND status='open' AND id<>? ORDER BY created_at LIMIT 1", (old["conversation_id"],old["goal_key"],entity_id)).fetchone()
                        if active:
                            return  # The goal is already live; preserve its completed history.
                if action == "snooze":
                    self.db.execute("UPDATE tasks SET snoozed_until=?,updated_at=? WHERE id=?", (now + max(0, min(int(value or 60), 10080)) * 60, now, entity_id))
                else:
                    status = {"complete": "done", "dismiss": "dismissed", "reopen": "open"}[action]
                    self.db.execute("UPDATE tasks SET status=?,completed_at=?,snoozed_until=0,updated_at=? WHERE id=?", (status, None if status == "open" else now, now, entity_id))
            elif action in ("close_conversation", "reopen_conversation"):
                closed = action == "close_conversation"
                self.db.execute("UPDATE conversations SET closed=?,closed_at=?,analyzed_fingerprint=NULL WHERE id=?", (int(closed), now if closed else None, entity_id))
                if closed:
                    self.db.execute("UPDATE tasks SET status='conversation_closed',completed_at=?,updated_at=? WHERE conversation_id=? AND status IN ('open','conversation_archived')", (now, now, entity_id))
                else:
                    archived = self.db.execute("SELECT archived FROM conversations WHERE id=?", (entity_id,)).fetchone()
                    self.db.execute("UPDATE tasks SET status=?,completed_at=NULL,updated_at=? WHERE conversation_id=? AND status='conversation_closed'", ('conversation_archived' if archived and archived[0] else 'open',now, entity_id))
            else:
                raise ValueError("未知操作")

    def save_manual(self, title, detail="", priority=2, entity_id=None):
        title, detail = str(title).strip(), str(detail).strip()
        if not title or len(title)>100 or len(detail)>4000 or priority not in (1,2,3):
            raise ValueError("请填写 1–100 字标题；备注最多 4000 字")
        now = time.time()
        with self.db:
            if entity_id:
                row = self.db.execute("SELECT kind FROM tasks WHERE id=?", (entity_id,)).fetchone()
                if not row or row["kind"] != "manual":
                    raise ValueError("只能编辑手动添加的待办")
                self.db.execute("UPDATE tasks SET title=?,detail=?,priority=?,updated_at=? WHERE id=?", (title,detail,priority,now,entity_id))
            else:
                entity_id = str(uuid.uuid4())
                self.db.execute("""INSERT INTO tasks(id,conversation_id,semantic_key,base_key,kind,title,detail,evidence,next_action,artifact,priority,confidence,created_at,updated_at,copy_version)
                    VALUES(?,'',?,?,'manual',?,?,'','','',?,1,?,?,?)""", (entity_id,entity_id,entity_id,title,detail,priority,now,now,COPY_VERSION))
        return entity_id

    def canonical_task_id(self, task_id):
        seen = set()
        while task_id not in seen:
            seen.add(task_id)
            row = self.db.execute("SELECT merged_into FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or not row[0]:
                return task_id
            task_id = row[0]
        raise ValueError("待办关联异常，请重新更新")

    def nudge_target(self, task_id):
        task_id = self.canonical_task_id(task_id)
        row = self.db.execute("""SELECT tasks.*,conversations.host,conversations.thread_id,
            conversations.closed,conversations.archived FROM tasks JOIN conversations ON tasks.conversation_id=conversations.id
            WHERE tasks.id=?""", (task_id,)).fetchone()
        if not row or row["kind"] == "manual":
            raise ValueError("该待办没有关联 Codex 对话")
        if row["archived"]:
            raise ValueError("对话已归档，不再跟踪或催办")
        if row["status"] != "open" or row["closed"]:
            raise ValueError("该任务已结束，请恢复待办后再催办")
        try:
            valid = str(uuid.UUID(row["thread_id"])) == row["thread_id"]
        except (ValueError, TypeError):
            valid = False
        if row["host"] not in ["mac"] + [r["id"] for r in self.settings()["remote_hosts"]] or not valid:
            raise ValueError("待办缺少有效的原对话来源")
        return dict(row)

    def nudge(self, action_id):
        row = self.db.execute("SELECT * FROM nudges WHERE action_id=?", (action_id,)).fetchone()
        return dict(dict(row), result=json.loads(row["result"])) if row else None

    def queue_nudge(self, task_id, action_id, retry_unknown=False):
        task_id = self.canonical_task_id(task_id)
        if not isinstance(action_id, str) or str(uuid.UUID(action_id)) != action_id:
            raise ValueError("催办请求编号无效")
        now = time.time()
        # Serialize double clicks across cards and processes, before any network write.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            target = self.nudge_target(task_id)
            prior = self.nudge(action_id)
            if prior:
                if prior["task_id"] != task_id:
                    raise ValueError("催办请求编号已用于另一条待办")
                self.db.commit()
                return prior, False
            rows = self.db.execute("SELECT * FROM nudges WHERE conversation_id=? ORDER BY created_at DESC", (target["conversation_id"],)).fetchall()
            pending = next((r for r in rows if r["status"] in ("queued", "sending")), None)
            if pending:
                self.db.commit()
                return self.nudge(pending["action_id"]), False
            unknown = [r for r in rows if r["status"] == "unknown"]
            if unknown and not retry_unknown:
                raise ValueError("上次催办送达情况未确认，请先核对原对话；确认未送达后可重试")
            recent = next((r for r in rows if r["status"] == "sent" and now-r["updated_at"] < 30), None)
            if recent:
                self.db.commit()
                return self.nudge(recent["action_id"]), False
            if unknown:
                self.db.execute("UPDATE nudges SET status='checked',updated_at=? WHERE conversation_id=? AND status='unknown'", (now, target["conversation_id"]))
            self.db.execute("INSERT INTO nudges(action_id,task_id,conversation_id,status,created_at,updated_at) VALUES(?,?,?,'queued',?,?)", (action_id, target["id"], target["conversation_id"], now, now))
            self.db.commit()
            return self.nudge(action_id), True
        except Exception:
            self.db.rollback()
            raise

    def finish_nudge(self, action_id, status, error="", result=None):
        if status not in ("sending", "sent", "failed", "unknown"):
            raise ValueError("催办状态无效")
        with self.db:
            self.db.execute("""UPDATE nudges SET status=?,updated_at=?,error=?,result=? WHERE action_id=?
                AND status IN ('queued','sending')""", (status, time.time(), error, json.dumps(result or {}, ensure_ascii=False), action_id))

    def recover_nudges(self):
        with self.db:
            self.db.execute("""UPDATE nudges SET status='unknown',updated_at=?,error='上次催办未确认，请先核对原对话'
                WHERE status IN ('queued','sending')""", (time.time(),))

    def nudge_attention(self, action_id, text):
        with self.db:
            self.db.execute("UPDATE nudges SET attention=? WHERE action_id=?", (text, action_id))

    def snapshot(self):
        now = time.time()
        tasks = [dict(r) for r in self.db.execute("""SELECT tasks.*,COALESCE(conversations.host,'manual') AS host,
           COALESCE(conversations.thread_id,'') AS thread_id,COALESCE(conversations.title,'') AS conversation_title,
           COALESCE(conversations.cwd,'') AS cwd,COALESCE(conversations.path,'') AS path,
           COALESCE(conversations.summary,'') AS summary,conversations.analysis_state,
           COALESCE(conversations.updated_at,tasks.updated_at) AS conversation_updated_at
           FROM tasks LEFT JOIN conversations ON tasks.conversation_id=conversations.id
           WHERE tasks.status<>'merged' AND COALESCE(conversations.archived,0)=0 ORDER BY tasks.priority,tasks.updated_at DESC""")]
        conversations = []
        pending_ids = {c["id"] for c in self.eligible()}
        for r in self.db.execute("SELECT * FROM conversations ORDER BY updated_at DESC"):
            c = {k: r[k] for k in ("id", "host", "thread_id", "title", "cwd", "path", "updated_at", "analysis_state", "summary", "closed", "archived")}
            payload = json.loads(r["payload"])
            c["active"] = payload["active"]
            c["execution_state"] = self.execution_state(payload, now)
            c["needs_analysis"] = c["id"] in pending_ids
            conversations.append(c)
        settings = self.settings()
        # Keep the legacy local source ID so existing goals and receipts stay linked.
        configured = {"mac": local_host_name(), **{r["id"]: r["name"] for r in settings["remote_hosts"]}}
        hosts = [dict(dict(r), name=configured[r["id"]]) for r in self.db.execute("SELECT * FROM hosts") if r["id"] in configured]
        from schedule import automatic_state
        from summaries import history, schedule_state
        from updates import state as update_state
        nudges = [self.nudge(r[0]) for r in self.db.execute("""SELECT action_id FROM nudges WHERE status IN ('queued','sending','unknown')
            OR action_id IN (SELECT action_id FROM nudges ORDER BY created_at DESC LIMIT 100) ORDER BY created_at DESC""")]
        return {"tasks": tasks, "conversations": conversations, "hosts": hosts, "nudges": nudges,
                "summaries": history(self), "summary_schedule": schedule_state(self, now), "app_update": update_state(self), "settings": self.settings(), "schedule": automatic_state(self,now),
                "model": settings["analysis_model"], "effort": settings["analysis_effort"], "pending_analysis": len(pending_ids),
                "last_sync": self.meta("last_sync", 0), "last_analysis": self.meta("last_analysis", 0),
                "model_error": self.meta("model_error", ""), "sync": self.meta("sync", {}), "now": now}
