#!/usr/bin/env python3
"""Linux desktop interface for coindex's private stdio backend."""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
except ImportError:  # --help remains usable on minimal Python installs.
    tk = None
    messagebox = simpledialog = ttk = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_paths import default_data_dir
try:
    from .palette import TOKENS
except ImportError:
    from linux.palette import TOKENS
if tk is not None:
    try:
        from .design import apply_theme, RoundedPanel, Icon
        from .summaries import SummaryPage
        from .updates import UpdateController
    except ImportError:  # Direct script entry point.
        from linux.design import apply_theme, RoundedPanel, Icon
        from linux.summaries import SummaryPage
        from linux.updates import UpdateController



def demo_snapshot():
    now = time.time()
    rows = [
        ("review", "文档搜索功能验收", "搜索功能已提交；尚未做集成验证", "在测试环境验证完整搜索流程", "PR #123 已创建"),
        ("continue", "修复应用自动更新", "已定位版本比较错误；尚未改代码", "修改版本比较规则后验证升级流程", "复现步骤已记录"),
        ("wait", "降低图片上传等待时间", "两组基准测试已进入队列", "查询基准测试的运行状态", "任务已排队"),
    ]
    tasks, conversations = [], []
    for i, (kind, title, progress, action, evidence) in enumerate(rows):
        cid = "mac:demo-" + str(i)
        tasks.append({"id": "demo-task-" + str(i), "conversation_id": cid, "kind": kind, "title": title,
                      "detail": "演示数据仅用于浏览界面。", "progress": progress, "next_action": action,
                      "evidence": evidence, "artifact": "演示记录", "priority": i + 1, "status": "open",
                      "snoozed_until": 0, "host": "mac", "thread_id": "demo-" + str(i),
                      "conversation_title": ["文档检索功能", "自动更新排查", "上传性能测试"][i],
                      "cwd": "/workspace/example", "path": "/example/session.jsonl", "updated_at": now - i * 600})
        conversations.append({"id": cid, "host": "mac", "thread_id": "demo-" + str(i),
                              "title": tasks[-1]["conversation_title"], "cwd": "/workspace/example",
                              "path": "/example/session.jsonl", "updated_at": now - i * 600,
                              "summary": "演示对话", "closed": 0, "archived": 0, "active": False,
                              "execution_state": "idle"})
    return {"tasks": tasks, "conversations": conversations,
            "hosts": [{"id": "mac", "name": "本机 / Linux", "status": "online", "detail": "演示数据"}],
            "nudges": [], "settings": {"automatic": True, "interval_seconds": 1800, "idle_minutes": 10,
                "batch_size": 6, "history_days": 0, "enabled_hosts": ["mac"], "workdays_only": True,
                "work_hours_enabled": False, "work_start_minutes": 540, "work_end_minutes": 1080,
                "codex_home": "", "codex_cli": "", "codex_app": "", "remote_hosts": [],
                "analysis_model": "gpt-6-luna", "analysis_effort": "max", "connection_setup_complete": False},
            "schedule": {"due": False, "summary": "演示模式", "next_at": None},
            "sync": {"running": False, "phase": ""}, "model": "gpt-6-luna", "effort": "max",
            "pending_analysis": 0, "last_sync": now, "model_error": "", "now": now}


def load_demo_snapshot():
    """Load the packaged fixture, or generate an isolated source-tree fixture."""
    packaged = ROOT / "demo.json"
    if packaged.is_file():
        return json.loads(packaged.read_text(encoding="utf-8"))
    generator = ROOT / "scripts" / "create-demo.py"
    if generator.is_file():
        with tempfile.TemporaryDirectory(prefix="coindex-demo-") as temp:
            output = pathlib.Path(temp) / "demo.json"
            subprocess.run([sys.executable, str(generator), str(output)], check=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return json.loads(output.read_text(encoding="utf-8"))
    return demo_snapshot()


class StdioClient:
    """Line-oriented RPC client. All Tk calls stay on the main thread."""
    def __init__(self, command, on_message, on_exit=None, on_callback_error=None, popen=subprocess.Popen):
        self.on_message = on_message
        self.on_exit = on_exit
        self.on_callback_error = on_callback_error
        self.process = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
        self.lock = threading.Lock()
        self.messages = queue.Queue()
        self.pending = {}
        self.closed = False
        self.exit_delivered = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def request(self, method, callback=None, **values):
        if self.closed or self.process.poll() is not None:
            raise RuntimeError("本地服务已关闭")
        request_id = str(uuid.uuid4())
        request = {"id": request_id, "method": method, **values}
        with self.lock:
            if callback:
                self.pending[request_id] = callback
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        return request_id

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("RPC responses must be objects")
                    self.messages.put(message)
                except (ValueError, TypeError):
                    self.messages.put({"_unmatched": True, "error": "服务返回了无法识别的数据"})
        finally:
            try:
                self.process.stdout.close()
            except OSError:
                pass
            self.messages.put({"_closed": True, "returncode": self.process.poll()})

    def _callback_failed(self, error):
        if self.on_callback_error:
            try:
                self.on_callback_error(error)
            except Exception:
                pass

    def drain(self):
        while True:
            try:
                msg = self.messages.get_nowait()
            except queue.Empty:
                break
            if msg.get("_closed"):
                self.exit_delivered = True
                for request_id, callback in list(self.pending.items()):
                    self.pending.pop(request_id, None)
                    try:
                        callback({"id": request_id, "error": "本地服务已退出"})
                    except Exception as exc:
                        self._callback_failed(exc)
                if self.on_exit:
                    try:
                        self.on_exit(msg.get("returncode"))
                    except Exception as exc:
                        self._callback_failed(exc)
                continue
            if msg.get("_unmatched"):
                self._callback_failed(RuntimeError(msg.get("error", "服务响应无法匹配请求")))
                continue
            callback = self.pending.pop(msg.get("id"), None)
            if callback:
                try:
                    callback(msg)
                except Exception as exc:
                    self._callback_failed(exc)
            elif msg.get("id"):
                self._callback_failed(RuntimeError("服务响应编号无法匹配请求"))

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.process.stdin.close()
        except (OSError, AttributeError):
            pass
        # Keep this short-lived reaper alive after the window closes, so a stalled
        # service cannot be orphaned merely because the GUI's main thread exits.
        threading.Thread(target=self._reap_owned_process).start()

    def _reap_owned_process(self):
        if self.process.poll() is not None:
            self.process.wait()
            return
        try:
            self.process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        except ProcessLookupError:
            pass
        try:
            self.process.kill()
        except ProcessLookupError:
            pass
        self.process.wait()


class CoindexApp:
    BG, SURFACE, SIDEBAR = TOKENS["canvas"], TOKENS["surface"], TOKENS["sidebar"]
    BORDER, INK, MUTED, ACCENT = TOKENS["border"], TOKENS["ink"], TOKENS["muted"], TOKENS["accent"]

    def __init__(self, root, data_dir=None, demo=False, client_factory=StdioClient, demo_data=None, smoke_test=False):
        self.root, self.demo = root, demo
        self.snapshot = copy.deepcopy(demo_data) if demo_data is not None else (load_demo_snapshot() if demo else {})
        self.data_dir = pathlib.Path(data_dir or default_data_dir()).expanduser()
        self.client = None
        self.selected_task = None
        self.tab = "tasks"
        self.show_inactive = False
        self.request_inflight = False
        self.last_auto_sync = 0
        self.initial_settings_prompted = False
        self.task_cards = {}
        self._task_order = []
        self._filter_signature = None
        self._detail_signature = None
        self.empty_state = None
        self._empty_signature = None
        self._conversation_filter = None
        self.client_factory = client_factory
        self.updates = UpdateController(self)
        self._build()
        if demo:
            self._render()
            self.status_var.set("演示模式 · 所有数据均为虚构，修改与连接操作已停用")
            if smoke_test:
                self.root.after(300, self._finish_smoke_test)
        else:
            self.client = self.client_factory([sys.executable, str(BACKEND / "service.py"), "--data-dir",
                                              str(self.data_dir), "serve"], self._incoming, self._service_exit,
                                              self._callback_error)
            self.root.after(50, self._drain)
            self._rpc("snapshot", self._snapshot_result)

    @classmethod
    def from_args(cls, argv=None):
        parser = argparse.ArgumentParser(description="coindex Linux desktop task workspace")
        parser.add_argument("--data-dir", default=None, help="coindex data directory")
        parser.add_argument("--demo", action="store_true", help="show fictional sample data without starting the service")
        parser.add_argument("--smoke-test", action="store_true", help="render demo widgets and exit (requires --demo)")
        args = parser.parse_args(argv)
        if args.smoke_test and not args.demo:
            parser.error("--smoke-test requires --demo")
        if tk is None:
            raise SystemExit("Tkinter is unavailable; install the python3-tk system package")
        root = tk.Tk()
        return cls(root, args.data_dir, args.demo, smoke_test=args.smoke_test)

    def _finish_smoke_test(self):
        try:
            if not self.snapshot.get("tasks") or not self.visible_task_ids:
                raise RuntimeError("demo task list did not render")
            self._select_task(self.visible_task_ids[0])
            if not self.detail_content.winfo_children():
                raise RuntimeError("task detail pane did not render")
            self.root.destroy()
        except Exception as exc:
            self.smoke_error = str(exc)
            self.root.destroy()

    def _build(self):
        self.root.title("coindex · 演示" if self.demo else "coindex")
        self.root.geometry("1240x820")
        self.root.minsize(1000, 680)
        self.root.configure(bg=self.BG)
        self.font_family = apply_theme(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Destroy>", self._destroyed, add=True)
        self.root.bind("<Control-f>", lambda _e: self.search_entry.focus_set())
        self.root.bind("<Control-n>", lambda _e: self.new_task())
        shell = tk.Frame(self.root, bg=self.BG)
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=self.SIDEBAR, width=208)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(shell, bg=self.BORDER, width=1).pack(side="left", fill="y")
        footer = tk.Frame(sidebar, bg=self.SIDEBAR)
        footer.pack(side="bottom", fill="x", padx=16, pady=8)
        self.settings_button = ttk.Button(footer, text="偏好设置", style="Nav.TButton", command=self.open_settings)
        self.settings_button.pack(fill="x", pady=(0, 4))
        self.sidebar_status = tk.Label(footer, text="正在连接…", bg=self.SIDEBAR, fg=self.MUTED,
                                       justify="left", wraplength=174, font=(self.font_family, 9))
        self.sidebar_status.pack(anchor="w", padx=6)
        footer_actions = tk.Frame(footer, bg=self.SIDEBAR)
        footer_actions.pack(fill="x", pady=(10, 0))
        self.check_updates_button = ttk.Button(footer_actions, text="检查更新…", width=0, style="Sidebar.Quiet.TButton", command=self.updates.check)
        self.check_updates_button.pack(side="left")
        self.workday_button = ttk.Button(footer_actions, text="下班", width=0, style="Sidebar.Quiet.TButton", command=self.toggle_workday)
        self.workday_button.pack(side="right")
        records = tk.Frame(sidebar, bg=self.SIDEBAR)
        records.pack(side="bottom", fill="x", pady=(0, 6))
        tk.Frame(records, height=1, bg=self.BORDER).pack(fill="x", padx=18, pady=8)
        self.nav_convs = ttk.Button(records, text="所有对话", style="Nav.TButton", command=lambda: self._switch("conversations"))
        self.nav_convs.pack(fill="x", padx=10, pady=2)
        self.nav_summaries = ttk.Button(records, text="总结", style="Nav.TButton", command=lambda: self._switch("summaries"))
        self.nav_summaries.pack(fill="x", padx=10, pady=2)

        brand = tk.Frame(sidebar, bg=self.SIDEBAR)
        brand.pack(fill="x", padx=20, pady=(20, 16))
        icon_path = ROOT / "Resources/Brand/AppIcon.png"
        if icon_path.is_file():
            original = tk.PhotoImage(file=str(icon_path))
            self.brand_image = original.subsample(max(1, original.width() // 30))
            tk.Label(brand, image=self.brand_image, bg=self.SIDEBAR).pack(side="left", padx=(0, 9))
        tk.Label(brand, text="coindex", bg=self.SIDEBAR, fg=self.INK,
                 font=(self.font_family, 17, "bold")).pack(side="left")
        nav_host = tk.Frame(sidebar, bg=self.SIDEBAR)
        nav_host.pack(fill="both", expand=True)
        self.sidebar_canvas = tk.Canvas(nav_host, bg=self.SIDEBAR, highlightthickness=0, width=190)
        nav_scroll = ttk.Scrollbar(nav_host, orient="vertical", command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=nav_scroll.set)
        self.sidebar_canvas.pack(side="left", fill="both", expand=True)
        nav_scroll.pack(side="right", fill="y")
        navigation = tk.Frame(self.sidebar_canvas, bg=self.SIDEBAR)
        nav_window = self.sidebar_canvas.create_window((0, 0), window=navigation, anchor="nw")
        navigation.bind("<Configure>", lambda _event: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        self.sidebar_canvas.bind("<Configure>", lambda event: self.sidebar_canvas.itemconfigure(nav_window, width=event.width))
        tk.Label(navigation, text="工作空间", bg=self.SIDEBAR, fg=self.MUTED,
                 font=(self.font_family, 9)).pack(anchor="w", padx=22, pady=(0, 8))
        self.nav_tasks = ttk.Button(navigation, text="所有待办", style="Selected.Nav.TButton", command=lambda: self._choose_kind("全部类型"))
        self.nav_tasks.pack(fill="x", padx=10, pady=2)
        self.category_buttons = {}
        for label, kind in (("进行中", "进行中"), ("结果校对", "结果校对"), ("继续推进", "继续"),
                            ("等待结果", "等待"), ("需要决定", "决策"), ("手动待办", "手动")):
            button = ttk.Button(navigation, text=label, style="Nav.TButton", command=lambda k=kind: self._choose_kind(k))
            button.pack(fill="x", padx=10, pady=1)
            self.category_buttons[kind] = (button, label)
        self.history_button = ttk.Button(navigation, text="已完成 / 稍后", style="Nav.TButton", command=self._choose_history)
        self.history_button.pack(fill="x", padx=10, pady=(10, 1))

        def reveal_navigation(event):
            widget = event.widget
            top = self.sidebar_canvas.canvasy(0)
            y, height = widget.winfo_y(), widget.winfo_height()
            viewport = self.sidebar_canvas.winfo_height()
            if y < top:
                self._restore_canvas_y(self.sidebar_canvas, y)
            elif y + height > top + viewport:
                self._restore_canvas_y(self.sidebar_canvas, y + height - viewport)
        for button in [self.nav_tasks, self.history_button] + [item[0] for item in self.category_buttons.values()]:
            button.bind("<FocusIn>", reveal_navigation, add=True)

        content = ttk.Frame(shell, padding=(28, 26, 24, 20))
        content.pack(side="left", fill="both", expand=True)
        header = ttk.Frame(content)
        header.pack(fill="x", pady=(0, 6))
        self.heading_var = tk.StringVar(value="所有待办")
        ttk.Label(header, textvariable=self.heading_var, style="Title.TLabel").pack(side="left")
        self.primary_button = ttk.Button(header, text="＋ 新建待办", style="Accent.TButton", command=self.new_task)
        self.primary_button.pack(side="right")
        self.update_button = ttk.Button(header, text="更新", command=self.manual_sync)
        self.update_button.pack(side="right", padx=(0, 8))
        self.stop_button = ttk.Button(header, text="中止更新", style="Danger.TButton", command=self.cancel_sync)
        self.summary_var = tk.StringVar(value="把每件事的进展和下一步放在一起。")
        ttk.Label(content, textvariable=self.summary_var, style="Muted.TLabel").pack(anchor="w", pady=(2, 20))
        self.status_var = tk.StringVar(value="")
        status_bar = tk.Frame(content, bg=self.BG)
        status_bar.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(status_bar, text="状态详情", style="Quiet.TButton", command=self._show_status).pack(side="right", padx=(8, 0))
        self.status_line = tk.Label(status_bar, textvariable=self.status_var, bg=self.BG, fg=self.MUTED,
                                    font=(self.font_family, 9), height=2, anchor="w", justify="left", wraplength=860)
        self.status_line.pack(side="left", fill="x", expand=True)
        self.status_line.bind("<Configure>", lambda event: self.status_line.configure(wraplength=max(200, event.width)))

        self.search_var = tk.StringVar()
        self.kind_var = tk.StringVar(value="全部类型")
        self.host_var = tk.StringVar(value="全部来源")
        self.inactive_var = tk.BooleanVar(value=False)
        self.task_filters = ttk.Frame(content)
        self.task_filters.pack(fill="x", pady=(0, 18))
        search_wrap = tk.Frame(self.task_filters, bg=self.SURFACE, highlightthickness=1,
                               highlightbackground=self.BORDER, padx=10, pady=5)
        search_wrap.pack(side="left", fill="x", expand=True, padx=(0, 10))
        Icon(search_wrap, "search", bg=self.SURFACE, color=self.MUTED).pack(side="left", padx=(0, 8))
        self.search_entry = ttk.Entry(search_wrap, textvariable=self.search_var, style="Search.TEntry")
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<FocusIn>", lambda _e: search_wrap.configure(highlightbackground=self.ACCENT))
        self.search_entry.bind("<FocusOut>", lambda _e: search_wrap.configure(highlightbackground=self.BORDER))
        self.search_hint = tk.Label(self.search_entry, text="搜索标题、进度或对话", bg=self.SURFACE, fg=self.MUTED,
                                    font=(self.font_family, 10), cursor="xterm")
        self.search_hint.place(x=3, rely=.5, anchor="w")
        self.search_hint.bind("<Button-1>", lambda _e: self.search_entry.focus_set())
        self.search_entry.bind("<FocusIn>", lambda _e: self.search_hint.place_forget(), add=True)
        self.search_entry.bind("<FocusOut>", lambda _e: self._search_placeholder(), add=True)
        self.search_var.trace_add("write", lambda *_: (self._search_placeholder(), self._render_tasks()))
        self.host_box = ttk.Combobox(self.task_filters, textvariable=self.host_var, values=("全部来源",), state="readonly", width=15)
        self.host_box.pack(side="right", ipady=4)
        self.host_box.bind("<<ComboboxSelected>>", lambda _e: self._render_tasks())
        self.result_label = ttk.Label(content, style="Caption.TLabel")
        self.result_label.pack(anchor="w", pady=(0, 10))
        self.task_page = ttk.Frame(content)
        self.conversation_page = ttk.Frame(content)
        self.summary_page = SummaryPage(content, self)
        self.task_page.pack(fill="both", expand=True)
        task_split = ttk.Frame(self.task_page)
        task_split.pack(fill="both", expand=True)
        list_frame = tk.Frame(task_split, bg=self.BG)
        self.task_list_frame = list_frame
        list_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(list_frame, bg=self.BG, highlightthickness=0)
        self.task_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.task_scroll.set)
        self.task_scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.cards = tk.Frame(self.canvas, bg=self.BG)
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.cards_window, width=e.width))
        self.root.bind_all("<MouseWheel>", self._wheel)
        self.root.bind_all("<Button-4>", self._wheel)
        self.root.bind_all("<Button-5>", self._wheel)
        self.detail = tk.Frame(task_split, bg=self.SURFACE, width=340, highlightthickness=1, highlightbackground=self.BORDER)
        self.detail.pack(side="right", fill="y", padx=(20, 0))
        self.detail.pack_propagate(False)
        self.detail_canvas = tk.Canvas(self.detail, bg=self.SURFACE, highlightthickness=0, takefocus=True)
        self.detail_scroll = ttk.Scrollbar(self.detail, orient="vertical", command=self.detail_canvas.yview)
        self.detail_canvas.configure(yscrollcommand=self.detail_scroll.set)
        self.detail_canvas.pack(side="left", fill="both", expand=True)
        self.detail_scroll.pack(side="right", fill="y")
        self.detail_content = tk.Frame(self.detail_canvas, bg=self.SURFACE, padx=20, pady=22)
        self.detail_window = self.detail_canvas.create_window((0, 0), window=self.detail_content, anchor="nw")
        self.detail_content.bind("<Configure>", lambda _e: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")))
        self.detail_canvas.bind("<Configure>", lambda e: self.detail_canvas.itemconfigure(self.detail_window, width=e.width))
        self.detail_canvas.bind("<Button-1>", lambda _e: self.detail_canvas.focus_set())
        self.detail_canvas.bind("<Up>", lambda _e: self.detail_canvas.yview_scroll(-1, "units"))
        self.detail_canvas.bind("<Down>", lambda _e: self.detail_canvas.yview_scroll(1, "units"))
        self._clear_detail()

        self.conversations = ttk.Treeview(self.conversation_page, columns=("host", "state", "updated"), show="tree headings", selectmode="browse")
        for name, label, width in (("#0", "对话", 340), ("host", "来源", 130), ("state", "状态", 110), ("updated", "最近更新", 140)):
            self.conversations.heading(name, text=label, anchor="w")
            self.conversations.column(name, width=width, minwidth=80, stretch=name == "#0")
        conv_list = ttk.Frame(self.conversation_page)
        conv_list.pack(fill="both", expand=True, pady=(0, 14))
        self.conversations.pack(in_=conv_list, side="left", fill="both", expand=True)
        conv_scroll = ttk.Scrollbar(conv_list, orient="vertical", command=self.conversations.yview)
        conv_scroll.pack(side="right", fill="y")
        self.conversations.configure(yscrollcommand=conv_scroll.set)
        self.conv_inactive_var = tk.BooleanVar(value=False)
        actions = ttk.Frame(self.conversation_page)
        actions.pack(fill="x")
        ttk.Checkbutton(actions, text="显示已结束对话", variable=self.conv_inactive_var,
                        command=self._toggle_conversations).pack(side="left")
        self.open_conv_button = ttk.Button(actions, text="打开对话", command=self.open_conversation)
        self.open_conv_button.pack(side="right")
        self.close_conv_button = ttk.Button(actions, text="结束跟踪", style="Quiet.TButton", command=self.toggle_conversation)
        self.close_conv_button.pack(side="right", padx=8)
        self._disable_mutations()

    def _search_placeholder(self):
        if not hasattr(self, "search_hint"):
            return
        if self.search_var.get() or self.root.focus_get() == self.search_entry:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(x=3, rely=.5, anchor="w")

    def _show_status(self):
        messagebox.showinfo("状态详情", self.status_var.get() or "暂无状态信息", parent=self.root)

    def _choose_kind(self, kind):
        self.kind_var.set(kind)
        self.inactive_var.set(False)
        self.show_inactive = False
        self._switch("tasks")

    def _choose_history(self):
        self.kind_var.set("全部类型")
        self.inactive_var.set(True)
        self.show_inactive = True
        self._switch("tasks")

    def _refresh_navigation(self):
        now = time.time()
        tasks = self.snapshot.get("tasks", [])
        active = [t for t in tasks if t.get("status", "open") == "open" and t.get("snoozed_until", 0) <= now]
        all_selected = self.tab == "tasks" and not self.show_inactive and self.kind_var.get() == "全部类型"
        self.nav_tasks.configure(text="所有待办    %d" % len(active), style="Selected.Nav.TButton" if all_selected else "Nav.TButton")
        for kind, (button, label) in self.category_buttons.items():
            count = sum(self._kind_label(t.get("kind")) == kind for t in active)
            selected = self.tab == "tasks" and not self.show_inactive and self.kind_var.get() == kind
            button.configure(text="%s    %d" % (label, count), style="Selected.Nav.TButton" if selected else "Nav.TButton")
        self.history_button.configure(style="Selected.Nav.TButton" if self.tab == "tasks" and self.show_inactive else "Nav.TButton")
        self.nav_convs.configure(style="Selected.Nav.TButton" if self.tab == "conversations" else "Nav.TButton")
        self.nav_summaries.configure(style="Selected.Nav.TButton" if self.tab == "summaries" else "Nav.TButton")

    def _disable_mutations(self):
        if self.demo:
            for widget in (self.primary_button, self.update_button, self.settings_button, self.open_conv_button,
                           self.close_conv_button, self.workday_button, self.stop_button, self.check_updates_button):
                widget.configure(state="disabled")

    def _rpc(self, method, callback=None, **kwargs):
        if not self.client:
            return None
        try:
            return self.client.request(method, callback, **kwargs)
        except Exception as exc:
            self._error(str(exc))
            return None

    def _incoming(self, _message):
        # Compatibility hook for injected clients; StdioClient queues messages itself.
        pass

    def _drain(self):
        if self.client:
            self.client.drain()
            # EOF is queued by the reader thread slightly after process exit.
            if not self.client.closed and not getattr(self.client, "exit_delivered", False):
                self.root.after(50, self._drain)

    def _service_exit(self, code):
        if not self.client or self.client.closed:
            return
        self.sidebar_status.configure(text="本地服务已退出" + ("" if code in (None, 0) else "（错误 %s）" % code), fg="#A34444")

    def _callback_error(self, error):
        self._error("界面处理服务响应失败：%s" % error)

    def _snapshot_result(self, response):
        if response.get("error"):
            self._error(response["error"])
            return
        self.snapshot = response.get("result", {})
        self._render()
        if (not self.demo and not self.initial_settings_prompted
                and not self.snapshot.get("settings", {}).get("connection_setup_complete")):
            self.initial_settings_prompted = True
            self.root.after_idle(self.open_settings)
        self._maybe_auto_sync()
        if self.client and not self.client.closed:
            self.root.after(2500, lambda: self._rpc("snapshot", self._snapshot_result))

    def _maybe_auto_sync(self):
        settings = self.snapshot.get("settings", {})
        schedule = self.snapshot.get("schedule", {})
        if (settings.get("automatic") and settings.get("connection_setup_complete") and schedule.get("due")
                and not self.snapshot.get("sync", {}).get("running") and not self.request_inflight
                and time.monotonic() - self.last_auto_sync > 30):
            self.last_auto_sync = time.monotonic()
            self._rpc("sync", lambda _r: None, automatic=True)

    def _render(self):
        settings = self.snapshot.get("settings", {})
        schedule = self.snapshot.get("schedule", {})
        sync = self.snapshot.get("sync", {})
        notices = [sync.get("phase") or schedule.get("summary", "")]
        if self.snapshot.get("model_error"):
            notices.append("分析提示：" + str(self.snapshot["model_error"])[:180])
        for host in self.snapshot.get("hosts", []):
            if host.get("status") in ("offline", "partial"):
                label = "本机 / Linux" if host.get("id") == "mac" else host.get("name") or host.get("id", "来源")
                notices.append("%s：%s" % (label, str(host.get("detail") or "连接异常")[:100]))
        self.status_var.set(" · ".join(x for x in notices if x))
        self.sidebar_status.configure(text="演示模式" if self.demo else
                                      "请先检查本机连接" if not settings.get("connection_setup_complete") else
                                      "自动更新已开启" if settings.get("automatic") else "自动更新已暂停")
        self.workday_button.configure(text="上班" if schedule.get("off_duty") else "下班")
        if sync.get("running") and not self.demo:
            if not self.stop_button.winfo_manager():
                self.stop_button.pack(side="right", padx=(0, 8))
        elif self.stop_button.winfo_manager():
            self.stop_button.pack_forget()
        names = {h["id"]: ("本机 / Linux" if h["id"] == "mac" else h.get("name") or h["id"])
                 for h in self.snapshot.get("hosts", [])}
        names["manual"] = "手动"
        hosts = ["全部来源"] + list(dict.fromkeys(names.get(t.get("host"), t.get("host", "")) for t in self.snapshot.get("tasks", [])))
        self.host_values = {label: key for key, label in names.items()}
        current = self.host_var.get()
        self.host_box.configure(values=hosts)
        if current not in hosts:
            self.host_var.set("全部来源")
        self._render_tasks()
        self._render_conversations()
        self.summary_page.render()
        self.updates.observe()
        self._refresh_navigation()

    def _kind_label(self, kind):
        return {"review": "结果校对", "continue": "继续", "wait": "等待", "decision": "决策", "manual": "手动", "running": "进行中"}.get(kind, kind or "任务")

    def _render_tasks(self):
        if not hasattr(self, "cards"):
            return
        tasks = self.snapshot.get("tasks", [])
        search = self.search_var.get().strip().lower()
        chosen_kind = self.kind_var.get()
        chosen_host = self.host_var.get()
        by_id = {t["id"]: t for t in tasks}
        rows = []
        now = time.time()
        for task in tasks:
            status = task.get("status", "open")
            inactive = status != "open" or task.get("snoozed_until", 0) > now
            if inactive != self.show_inactive:
                continue
            if search and search not in " ".join(str(task.get(k, "")) for k in ("title", "detail", "progress", "evidence", "next_action", "conversation_title")).lower():
                continue
            if chosen_kind != "全部类型" and self._kind_label(task.get("kind")) != chosen_kind:
                continue
            if chosen_host != "全部来源" and self.host_values.get(chosen_host, chosen_host) != task.get("host"):
                continue
            rows.append(task)
        filters = (search, chosen_kind, chosen_host, self.show_inactive)
        filter_changed = filters != self._filter_signature
        self._filter_signature = filters
        top = self.canvas.canvasy(0)
        anchor = next(((tid, top - self.task_cards[tid][0].winfo_y()) for tid in self._task_order
                       if self.task_cards[tid][0].winfo_y() + self.task_cards[tid][0].winfo_height() > top), None)
        focused = self.root.focus_get()
        focused_card = next((tid for tid, (card, _) in self.task_cards.items()
                             if focused and (str(focused) == str(card) or str(focused).startswith(str(card) + "."))), None)
        self.visible_task_ids = [t["id"] for t in rows]
        self.selected_task = self.selected_task if self.selected_task in self.visible_task_ids else (rows[0]["id"] if rows else None)
        self.result_count = len(rows)
        self.result_label.configure(text="%d 项%s" % (len(rows), "历史事项" if self.show_inactive else "待跟进事项"))
        layout_changed = self._task_order != self.visible_task_ids
        for tid in list(self.task_cards):
            if tid not in self.visible_task_ids:
                self.task_cards.pop(tid)[0].destroy()
        for task in rows:
            tid = task["id"]
            key = (task.get("kind"), task.get("title"), self._host_label(task.get("host")),
                   task.get("progress") or task.get("detail"), task.get("next_action"))
            previous = self.task_cards.get(tid)
            selected = tid == self.selected_task
            if previous is None:
                self.task_cards[tid] = (self._task_card(task, selected), key)
                layout_changed = True
            else:
                card = previous[0]
                if previous[1] != key:
                    self._update_task_card(card, task)
                    self.task_cards[tid] = (card, key)
                    layout_changed = True
                if card.selected != selected:
                    card.selected = selected
                    card.set_outline(self.ACCENT if selected else self.BORDER)
        if rows and self.empty_state is not None:
            self.empty_state.destroy()
            self.empty_state = None
            self._empty_signature = None
        if rows and layout_changed:
            previous = None
            for tid in self.visible_task_ids:
                card = self.task_cards[tid][0]
                first = self.cards.pack_slaves()[0]
                if previous is not None:
                    card.pack_configure(after=previous)
                elif card is not first:
                    card.pack_configure(before=first)
                previous = card
        self._task_order = list(self.visible_task_ids)
        if not rows:
            if self._empty_signature != filters:
                if self.empty_state is not None:
                    self.empty_state.destroy()
                empty = self.empty_state = tk.Frame(self.cards, bg=self.BG, pady=56)
                empty.pack(fill="both", expand=True)
                self._empty_signature = filters
                Icon(empty, "check" if not search else "search", size=36, color=self.ACCENT, bg=self.BG).pack(pady=(0, 18))
                tk.Label(empty, text="暂时没有匹配的事项" if search else "给每件事一个下一步", bg=self.BG, fg=self.INK,
                         font=(self.font_family, 15, "bold")).pack()
                tk.Label(empty, text="试试其他关键词或清除筛选。" if search else "更新对话，或添加一件需要跟进的事。", bg=self.BG,
                         fg=self.MUTED, font=(self.font_family, 10)).pack(pady=(10, 18))
                if search or chosen_kind != "全部类型" or chosen_host != "全部来源" or self.show_inactive:
                    ttk.Button(empty, text="清除筛选", command=self._clear_filters).pack()
                elif not self.demo:
                    ttk.Button(empty, text="新建待办", style="Accent.TButton", command=self.new_task).pack()
            self.detail.pack_forget()
        elif not self.detail.winfo_manager():
            self.detail.pack(side="right", fill="y", padx=(20, 0))
        if self.selected_task:
            self._show_detail(by_id[self.selected_task])
        else:
            self._clear_detail()
        if layout_changed or filter_changed:
            # Resolve only geometry work, then retain the same visible task and
            # pixel offset even when content above it grows or is inserted.
            self.cards.update_idletasks()
            if filter_changed:
                target = 0
            elif anchor and anchor[0] in self.task_cards:
                target = self.task_cards[anchor[0]][0].winfo_y() + anchor[1]
            else:
                target = top
            self._restore_canvas_y(self.canvas, target)
            if focused_card in self.task_cards:
                self.task_cards[focused_card][0].focus_set()
        self._refresh_navigation()
        if self.tab == "tasks":
            sources = len({t.get("host") for t in rows if t.get("host") not in (None, "manual")})
            self.summary_var.set("%d 件事项 · %d 个来源 · 进展与下一步，一目了然。" % (len(rows), sources))

    @staticmethod
    def _restore_canvas_y(canvas, top):
        bounds = canvas.bbox("all")
        if bounds and bounds[3] > bounds[1]:
            canvas.configure(scrollregion=bounds)
            canvas.yview_moveto(max(0, top - bounds[1]) / (bounds[3] - bounds[1]))

    def _clear_filters(self):
        self.search_var.set("")
        self.host_var.set("全部来源")
        self._choose_kind("全部类型")

    def _host_label(self, host):
        if host == "mac":
            return "本机"
        if host == "manual":
            return "手动"
        return next((h.get("name") or host for h in self.snapshot.get("hosts", []) if h["id"] == host), host or "未知来源")

    def _badge_colors(self, kind):
        colors = {"review": (self.ACCENT, TOKENS["accent_wash"]), "running": ("#2F7298", "#EAF3F9"),
                  "continue": ("#93672C", "#FAF1E2"), "decision": ("#79539D", "#F2ECF8")}
        return colors.get(kind, (self.MUTED, TOKENS["subtle"]))

    def _badge(self, parent, kind):
        ink, fill = self._badge_colors(kind)
        badge = tk.Label(parent, text=self._kind_label(kind), bg=fill, fg=ink,
                         font=(self.font_family, 9), padx=7, pady=2)
        return badge

    def _task_card(self, task, selected=False):
        card = RoundedPanel(self.cards, fill=self.SURFACE, outline=self.ACCENT if selected else self.BORDER,
                            radius=12, padding=16, takefocus=True, cursor="hand2")
        card.selected = selected
        card.pack(fill="x", pady=(0, 12), padx=(1, 7))
        frame = card.body
        meta = tk.Frame(frame, bg=self.SURFACE)
        meta.pack(fill="x", pady=(0, 9))
        badge = self._badge(meta, task.get("kind"))
        badge.pack(side="left")
        host = tk.Label(meta, text=self._host_label(task.get("host")), bg=self.SURFACE, fg=self.MUTED,
                        font=(self.font_family, 9))
        host.pack(side="right")
        title = tk.Label(frame, text=task.get("title", "未命名待办"), bg=self.SURFACE, fg=self.INK,
                         font=(self.font_family, 12, "bold"), anchor="w", justify="left", wraplength=380)
        title.pack(fill="x", pady=(0, 9))
        progress = tk.Label(frame, text=task.get("progress") or task.get("detail") or "暂无进展记录", bg=self.SURFACE, fg=self.MUTED,
                            font=(self.font_family, 10), anchor="w", justify="left", wraplength=380)
        progress.pack(fill="x", pady=(0, 12))
        next_step = tk.Frame(frame, bg=TOKENS["subtle"], padx=10, pady=9)
        next_step.pack(fill="x")
        Icon(next_step, "arrow", color=self.ACCENT, bg=TOKENS["subtle"]).pack(side="left", anchor="n", padx=(0, 8), pady=2)
        action = tk.Label(next_step, text=task.get("next_action") or "下一步尚未记录", bg=TOKENS["subtle"], fg=self.INK,
                          font=(self.font_family, 10), anchor="w", justify="left", wraplength=340)
        action.pack(side="left", fill="x", expand=True)
        card.labels = {"badge": badge, "host": host, "title": title, "progress": progress, "action": action}
        def resize(event):
            title.configure(wraplength=max(150, event.width))
            progress.configure(wraplength=max(150, event.width))
            action.configure(wraplength=max(130, event.width - 48))
        frame.bind("<Configure>", resize, add=True)
        def select(_event=None):
            self._select_task(task["id"])
        def bind_children(widget):
            widget.bind("<Button-1>", select, add=True)
            for child in widget.winfo_children():
                bind_children(child)
        bind_children(card)
        card.bind("<Return>", select)
        card.bind("<space>", select)
        card.bind("<FocusIn>", lambda _e: card.set_outline(self.ACCENT))
        card.bind("<FocusOut>", lambda _e: card.set_outline(self.ACCENT if card.selected else self.BORDER))
        card.bind("<Enter>", lambda _e: card.set_outline(self.ACCENT))
        card.bind("<Leave>", lambda _e: card.set_outline(self.ACCENT if card.selected else self.BORDER))
        return card

    def _update_task_card(self, card, task):
        ink, fill = self._badge_colors(task.get("kind"))
        card.labels["badge"].configure(text=self._kind_label(task.get("kind")), fg=ink, bg=fill)
        for name, value in (("host", self._host_label(task.get("host"))), ("title", task.get("title", "未命名待办")),
                            ("progress", task.get("progress") or task.get("detail") or "暂无进展记录"),
                            ("action", task.get("next_action") or "下一步尚未记录")):
            card.labels[name].configure(text=value)

    def _select_task(self, task_id):
        self.selected_task = task_id
        self._render_tasks()

    def _clear_detail(self):
        if not hasattr(self, "detail"):
            return
        if self._detail_signature == (None,):
            return
        self._detail_signature = (None,)
        for child in self.detail_content.winfo_children():
            child.destroy()
        tk.Label(self.detail_content, text="选择一条事项查看详情", bg=self.SURFACE, fg=self.MUTED,
                 font=(self.font_family, 10)).pack(padx=8, pady=30)

    def _show_detail(self, task):
        receipt = self._latest_nudge(task)
        signature = (task["id"], tuple(task.get(k) for k in
                     ("kind", "title", "status", "progress", "detail", "next_action", "evidence", "artifact", "conversation_title",
                      "priority", "conversation_id", "thread_id")),
                     self._host_label(task.get("host")), task.get("snoozed_until", 0) > time.time(),
                     tuple((receipt or {}).get(k) for k in ("action_id", "status", "error", "attention")))
        if signature == self._detail_signature:
            return
        same_task = self._detail_signature and self._detail_signature[0] == task["id"]
        top = self.detail_canvas.canvasy(0) if same_task else 0
        focused = self.root.focus_get()
        focused_text = (focused.cget("text") if same_task and isinstance(focused, ttk.Button)
                        and str(focused).startswith(str(self.detail_content) + ".") else None)
        self._detail_signature = signature
        for child in self.detail_content.winfo_children():
            child.destroy()
        pane = self.detail_content
        self._badge(pane, task.get("kind")).pack(anchor="w", pady=(0, 12))
        tk.Label(pane, text=task.get("title", ""), bg=self.SURFACE, fg=self.INK, font=(self.font_family, 16, "bold"),
                 anchor="w", justify="left", wraplength=280).pack(fill="x")
        tk.Label(pane, text=self._host_label(task.get("host")), bg=self.SURFACE, fg=self.MUTED,
                 font=(self.font_family, 9), anchor="w").pack(fill="x", pady=(8, 18))
        buttons = []
        primary_actions = tk.Frame(pane, bg=self.SURFACE)
        primary_actions.pack(fill="x", pady=(0, 14))
        status = task.get("status")
        if status == "open" and task.get("snoozed_until", 0) <= time.time():
            done = ttk.Button(primary_actions, text="完成", style="Accent.TButton", command=lambda: self._act("complete", task))
            done.pack(side="left", fill="x", expand=True)
            buttons.append(done)
        elif status in ("done", "dismissed") or (status == "open" and task.get("snoozed_until", 0) > time.time()):
            reopen = ttk.Button(primary_actions, text="重新打开", style="Accent.TButton", command=lambda: self._act("reopen", task))
            reopen.pack(side="left", fill="x", expand=True)
            buttons.append(reopen)
        if task.get("kind") != "manual":
            open_button = ttk.Button(primary_actions, text="打开对话", command=self.open_conversation)
            open_button.pack(side="left", fill="x", expand=True, padx=(8 if buttons else 0, 0))
            buttons.append(open_button)
        tk.Frame(pane, height=1, bg=self.BORDER).pack(fill="x", pady=(0, 4))
        self._section(pane, "当前进展", task.get("progress") or task.get("detail") or "暂无记录")
        self._section(pane, "下一步", task.get("next_action") or "尚未记录", accent=True)
        self._section(pane, "依据", task.get("evidence") or "暂无依据")
        if task.get("artifact"):
            self._section(pane, "相关产物", task["artifact"])
        if task.get("conversation_title"):
            self._section(pane, "原对话", task["conversation_title"])
        pending_nudge = bool(receipt and receipt.get("status") in ("queued", "sending"))
        if receipt:
            self._section(pane, "最近催办", self._receipt_text(receipt))
        elif status == "conversation_closed":
            self._section(pane, "状态", "对话已结束；请在对话列表中恢复后再恢复待办。")
        elif status == "conversation_archived":
            self._section(pane, "状态", "对话已归档，待办保留在历史记录中。")
        tk.Frame(pane, height=1, bg=self.BORDER).pack(fill="x", pady=(20, 14))
        if status == "open" and task.get("snoozed_until", 0) <= time.time() and task.get("kind") != "manual":
            nudge_button = ttk.Button(pane, text="轻推原对话…", style="Quiet.TButton", command=lambda: self._nudge(task))
            nudge_button.pack(fill="x", pady=(0, 9))
            if pending_nudge:
                nudge_button.configure(state="disabled")
            buttons.append(nudge_button)
        secondary = tk.Frame(pane, bg=self.SURFACE)
        secondary.pack(fill="x")
        labels = [("改标题", lambda: self.rename_task(task))]
        if task.get("kind") == "manual":
            labels.append(("编辑", lambda: self.edit_task(task)))
        if status == "open":
            labels.extend((("稍后提醒…", lambda: self._snooze(task)), ("忽略", lambda: self._act("dismiss", task))))
        for i, (label, command) in enumerate(labels):
            button = ttk.Button(secondary, text=label, style="Quiet.TButton", command=command)
            button.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else 8, 0), pady=(0, 8))
            buttons.append(button)
        secondary.columnconfigure((0, 1), weight=1, uniform="detail")
        if self.demo:
            for button in buttons:
                button.configure(state="disabled")
        self.detail_content.update_idletasks()
        self._restore_canvas_y(self.detail_canvas, top)
        if focused_text:
            for button in buttons:
                if button.cget("text") == focused_text and not button.instate(["disabled"]):
                    button.focus_set()
                    break

    def _section(self, parent, heading, text, accent=False):
        tk.Label(parent, text=heading, bg=self.SURFACE, fg=self.MUTED, font=(self.font_family, 9), anchor="w").pack(fill="x", pady=(18, 6))
        tk.Label(parent, text=text, bg=TOKENS["accent_wash"] if accent else self.SURFACE,
                 fg=self.ACCENT if accent else self.INK, font=(self.font_family, 10), anchor="w", justify="left",
                 wraplength=275, padx=10 if accent else 0, pady=10 if accent else 0).pack(fill="x")

    def _latest_nudge(self, task):
        matches = [n for n in self.snapshot.get("nudges", [])
                   if n.get("conversation_id") == task.get("conversation_id")]
        return max(matches, key=lambda n: n.get("updated_at", n.get("created_at", 0)), default=None)

    @staticmethod
    def _receipt_text(receipt):
        labels = {"queued": "等待发送", "sending": "正在发送", "sent": "已送达", "failed": "发送失败",
                  "unknown": "送达情况未知", "checked": "已核对"}
        lines = [labels.get(receipt.get("status"), receipt.get("status", "状态未知"))]
        if receipt.get("error"):
            lines.append(receipt["error"])
        if receipt.get("attention"):
            lines.append(receipt["attention"])
        return "\n".join(lines)

    def _act(self, action, task):
        self._rpc("act", self._mutation_result, action=action, entity_id=task["id"])

    def _mutation_result(self, response):
        self.request_inflight = False
        if response.get("error"):
            self._error(response["error"])
        elif "snapshot" in response.get("result", {}):
            self.snapshot = response["result"]["snapshot"]
            self._render()
        elif isinstance(response.get("result"), dict):
            self.snapshot = response["result"]
            self._render()

    def _snooze(self, task):
        minutes = simpledialog.askinteger("稍后提醒", "多少分钟后重新显示？（1–10080）", parent=self.root, initialvalue=60, minvalue=1, maxvalue=10080)
        if minutes is not None:
            self._rpc("act", self._mutation_result, action="snooze", entity_id=task["id"], value=minutes)

    def _nudge(self, task, retry_unknown=False):
        existing = [n for n in self.snapshot.get("nudges", [])
                    if n.get("conversation_id") == task.get("conversation_id") and n.get("status") == "unknown"]
        if (existing or retry_unknown) and not messagebox.askyesno(
                "确认送达情况", "请先检查原 Codex 对话，确认上次没有收到催办。现在继续重试吗？", parent=self.root):
            return
        if existing:
            retry_unknown = True
        action_id = str(uuid.uuid4())
        self._rpc("nudge", self._mutation_result, entity_id=task["id"], action_id=action_id, retry_unknown=retry_unknown)

    def new_task(self):
        if self.demo:
            return
        self._task_dialog()

    def edit_task(self, task):
        if task.get("kind") == "manual" and not self.demo:
            self._task_dialog(task)

    def rename_task(self, task):
        title = simpledialog.askstring("改标题", "待办标题", initialvalue=task.get("title", ""), parent=self.root)
        if title and title.strip():
            self._rpc("rename_task", self._mutation_result, entity_id=task["id"], title=title.strip())

    def _task_dialog(self, task=None):
        win = tk.Toplevel(self.root)
        win.title("编辑待办" if task else "新建待办")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.BG)
        box = ttk.Frame(win, padding=18)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="标题").pack(anchor="w")
        title = ttk.Entry(box, width=54)
        title.pack(fill="x", pady=(4, 12))
        title.insert(0, task.get("title", "") if task else "")
        ttk.Label(box, text="备注").pack(anchor="w")
        detail = tk.Text(box, width=54, height=7, wrap="word", relief="solid", bd=1)
        detail.pack(fill="both", expand=True, pady=(4, 12))
        if task:
            detail.insert("1.0", task.get("detail", ""))
        ttk.Label(box, text="优先级").pack(anchor="w")
        priority = tk.IntVar(value=task.get("priority", 2) if task else 2)
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=4)
        for value, label in ((1, "高"), (2, "普通"), (3, "低")):
            ttk.Radiobutton(row, text=label, value=value, variable=priority).pack(side="left", padx=(0, 8))
        def save():
            values = {"title": title.get().strip(), "detail": detail.get("1.0", "end-1c"), "priority": priority.get()}
            if not values["title"]:
                messagebox.showerror("需要标题", "请填写待办标题。", parent=win)
                return
            if task:
                values["entity_id"] = task["id"]
            self._rpc("save_manual", lambda response: (win.destroy(), self._mutation_result(response)), **values)
        ttk.Button(box, text="保存", style="Accent.TButton", command=save).pack(anchor="e")
        title.focus_set()

    def _switch(self, name):
        self.tab = name
        for page in (self.task_page, self.conversation_page, self.summary_page):
            page.pack_forget()
        if name == "tasks":
            self.task_page.pack(fill="both", expand=True)
            self.result_label.pack(anchor="w", pady=(0, 10), before=self.task_page)
            self.task_filters.pack(fill="x", pady=(0, 18), before=self.result_label)
            label = "已完成 / 稍后" if self.show_inactive else self.category_buttons.get(self.kind_var.get(), (None, "所有待办"))[1]
            self.heading_var.set(label)
            if not self.primary_button.winfo_manager():
                self.primary_button.pack(side="right")
            self._render_tasks()
        else:
            self.task_filters.pack_forget()
            self.result_label.pack_forget()
            self.primary_button.pack_forget()
            if name == "summaries":
                self.summary_page.pack(fill="both", expand=True)
                self.heading_var.set("总结")
                self.summary_var.set("按专项整理进展、结果与下一步，并附已有文档和图片。")
                self.summary_page.render()
            else:
                self.conversation_page.pack(fill="both", expand=True)
                self.heading_var.set("所有对话")
                self.summary_var.set("跨设备的原始对话，随时回到上下文。")
                self._render_conversations()
        self._refresh_navigation()

    def _render_conversations(self):
        if not hasattr(self, "conversations"):
            return
        tree = self.conversations
        previous = list(tree.get_children())
        selection, focused = tree.selection(), tree.focus()
        top = tree.yview()[0] * len(previous)
        index = min(int(top), len(previous) - 1) if previous else 0
        anchor = previous[index] if previous else None
        filter_changed = self._conversation_filter != self.conv_inactive_var.get()
        self._conversation_filter = self.conv_inactive_var.get()
        self.conv_map = {}
        for conv in self.snapshot.get("conversations", []):
            if bool(conv.get("closed")) != self.conv_inactive_var.get():
                continue
            title = conv.get("title") or "未命名对话"
            host = self._host_label(conv.get("host"))
            state = "已结束" if conv.get("closed") else {"running": "进行中", "idle": "等待推进", "stopped": "已停止"}.get(conv.get("execution_state"), "待整理")
            iid = conv["id"]
            values = (host, state, self._age(conv.get("updated_at", 0)))
            if not tree.exists(iid):
                tree.insert("", "end", text=title, values=values, iid=iid)
            elif tree.item(iid, "text") != title or tuple(tree.item(iid, "values")) != values:
                tree.item(iid, text=title, values=values)
            self.conv_map[iid] = conv
        for iid in previous:
            if iid not in self.conv_map:
                tree.delete(iid)
        wanted = list(self.conv_map)
        if list(tree.get_children()) != wanted:
            for index_in_tree, iid in enumerate(wanted):
                tree.move(iid, "", index_in_tree)
        if filter_changed or wanted != previous:
            surviving = [iid for iid in selection if tree.exists(iid)]
            if surviving:
                tree.selection_set(surviving)
            if focused and tree.exists(focused):
                tree.focus(focused)
            if not filter_changed and anchor in wanted:
                tree.yview_moveto((wanted.index(anchor) + top - index) / len(wanted))
            elif filter_changed:
                tree.yview_moveto(0)
        self.close_conv_button.configure(text="恢复跟踪" if self.conv_inactive_var.get() else "结束跟踪")

    def _toggle_conversations(self):
        self._render_conversations()

    def _age(self, timestamp):
        if not timestamp:
            return ""
        return time.strftime("%m-%d %H:%M", time.localtime(timestamp))

    def _selected_conversation(self):
        selection = self.conversations.selection()
        return self.conv_map.get(selection[0]) if selection else None

    def toggle_conversation(self):
        conv = self._selected_conversation()
        if conv and not self.demo:
            action = "reopen_conversation" if conv.get("closed") else "close_conversation"
            self._rpc("act", self._mutation_result, action=action, entity_id=conv["id"])

    def open_conversation(self):
        if self.tab == "conversations":
            conv = self._selected_conversation()
            if not conv:
                return
            entity = conv["id"]
        else:
            task = next((x for x in self.snapshot.get("tasks", []) if x["id"] == self.selected_task), None)
            if not task or task.get("kind") == "manual":
                return
            entity = task["id"]
        if not self.demo:
            self._rpc("open_thread", self._action_result, entity_id=entity)

    def _action_result(self, response):
        if response.get("error"):
            self._error(response["error"])
        else:
            result = response.get("result", {})
            self.status_var.set(result.get("detail", "已打开对话"))

    def _toggle_inactive(self):
        self.show_inactive = self.inactive_var.get()
        self._render_tasks()
        self._render_conversations()

    def _wheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        path = str(widget) if widget else ""
        if path.startswith(str(self.sidebar_canvas)):
            canvas = self.sidebar_canvas
        elif self.tab == "tasks" and path.startswith(str(self.detail)):
            canvas = self.detail_canvas
        elif self.tab == "tasks" and path.startswith(str(self.task_list_frame)):
            canvas = self.canvas
        else:
            return
        number = getattr(event, "num", None)
        delta = 1 if number == 5 else -1 if number == 4 else int(-event.delta / 120)
        canvas.yview_scroll(delta, "units")

    def cancel_sync(self):
        if not self.demo:
            self._rpc("cancel_sync", self._mutation_result)

    def toggle_workday(self):
        if self.demo:
            return
        method = "resume_workday" if self.snapshot.get("schedule", {}).get("off_duty") else "finish_workday"
        self._rpc(method, self._mutation_result)

    def manual_sync(self):
        if self.demo:
            return
        self.request_inflight = True
        self._rpc("sync", lambda r: (setattr(self, "request_inflight", False), self._action_result(r)), automatic=False)

    def open_settings(self):
        if self.demo:
            return
        SettingsDialog(self)

    def _settings_saved(self, values):
        self._rpc("settings", self._mutation_result, values=values)

    def _error(self, text):
        self.status_var.set(str(text)[:160])

    def close(self):
        if self.client:
            self.client.close()
        self.root.destroy()

    def _destroyed(self, event):
        if event.widget is not self.root:
            return
        if self.client:
            self.client.close()
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        self.saved = copy.deepcopy(app.snapshot.get("settings", {}))
        self.win = tk.Toplevel(app.root)
        self.win.title("设置")
        self.win.geometry("720x740")
        self.win.minsize(600, 540)
        self.win.configure(bg=app.BG)
        self.win.transient(app.root)
        heading = ttk.Frame(self.win, padding=(24, 20, 24, 12))
        heading.pack(fill="x")
        ttk.Label(heading, text="偏好设置", font=(app.font_family, 18, "bold")).pack(anchor="w")
        ttk.Label(heading, text="连接你的对话，安排适合自己的整理节奏。", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        body = ttk.Frame(self.win, padding=(24, 4, 16, 12))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0, bg=app.BG)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.form = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.form, anchor="nw", tags="form")
        self.form.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure("form", width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        def scroll_form(event):
            number = getattr(event, "num", None)
            delta = 1 if number == 5 else -1 if number == 4 else int(-event.delta / 120)
            self.canvas.yview_scroll(delta, "units")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.win.bind(sequence, scroll_form)
        self.vars = {}
        self._initial_local_paths = tuple(self.saved.get(key, "") for key in ("codex_home", "codex_cli", "codex_app"))
        self._local_connection_succeeded = False
        self._tested_local_paths = None
        self._header("本机 Codex")
        self._entry("codex_home", "Codex 数据目录", self.saved.get("codex_home", ""))
        self._entry("codex_cli", "Codex CLI 路径（留空自动查找）", self.saved.get("codex_cli", ""))
        self._entry("codex_app", "Codex 应用路径（可选）", self.saved.get("codex_app", ""))
        ttk.Button(self.section_body, text="检查本机连接", command=self._test_local).pack(anchor="w", pady=(10, 0))
        self._header("分析模型")
        self._entry("analysis_model", "模型名称", self.saved.get("analysis_model", "gpt-6-luna"))
        effort = tk.StringVar(value=self.saved.get("analysis_effort", "max"))
        self.vars["analysis_effort"] = effort
        self._choice("推理强度", effort, ("minimal", "low", "medium", "high", "xhigh", "max", "ultra"))
        self._header("自动检测")
        self._check("automatic", "启用自动更新", self.saved.get("automatic", True))
        self._check("workdays_only", "仅工作日运行", self.saved.get("workdays_only", True))
        self._check("work_hours_enabled", "限定工作时段", self.saved.get("work_hours_enabled", False))
        self._entry("interval_seconds", "检测间隔（秒，30–3600）", self.saved.get("interval_seconds", 1800))
        for key, label, default in (("work_start_minutes", "开始时间（北京时间，HH:MM）", 540),
                                    ("work_end_minutes", "结束时间（北京时间，HH:MM）", 1080)):
            minutes = self.saved.get(key, default)
            self._entry(key, label, "%02d:%02d" % divmod(minutes, 60))
        self._header("SSH 来源")
        self._check("local_enabled", "启用本机来源", "mac" in self.saved.get("enabled_hosts", ["mac"]))
        self.host_list = ttk.Frame(self.section_body, style="Panel.TFrame")
        self.host_list.pack(fill="x")
        self._render_hosts()
        ttk.Button(self.section_body, text="＋ 添加 SSH 来源", command=lambda: RemoteDialog(self)).pack(anchor="w", pady=(12, 0))
        tk.Frame(self.win, bg=app.BORDER, height=1).pack(fill="x")
        foot = ttk.Frame(self.win, padding=(24, 14, 24, 18))
        foot.pack(fill="x")
        ttk.Button(foot, text="保存更改", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(foot, text="关闭", style="Quiet.TButton", command=self.win.destroy).pack(side="right", padx=8)

    def _header(self, text):
        panel = RoundedPanel(self.form, padding=20)
        panel.pack(fill="x", padx=(0, 8), pady=(0, 14))
        self.section_body = panel.body
        tk.Label(self.section_body, text=text, bg=self.app.SURFACE, fg=self.app.INK,
                 font=(self.app.font_family, 12, "bold")).pack(anchor="w", pady=(0, 6))
        descriptions = {"本机 Codex": "使用已有登录；留空路径可自动查找。", "分析模型": "用于整理目标、进度与下一步。",
                        "自动检测": "只在设置的时间范围内检查变化。", "SSH 来源": "把其他机器上的对话汇集到同一个工作台。"}
        tk.Label(self.section_body, text=descriptions.get(text, ""), bg=self.app.SURFACE, fg=self.app.MUTED,
                 font=(self.app.font_family, 9), anchor="w", justify="left", wraplength=540).pack(fill="x", pady=(0, 10))

    def _entry(self, key, label, value):
        ttk.Label(self.section_body, text=label, style="Panel.TLabel").pack(anchor="w", pady=(8, 5))
        var = tk.StringVar(value=str(value))
        self.vars[key] = var
        ttk.Entry(self.section_body, textvariable=var).pack(fill="x")

    def _check(self, key, label, value):
        var = tk.BooleanVar(value=bool(value))
        self.vars[key] = var
        ttk.Checkbutton(self.section_body, text=label, variable=var, style="Panel.TCheckbutton").pack(anchor="w", pady=3)

    def _choice(self, label, var, values):
        ttk.Label(self.section_body, text=label, style="Panel.TLabel").pack(anchor="w", pady=(8, 5))
        ttk.Combobox(self.section_body, textvariable=var, values=values, state="readonly").pack(fill="x")

    def _render_hosts(self):
        for child in self.host_list.winfo_children():
            child.destroy()
        for profile in self.saved.get("remote_hosts", []):
            row = ttk.Frame(self.host_list, style="Panel.TFrame")
            row.pack(fill="x", pady=6)
            enabled = self.vars.get("host:" + profile["id"])
            if enabled is None:
                enabled = tk.BooleanVar(value=profile["id"] in self.saved.get("enabled_hosts", []))
                self.vars["host:" + profile["id"]] = enabled
            ttk.Checkbutton(row, text="启用", variable=enabled, style="Panel.TCheckbutton").pack(side="left")
            ttk.Label(row, text=profile.get("name", profile["id"]), style="Panel.TLabel").pack(side="left", fill="x", expand=True, padx=6)
            ttk.Button(row, text="测试", command=lambda p=profile: self._test_remote(p)).pack(side="right", padx=2)
            ttk.Button(row, text="编辑", command=lambda p=profile: RemoteDialog(self, p)).pack(side="right", padx=2)
            ttk.Button(row, text="移除", command=lambda p=profile: self._remove(p)).pack(side="right", padx=2)

    def _remove(self, profile):
        if messagebox.askyesno("移除 SSH 来源", "移除 %s？现有历史记录会保留。" % profile.get("name", profile["id"]), parent=self.win):
            self.saved["remote_hosts"] = [x for x in self.saved.get("remote_hosts", []) if x["id"] != profile["id"]]
            self.saved["enabled_hosts"] = [x for x in self.saved.get("enabled_hosts", []) if x != profile["id"]]
            self._render_hosts()

    def _test_local(self):
        try:
            values = self._values()
        except ValueError as exc:
            messagebox.showerror("设置无效", str(exc), parent=self.win)
            return
        self._checking_local_paths = tuple(str(values[key]).strip() for key in ("codex_home", "codex_cli", "codex_app"))
        values["connection_setup_complete"] = False
        # The service checks its persisted connection settings. Save edited paths
        # first, while preserving an incomplete gate until this local check succeeds.
        self.app._rpc("settings", lambda r: self._after_local_settings(r), values=values)

    def _after_local_settings(self, response):
        if response.get("error"):
            messagebox.showerror("连接设置失败", response["error"], parent=self.win)
            return
        self.app.snapshot = response.get("result", self.app.snapshot)
        self.app._rpc("check_connection", lambda r: self._checked(r, local=True))

    def _test_remote(self, profile):
        self.app._rpc("check_connection", lambda r: self._checked(r, local=False), profile=profile)

    def _checked(self, response, local):
        if response.get("error"):
            if local:
                self._local_check_failed()
            messagebox.showerror("连接测试失败", response["error"], parent=self.win)
            return
        result = response.get("result", {})
        if result.get("ok"):
            if local:
                checked_paths = getattr(self, "_checking_local_paths", None)
                current_paths = tuple(str(self.vars[key].get()).strip() for key in ("codex_home", "codex_cli", "codex_app"))
                if checked_paths is not None and current_paths != checked_paths:
                    self._local_check_failed()
                    messagebox.showerror("请重新检查连接", "检查期间本机路径已更改，请保存后重新检查。", parent=self.win)
                    return
                self._local_connection_succeeded = True
                self._tested_local_paths = tuple(str(self.vars[key].get()).strip() for key in ("codex_home", "codex_cli", "codex_app"))
                self.saved["connection_setup_complete"] = True
                self.app._rpc("settings", self.app._mutation_result, values={"connection_setup_complete": True})
            messagebox.showinfo("连接可用", result.get("detail", "连接测试通过。"), parent=self.win)
        else:
            if local:
                self._local_check_failed()
            messagebox.showerror("连接测试失败", result.get("detail", "连接检查未通过。"), parent=self.win)

    def _local_check_failed(self):
        self._local_connection_succeeded = False
        self._tested_local_paths = None
        self.saved["connection_setup_complete"] = False
        self.app._rpc("settings", self.app._mutation_result, values={"connection_setup_complete": False})

    def _values(self):
        values = {}
        for key, var in self.vars.items():
            if key.startswith("host:"):
                continue
            value = var.get()
            if key in ("work_start_minutes", "work_end_minutes"):
                try:
                    hour, minute = map(int, str(value).split(":"))
                    if not 0 <= hour < 24 or not 0 <= minute < 60:
                        raise ValueError()
                    value = hour * 60 + minute
                except (ValueError, TypeError):
                    raise ValueError("开始和结束时间请填写 HH:MM，例如 09:00")
            elif key == "interval_seconds":
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    raise ValueError("检测间隔请填写整数秒数")
            values[key] = value
        remotes = copy.deepcopy(self.saved.get("remote_hosts", []))
        enabled = ["mac"] if self.vars.get("local_enabled", tk.BooleanVar(value=True)).get() else []
        for item in remotes:
            var = self.vars.get("host:" + item["id"])
            if var and var.get():
                enabled.append(item["id"])
        values["remote_hosts"] = remotes
        values["enabled_hosts"] = enabled
        current_paths = tuple(str(self.vars[key].get()).strip() for key in ("codex_home", "codex_cli", "codex_app"))
        local_paths_changed = current_paths != self._initial_local_paths
        local_test_valid = (self._local_connection_succeeded and current_paths == self._tested_local_paths)
        if local_paths_changed and not local_test_valid:
            values["connection_setup_complete"] = False
        elif local_test_valid:
            values["connection_setup_complete"] = True
        return values

    def _save(self):
        try:
            values = self._values()
        except ValueError as exc:
            messagebox.showerror("设置无效", str(exc), parent=self.win)
            return
        def saved(response):
            if response.get("error"):
                messagebox.showerror("设置未保存", response["error"], parent=self.win)
                return
            self.app._mutation_result(response)
            self.win.destroy()
        self.app._rpc("settings", saved, values=values)


class RemoteDialog:
    FIELDS = (("id", "连接标识（如 build-server）"), ("name", "显示名称"), ("hostname", "主机名或 IP"),
              ("user", "SSH 用户"), ("port", "SSH 端口（可留空）"), ("identity_file", "私钥路径（可留空）"),
              ("codex_home", "远程 Codex 数据目录（可留空）"), ("python", "远程 Python（可留空）"),
              ("host_id", "Codex 主机 ID（可选）"))

    def __init__(self, settings_dialog, profile=None):
        self.settings = settings_dialog
        self.profile = profile
        self.win = tk.Toplevel(settings_dialog.win)
        self.win.title("编辑 SSH 来源" if profile else "添加 SSH 来源")
        box = ttk.Frame(self.win, padding=16)
        box.pack(fill="both", expand=True)
        self.vars = {}
        for key, label in self.FIELDS:
            ttk.Label(box, text=label).pack(anchor="w", pady=(5, 2))
            var = tk.StringVar(value=str((profile or {}).get(key, "")))
            self.vars[key] = var
            ttk.Entry(box, textvariable=var, width=54).pack(fill="x")
        ttk.Button(box, text="保存连接", command=self._save).pack(anchor="e", pady=(12, 0))

    def _save(self):
        profile = {key: var.get().strip() for key, var in self.vars.items()}
        try:
            import connections
            profile = connections.normalize_remote(profile)
            old_id = self.profile.get("id") if self.profile else None
            remotes = [x for x in self.settings.saved.get("remote_hosts", []) if x["id"] != old_id and x["id"] != profile["id"]]
            remotes.append(profile)
            self.settings.saved["remote_hosts"] = remotes
            self.settings.saved["enabled_hosts"] = list(dict.fromkeys(self.settings.saved.get("enabled_hosts", []) + [profile["id"]]))
            self.settings.vars["host:" + profile["id"]] = tk.BooleanVar(master=self.settings.win, value=True)
            self.settings._render_hosts()
            self.destroy()
        except Exception as exc:
            messagebox.showerror("连接设置无效", str(exc), parent=self.win)

    def destroy(self):
        self.win.destroy()


def main(argv=None):
    app = CoindexApp.from_args(argv)
    app.root.mainloop()
    if getattr(app, "smoke_error", ""):
        print(app.smoke_error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
