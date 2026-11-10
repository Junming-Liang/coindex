#!/usr/bin/env python3
"""Private stdio RPC; no network listener. Supports background sync while UI mutates state."""
import argparse
import concurrent.futures
import fcntl
import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import threading
import time

from collector import collect, redact, VERSION
from claude_collector import collect as claude_collect, merge as claude_merge, claude_root
from analyzer import analyze, codex_path, rewrite_task_copy
from store import Store
from connections import profile, ssh_command, ssh_aliases, local_check, remote_check, normalize_remote, codex_home
from schedule import automatic_state, refresh_calendars, refresh_needed, off_duty_state, finish_workday
from platform_paths import default_data_dir
import summaries
import updates
import taskmap


def collect_host(host, request, settings=None):
    settings = settings or {}
    entry = profile(settings, host)
    request = dict(request, host=host)
    request["root"] = entry.get("codex_home", "")
    claude_enabled = bool(settings.get("claude_enabled"))
    claude_home = str(claude_root(settings)) if host == "mac" else entry.get("claude_home", "")
    if host == "mac":
        result = collect(request)
        if claude_enabled:
            try:
                result = claude_merge(result, claude_collect(dict(request, root=claude_home)))
            except Exception as error:
                # Claude is an optional second leg; its failure must not hide Codex data.
                result.setdefault("read_errors", []).append({"path": "claude:" + claude_home, "error": redact(str(error))[:200]})
        return result
    code = pathlib.Path(__file__).with_name("collector.py").read_text()
    claude_code = pathlib.Path(__file__).with_name("claude_collector.py").read_text()
    # The scripts and request travel through stdin; neither remote files nor SSH settings change.
    wrapper = ("import json,sys,types\n"
               "data=json.loads(sys.stdin.read())\n"
               "mod=types.ModuleType('collector');sys.modules['collector']=mod;exec(data['code'],mod.__dict__)\n"
               "scope={'__name__':'claude_collector'};exec(data['claude_code'],scope)\n"
               "result=mod.collect(data['request'])\n"
               "if data.get('claude_enabled'):\n"
               " try:result=scope['merge'](result,scope['collect'](dict(data['request'],root=data.get('claude_root',''))))\n"
               " except Exception as error:result.setdefault('read_errors',[]).append({'path':'claude','error':scope['redact'](str(error))[:200]})\n"
               "print(json.dumps(result,ensure_ascii=False))")
    cmd = ssh_command(entry) + [shlex.quote(entry.get("python") or "python3") + " -c " + shlex.quote(wrapper)]
    payload = {"code": code, "claude_code": claude_code, "request": request,
               "claude_enabled": claude_enabled, "claude_root": claude_home}
    result = subprocess.run(cmd, input=json.dumps(payload), text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(redact(result.stderr.strip())[:500] or "SSH 采集失败")
    data = json.loads(result.stdout)
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data


def sync(folder, force=False, collect_only=False):
    store = Store(folder)
    lock = open(pathlib.Path(folder) / "sync.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {"busy": True}
    try:
        if off_duty_state(store)["off_duty"]:
            return {"accepted": False, "off_duty": True}
        settings = store.settings()
        store.put_meta("sync", {"running": True, "phase": "正在读取 %d 个来源的对话" % len(settings["enabled_hosts"]), "started_at": time.time()})
        if store.meta("collector_version", 0) != VERSION:
            with store.db:
                store.db.execute("DELETE FROM files")
            store.put_meta("collector_version", VERSION)
        if force:
            with store.db:
                store.db.execute("UPDATE conversations SET analyzed_fingerprint=NULL WHERE closed=0")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for host in settings["enabled_hosts"]:
                req = {"known": store.known(host), "days": settings["history_days"], "limit": settings["source_limit"]}
                futures[pool.submit(collect_host, host, req, settings)] = host
            for future in concurrent.futures.as_completed(futures):
                host = futures[future]
                try:
                    store.ingest(future.result())
                except Exception as e:
                    store.host_error(host, e)
        store.put_meta("last_sync", time.time())
        pending = store.eligible()
        batch = pending[:settings["batch_size"]]
        old_copy = store.copy_pending()[:12]
        analyzed_count, rewritten_count = 0, 0
        if old_copy and not collect_only:
            store.put_meta("sync", {"running": True, "phase": "正在精炼 %d 条待办的标题和进度" % len(old_copy), "started_at": time.time()})
            try:
                rewritten_count = store.apply_copy(rewrite_task_copy(old_copy, settings=settings), old_copy)
                store.put_meta("model_error", "")
            except Exception as e:
                store.put_meta("model_error", redact(str(e))[:1600])
        elif batch and not collect_only:
            store.put_meta("sync", {"running": True, "phase": "%s %s 正在分析 %d 个对话" % (settings["analysis_model"], settings["analysis_effort"], len(batch)), "started_at": time.time()})
            try:
                entries = analyze(batch, store.existing([c["id"] for c in batch]), settings=settings)
                store.reconcile(entries, batch)
                analyzed_count = len(entries)
                store.put_meta("last_analysis", time.time())
                store.put_meta("model_error", "")
            except Exception as e:
                store.put_meta("model_error", redact(str(e))[:1600])
        return {"collected": len(store.snapshot()["conversations"]), "analyzed": analyzed_count, "rewritten": rewritten_count}
    finally:
        store.put_meta("sync", {"running": False, "phase": "", "finished_at": time.time()})
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
        store.db.close()


def serve(folder):
    pathlib.Path(folder).mkdir(parents=True, exist_ok=True, mode=0o700)
    service_lock = open(pathlib.Path(folder) / "service.lock", "a+")
    fcntl.flock(service_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    output_lock = threading.Lock()
    worker = None
    calendar_worker = None
    nudge_workers = {}
    summary_worker = None
    summary_worker_id = None
    update_worker = None
    map_worker = None
    map_worker_id = None

    def emit(value):
        with output_lock:
            print(json.dumps(value, ensure_ascii=False), flush=True)

    # A dedicated sync process group lets Quit/EOF stop model children and SSH too.
    def stop_children():
        nonlocal worker
        stopped = False
        if worker and worker.poll() is None:
            stopped = True
            pid = worker.pid
            try:
                os.killpg(pid, signal.SIGTERM)
                worker.wait(timeout=0.4)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                # A parent may exit before its SSH/model child handles SIGTERM.
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    worker.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
        worker = None
        return stopped

    def finish(signum, frame):
        stop_children()
        stop_calendar()
        stop_nudges()
        stop_summary()
        stop_update()
        stop_map()
        store.put_meta("sync", {"running": False, "phase": ""})
        raise SystemExit(0)

    def stop_nudges():
        # Close only our transports. The original Codex engine and its turn survive.
        for action_id, child in nudge_workers.items():
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=0.4)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait(timeout=1)
            store.finish_nudge(action_id, "unknown", error="催办连接已关闭，请先核对原对话")
        nudge_workers.clear()

    def reap_update():
        nonlocal update_worker
        if update_worker and update_worker.poll() is not None:
            if updates.state(store)["checking"]:
                updates.cancel(store, "版本检查进程已退出，请重试")
            update_worker = None

    def stop_update():
        nonlocal update_worker
        if update_worker and update_worker.poll() is None:
            updates.cancel(store)
            try:
                os.killpg(update_worker.pid, signal.SIGTERM)
                update_worker.wait(timeout=0.5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try: os.killpg(update_worker.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                try: update_worker.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
        update_worker = None

    def start_update(automatic=False):
        nonlocal update_worker
        reap_update()
        if not updates.begin(store, automatic):
            return False
        try:
            cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--data-dir", str(folder), "update-check"]
            if automatic:
                cmd.append("--automatic")
            update_worker = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True)
        except Exception as error:
            updates.cancel(store, redact(str(error)))
            raise
        return True

    def reap_summary():
        nonlocal summary_worker, summary_worker_id
        if summary_worker and summary_worker.poll() is not None:
            summaries.fail(store, summary_worker_id, "总结进程已退出，结果未完成，可重新生成")
            summary_worker = None
            summary_worker_id = None

    def stop_summary(summary_id=None):
        nonlocal summary_worker, summary_worker_id
        if summary_id is None:
            summary_id = summary_worker_id
        if summary_id:
            # Mark first so a late model response can never resurrect a cancelled report.
            summaries.cancel(store, summary_id)
        if summary_worker and summary_worker_id == summary_id:
            if summary_worker.poll() is None:
                pid = summary_worker.pid
                try:
                    os.killpg(pid, signal.SIGTERM)
                    summary_worker.wait(timeout=0.5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
                finally:
                    try: os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    try: summary_worker.wait(timeout=1)
                    except subprocess.TimeoutExpired: pass
            summary_worker = None
            summary_worker_id = None

    def start_summary(selection, origin="manual"):
        nonlocal summary_worker, summary_worker_id
        reap_summary()
        summary_id = summaries.create(store, selection, origin)
        try:
            cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--data-dir", str(folder),
                   "summarize", "--summary-id", summary_id]
            summary_worker = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                              start_new_session=True)
            summary_worker_id = summary_id
        except Exception as error:
            summaries.fail(store, summary_id, error)
            raise
        return summary_id

    def reap_map():
        nonlocal map_worker, map_worker_id
        if map_worker and map_worker.poll() is not None:
            taskmap.fail(store, map_worker_id, "导图进程已退出，可重新分析；原有导图已保留")
            map_worker = None
            map_worker_id = None

    def stop_map(ident=None):
        nonlocal map_worker, map_worker_id
        ident = ident or map_worker_id
        if ident:
            taskmap.cancel(store, ident)
        if map_worker and map_worker_id == ident:
            pid = map_worker.pid
            if map_worker.poll() is None:
                try:
                    os.killpg(pid, signal.SIGTERM)
                    map_worker.wait(timeout=0.5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
                finally:
                    try: os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    try: map_worker.wait(timeout=1)
                    except subprocess.TimeoutExpired: pass
            map_worker = None
            map_worker_id = None

    def start_map(request):
        nonlocal map_worker, map_worker_id
        reap_map()
        ident = taskmap.create(store, request)
        try:
            cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--data-dir", str(folder), "task-map", "--map-id", ident]
            map_worker = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            map_worker_id = ident
        except Exception as error:
            taskmap.fail(store, ident, error)
            raise
        return ident

    def stop_calendar():
        if calendar_worker and calendar_worker.poll() is None:
            try:
                os.killpg(calendar_worker.pid,signal.SIGTERM)
                calendar_worker.wait(timeout=1)
            except (ProcessLookupError,subprocess.TimeoutExpired):
                try: os.killpg(calendar_worker.pid,signal.SIGKILL)
                except ProcessLookupError: pass

    def start_calendar(force=False):
        nonlocal calendar_worker
        if calendar_worker and calendar_worker.poll() is None:
            return
        if off_duty_state(store)["off_duty"]:
            return
        if force or refresh_needed(store):
            cmd = [sys.executable,str(pathlib.Path(__file__).resolve()),"--data-dir",str(folder),"calendar-refresh"]
            if force: cmd.append("--force")
            calendar_worker = subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

    signal.signal(signal.SIGTERM, finish)
    store = Store(folder)
    store.recover_nudges()
    summaries.recover(store)
    updates.recover(store)
    taskmap.recover(store)
    store.put_meta("sync", {"running": False, "phase": ""})
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            action = request.get("method", "snapshot")
            if action == "sync":
                rest = off_duty_state(store)
                allowed = not rest["off_duty"] and (not request.get("automatic") or (store.settings()["connection_setup_complete"] and automatic_state(store)["due"]))
                if allowed and (worker is None or worker.poll() is not None):
                    cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--data-dir", str(folder), "sync"]
                    if request.get("force"):
                        cmd.append("--force")
                    # Suppress stdout; polling snapshots exposes progress and errors without logs.
                    worker = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    store.put_meta("last_check",time.time())
                    store.put_meta("sync", {"running": True, "phase": "正在启动更新", "started_at": time.time()})
                result = {"accepted": allowed, **rest}
            elif action == "finish_workday":
                finish_workday(store)
                stop_children()
                stop_calendar()
                stop_summary()
                stop_map()
                store.put_meta("sync", {"running": False, "phase": "已下班", "finished_at": time.time()})
                result = store.snapshot()
            elif action == "resume_workday":
                store.put_meta("off_duty_until", 0)
                store.put_meta("sync", {"running": False, "phase": ""})
                result = store.snapshot()
            elif action == "cancel_sync":
                stopped = stop_children()
                # Explicit cancellation also pauses the scheduler, so it cannot restart immediately.
                store.save_settings({"automatic": False})
                store.put_meta("sync", {"running": False, "cancelled": stopped,
                                        "phase": "本次更新已中止" if stopped else "自动更新已暂停",
                                        "finished_at": time.time()})
                result = store.snapshot()
            elif action == "settings":
                if ((worker and worker.poll() is None) or (summary_worker and summary_worker.poll() is None) or (map_worker and map_worker.poll() is None)) and any(k in request.get("values", {}) for k in ("codex_home", "codex_cli", "codex_app", "claude_home", "claude_enabled", "remote_hosts", "analysis_model", "analysis_effort")):
                    raise ValueError("请先中止当前更新、总结或导图分析，再修改连接设置")
                store.save_settings(request.get("values", {}))
                result = store.snapshot()
            elif action == "ssh_aliases":
                result = {"aliases": ssh_aliases()}
            elif action == "open_thread":
                from nudge import open_desktop_thread
                from connections import desktop_host_id
                snapshot = store.snapshot()
                target = next((item for item in snapshot["conversations"] + snapshot["tasks"]
                               if item["id"] == request.get("entity_id") and item.get("thread_id")), None)
                if target is None:
                    raise ValueError("找不到关联的 Codex 对话")
                settings = store.settings()
                thread_id = target["thread_id"]
                if target.get("agent") == "claude":
                    cwd = target.get("cwd") or ""
                    command = ("cd " + shlex.quote(cwd) + " && " if cwd else "") + "claude --resume " + shlex.quote(thread_id)
                    result = {"opened": False, "command": command, "detail": "Claude 对话请在终端恢复；命令已生成"}
                else:
                    host_id = desktop_host_id(settings, target["host"])
                    request_id = request.get("id")
                    def open_and_emit(request_id=request_id, thread_id=thread_id, host_id=host_id, settings=settings):
                        try:
                            open_desktop_thread(thread_id, host_id, settings["codex_app"])
                            emit({"id": request_id, "result": {"opened": True}})
                        except Exception as error:
                            emit({"id": request_id, "error": redact(str(error))[:1000]})
                    threading.Thread(target=open_and_emit, daemon=True).start()
                    continue
            elif action == "ssh_terminal_command":
                result = {"command": shlex.join(ssh_command(request.get("profile", {}), interactive=True))}
            elif action == "check_connection":
                # Checks must not block snapshot polling, cancellation or manual edits.
                settings = store.settings()
                entry = normalize_remote(request["profile"]) if request.get("profile") else None
                request_id = request.get("id")
                def check_and_emit(request_id=request_id, settings=settings, entry=entry):
                    try:
                        checked = remote_check(entry, claude_enabled=bool(settings.get("claude_enabled"))) if entry else local_check(settings)
                        emit({"id": request_id, "result": checked})
                    except Exception as error:
                        emit({"id": request_id, "error": redact(str(error))[:1000]})
                threading.Thread(target=check_and_emit, daemon=True).start()
                continue
            elif action == "save_manual":
                task_id = store.save_manual(request.get("title",""),request.get("detail",""),request.get("priority",2),request.get("entity_id"))
                result = {"task_id":task_id,"snapshot":store.snapshot()}
            elif action == "rename_task":
                task_id = store.rename_task(request.get("entity_id"), request.get("title"))
                result = {"task_id":task_id,"snapshot":store.snapshot()}
            elif action == "nudge":
                record, created = store.queue_nudge(request["entity_id"], request["action_id"], request.get("retry_unknown") is True)
                if created:
                    cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--data-dir", str(folder), "nudge", "--action-id", record["action_id"]]
                    try:
                        nudge_workers[record["action_id"]] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    except Exception:
                        store.finish_nudge(record["action_id"], "failed", error="催办服务无法启动，请重试")
                result = store.snapshot()
            elif action == "refresh_calendar":
                if off_duty_state(store)["off_duty"]:
                    raise ValueError("已下班，请提前上班后再更新节假日数据")
                start_calendar(force=True)
                result = {"accepted":True}
            elif action == "act":
                store.act(request["action"], request["entity_id"], request.get("value"))
                result = store.snapshot()
            elif action == "check_updates":
                result = {"accepted": start_update(request.get("automatic") is True)}
            elif action == "skip_update":
                updates.skip(store, request["version"])
                result = store.snapshot()
            elif action == "open_update":
                if request.get("version") != updates.state(store)["version"]:
                    raise ValueError("该更新已变化，请重新检查版本")
                url = updates.download_url(store)
                request_id = request.get("id")
                def download_and_emit(url=url, request_id=request_id):
                    try:
                        command = ["open" if sys.platform == "darwin" else "xdg-open", url]
                        completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                        if completed.returncode:
                            raise RuntimeError("无法打开浏览器，请重试")
                        emit({"id": request_id, "result": {"opened": True}})
                    except Exception as error:
                        emit({"id": request_id, "error": redact(str(error))[:1000]})
                threading.Thread(target=download_and_emit, daemon=True).start()
                continue
            elif action == "summary_preview":
                result = summaries.preview(store, request)
            elif action == "task_map_detail":
                reap_map()
                result = taskmap.detail(store, request)
            elif action == "task_map_analyze":
                start_map(request)
                result = taskmap.detail(store, request)
            elif action == "task_map_cancel":
                stop_map(request["job_id"])
                result = taskmap.detail(store, request)
            elif action == "summary_generate":
                summary_id = start_summary(request)
                result = {"summary_id": summary_id, "snapshot": store.snapshot()}
            elif action == "summary_detail":
                result = summaries.detail(store, request["summary_id"])
            elif action == "summary_cancel":
                stop_summary(request["summary_id"])
                result = store.snapshot()
            elif action == "summary_settings":
                summaries.save_schedule(store, request.get("values", {}))
                result = store.snapshot()
            elif action == "snapshot":
                reap_update()
                reap_summary()
                if worker is None or worker.poll() is not None:
                    selection = summaries.automatic_request(store)
                    if selection is not None:
                        start_summary(selection, "automatic")
                for action_id, child in list(nudge_workers.items()):
                    if child.poll() is not None:
                        store.finish_nudge(action_id, "unknown", error="催办连接意外关闭，请先核对原对话")
                        del nudge_workers[action_id]
                result = store.snapshot()
            elif action == "diagnostics":
                result = {"python": sys.executable, "codex": codex_path(store.settings()), "codex_home": str(codex_home(store.settings())), "data": str(store.path)}
            else:
                raise ValueError("未知请求")
            emit({"id": request.get("id"), "result": result})
            start_calendar()
        except Exception as e:
            emit({"id": request.get("id"), "error": redact(str(e))[:1000]})
    stop_children()
    stop_calendar()
    stop_nudges()
    stop_summary()
    stop_map()
    stop_update()
    store.put_meta("sync", {"running": False, "phase": ""})
    store.db.close()
    service_lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(default_data_dir()))
    parser.add_argument("command", choices=["serve", "sync", "snapshot", "act", "diagnostics", "calendar-refresh", "nudge", "summarize", "update-check", "task-map"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--action")
    parser.add_argument("--id")
    parser.add_argument("--action-id")
    parser.add_argument("--summary-id")
    parser.add_argument("--map-id")
    parser.add_argument("--automatic", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.data_dir)
    elif args.command == "update-check":
        store = Store(args.data_dir)
        try:
            updates.perform(store, args.automatic)
        finally:
            store.db.close()
    elif args.command == "summarize":
        store = Store(args.data_dir)
        try:
            summaries.run(store, args.summary_id)
        finally:
            store.db.close()
    elif args.command == "task-map":
        store = Store(args.data_dir)
        try:
            taskmap.run(store, args.map_id)
        finally:
            store.db.close()
    elif args.command == "nudge":
        from nudge import run_nudge
        run_nudge(args.data_dir, args.action_id)
    elif args.command == "calendar-refresh":
        store = Store(args.data_dir)
        refresh_calendars(store,args.force)
        store.db.close()
    elif args.command == "sync":
        print(json.dumps(sync(args.data_dir, args.force, args.collect_only), ensure_ascii=False))
    else:
        store = Store(args.data_dir)
        if args.command == "act":
            store.act(args.action, args.id)
        if args.command == "diagnostics":
            print(json.dumps({"codex": codex_path(), "python": sys.executable}))
        else:
            print(json.dumps(store.snapshot(), ensure_ascii=False))


if __name__ == "__main__":
    main()
