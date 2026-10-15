"""Summary workspace and guided forms, using the shared private service RPCs."""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from .design import RoundedPanel
except ImportError:
    from design import RoundedPanel

BEIJING = dt.timezone(dt.timedelta(hours=8))
STATUS_LABELS = {"queued": "排队中", "running": "生成中", "completed": "已完成",
                 "failed": "生成失败", "cancelled": "已中止"}
DAY_CHOICES = {"今天": 1, "近三天": 3, "近一周": 7}
FREQUENCIES = {"每天": "daily", "每周": "weekly", "每隔几小时": "interval"}
SCOPES = {"正在进行的全部待办": "active", "最近几天的全部待办": "period", "全部已保存任务（含完成、归档）": "all"}
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def today_string():
    return dt.datetime.now(BEIJING).date().isoformat()


def range_request(scope, preset, start_date, end_date):
    """Validate the form independently of transport and GUI state."""
    if scope in ("active", "all"):
        return {"scope": scope}
    if preset in DAY_CHOICES:
        return {"scope": "period", "days": DAY_CHOICES[preset]}
    if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) for value in (start_date, end_date)):
        raise ValueError("请使用 YYYY-MM-DD 格式，例如 2026-10-15。")
    try:
        start, end = dt.date.fromisoformat(start_date.strip()), dt.date.fromisoformat(end_date.strip())
    except ValueError as exc:
        raise ValueError("请使用 YYYY-MM-DD 格式，例如 2026-10-15。") from exc
    if start > end:
        raise ValueError("开始日期不能晚于结束日期。")
    if end > dt.date.fromisoformat(today_string()):
        raise ValueError("结束日期不能晚于今天（北京时间）。")
    return {"scope": "period", "start_date": start.isoformat(), "end_date": end.isoformat()}


def format_time(value):
    return dt.datetime.fromtimestamp(value, BEIJING).strftime("%m-%d %H:%M") if value else ""


def dialog_content(win, app):
    """Keep actions reachable on short displays without rebuilding form widgets."""
    actions = ttk.Frame(win, padding=(24, 14, 24, 18))
    actions.pack(side="bottom", fill="x")
    tk.Frame(win, height=1, bg=app.BORDER).pack(side="bottom", fill="x")
    host = ttk.Frame(win, padding=(24, 20, 16, 8))
    host.pack(fill="both", expand=True)
    canvas = tk.Canvas(host, highlightthickness=0, bg=app.BG)
    scroll = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    body = ttk.Frame(canvas, padding=(0, 0, 8, 0))
    form = canvas.create_window((0, 0), window=body, anchor="nw")
    body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(form, width=event.width))
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    def wheel(event):
        number = getattr(event, "num", None)
        delta = 1 if number == 5 else -1 if number == 4 else int(-event.delta / 120)
        canvas.yview_scroll(delta, "units")
    for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        win.bind(event, wheel, add=True)
    return body, actions, canvas


class SummaryPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.selected_id = None
        self.rows = {}
        self.cache = {}
        self.inflight = set()
        self.shown_signature = None
        self.current_content = ""
        self.current_sources = []
        self.wizard = None
        self.schedule_dialog = None
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        self.new_button = ttk.Button(bar, text="＋ 新建总结", style="Accent.TButton", command=self.new_summary)
        self.new_button.pack(side="left")
        self.schedule_button = ttk.Button(bar, text="自动总结…", command=self.open_schedule)
        self.schedule_button.pack(side="left", padx=8)
        self.schedule_text = tk.StringVar(value="自动总结未开启")
        ttk.Label(self, textvariable=self.schedule_text, style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=(0, 16))
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        history = ttk.Frame(panes)
        panes.add(history, weight=1)
        ttk.Label(history, text="总结记录 · 最近 100 条", style="Caption.TLabel").pack(anchor="w", pady=(0, 8))
        history_body = ttk.Frame(history)
        history_body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(history_body, columns=("state",), show="tree headings", selectmode="browse", height=12)
        self.tree.heading("#0", text="范围 / 时间", anchor="w")
        self.tree.heading("state", text="状态", anchor="w")
        self.tree.column("#0", width=185, minwidth=110)
        self.tree.column("state", width=70, minwidth=65, stretch=False)
        scroll = ttk.Scrollbar(history_body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        detail = tk.Frame(panes, bg=app.SURFACE, padx=20, pady=20,
                          highlightthickness=1, highlightbackground=app.BORDER)
        panes.add(detail, weight=3)
        self.title = tk.StringVar(value="回顾进展，看清下一步")
        self.subtitle = tk.StringVar(value="每个目标用四句话：背景、问题、实验结果和结论。")
        title_label = tk.Label(detail, textvariable=self.title, bg=app.SURFACE, fg=app.INK,
                              font=(app.font_family, 14, "bold"), anchor="w", justify="left", wraplength=430)
        title_label.pack(fill="x")
        title_label.bind("<Configure>", lambda event: title_label.configure(wraplength=max(180, event.width)))
        subtitle_label = tk.Label(detail, textvariable=self.subtitle, bg=app.SURFACE, fg=app.MUTED, anchor="w", justify="left",
                                  wraplength=430, font=(app.font_family, 9))
        subtitle_label.pack(fill="x", pady=(7, 14))
        subtitle_label.bind("<Configure>", lambda event: subtitle_label.configure(wraplength=max(180, event.width)))
        actions = tk.Frame(detail, bg=app.SURFACE)
        actions.pack(side="bottom", fill="x", pady=(16, 0))
        text_frame = tk.Frame(detail, bg=app.SURFACE)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", state="disabled", relief="flat", borderwidth=0,
                            bg=app.SURFACE, fg=app.INK, selectbackground="#DDE0FA", selectforeground=app.INK,
                            font=(app.font_family, 11), spacing1=4, spacing3=6, width=35, height=10,
                            padx=0, pady=3)
        self.text.tag_configure("heading", font=(app.font_family, 13, "bold"), foreground=app.ACCENT,
                                spacing1=14, spacing3=8)
        self.text.tag_configure("bold", font=(app.font_family, 11, "bold"))
        detail_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=detail_scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self.copy_button = ttk.Button(actions, text="复制 Markdown", width=0, command=self.copy_content, state="disabled")
        self.copy_button.pack(side="left")
        self.export_button = ttk.Button(actions, text="导出…", width=0, command=self.export_content, state="disabled")
        self.export_button.pack(side="left", padx=8)
        self.audit_button = ttk.Button(actions, text="筛选依据…", width=0, command=self.show_audit)
        self.cancel_button = ttk.Button(actions, text="中止生成", style="Danger.TButton", command=self.cancel)
        self._set_text("点击「新建总结」，选择正在进行的全部待办，或回顾某个时间段。\n\n总结会保存在本机，方便随时查阅和导出。")
        if app.demo:
            self.new_button.configure(state="disabled")
            self.schedule_button.configure(state="disabled")

    @staticmethod
    def _signature(row):
        return tuple(row.get(key) for key in ("id", "status", "finished_at", "task_count", "error", "excluded_count", "uncertain_count"))

    def render(self):
        schedule = self.app.snapshot.get("summary_schedule", {})
        text = schedule.get("description") or ("自动总结已开启" if schedule.get("enabled") else "自动总结未开启")
        if schedule.get("enabled") and schedule.get("next_at"):
            text += " · 下次 " + format_time(schedule["next_at"]) + "（北京时间）"
        if self.app.snapshot.get("schedule", {}).get("off_duty") and schedule.get("enabled"):
            text += " · 已下班，自动总结暂停"
        self.schedule_text.set(text)
        rows = {row["id"]: row for row in self.app.snapshot.get("summaries", [])}
        previous = list(self.tree.get_children())
        top = self.tree.yview()[0]
        anchor_index = min(int(top * len(previous)), len(previous) - 1) if previous else 0
        anchor = previous[anchor_index] if previous else None
        for iid, row in rows.items():
            label = row.get("title") or "待办总结"
            label += "\n" + format_time(row.get("created_at", 0))
            values = (STATUS_LABELS.get(row.get("status"), row.get("status", "")),)
            if not self.tree.exists(iid):
                self.tree.insert("", "end", iid=iid, text=label, values=values)
            elif self.tree.item(iid, "text") != label or tuple(self.tree.item(iid, "values")) != values:
                self.tree.item(iid, text=label, values=values)
        for iid in previous:
            if iid not in rows:
                self.tree.delete(iid)
                self.cache.pop(iid, None)
        wanted = list(rows)
        self.rows = rows
        if previous != wanted:
            for index, iid in enumerate(wanted):
                self.tree.move(iid, "", index)
            if anchor in wanted:
                self.tree.yview_moveto((wanted.index(anchor) + top * len(previous) - anchor_index) / len(wanted))
        if self.selected_id not in rows:
            self.selected_id = wanted[0] if wanted else None
        if self.selected_id and tuple(self.tree.selection()) != (self.selected_id,):
            self.tree.selection_set(self.selected_id)
        if self.app.tab == "summaries":
            self._load_selected()

    def select(self, summary_id):
        if summary_id in self.rows:
            self.selected_id = summary_id
            self.tree.selection_set(summary_id)
            self.tree.see(summary_id)
            self._load_selected()

    def _selection_changed(self, _event=None):
        selected = self.tree.selection()
        if selected:
            self.selected_id = selected[0]
            self._load_selected()

    def _load_selected(self):
        row = self.rows.get(self.selected_id)
        if not row:
            return
        signature = self._signature(row)
        cached = self.cache.get(row["id"])
        if cached and cached[0] == signature:
            self._show(cached[1])
            return
        self._show(row)
        request_key = (row["id"], signature)
        if request_key in self.inflight or self.app.demo:
            return
        self.inflight.add(request_key)
        def loaded(response):
            self.inflight.discard(request_key)
            if not self.winfo_exists():
                return
            current = self.rows.get(row["id"])
            # A queued response must never overwrite a newer completed result.
            if not current or self._signature(current) != signature:
                return
            if response.get("error"):
                if self.selected_id == row["id"]:
                    self._set_text("读取总结失败：" + str(response["error"]))
                return
            detail = response.get("result", {})
            self.cache[row["id"]] = (signature, detail)
            if self.selected_id == row["id"]:
                self._show(detail)
        if self.app._rpc("summary_detail", loaded, summary_id=row["id"]) is None:
            self.inflight.discard(request_key)

    def _show(self, detail):
        source_labels = tuple((source.get("id"), source.get("title"), source.get("relevance"), source.get("relevance_reason"))
                              for source in detail.get("sources", []))
        signature = (self._signature(detail), detail.get("content", ""), source_labels)
        if signature == self.shown_signature:
            return
        self.shown_signature = signature
        self.title.set(detail.get("title") or "待办总结")
        state = detail.get("status", "queued")
        source = "自动" if detail.get("origin") == "automatic" else "手动"
        self.subtitle.set("%s · %s生成 · %d 件候选待办 · %s（北京时间）" %
                          (STATUS_LABELS.get(state, state), source, detail.get("task_count", 0),
                           format_time(detail.get("created_at", 0))))
        self.current_content = detail.get("content", "")
        self.current_sources = detail.get("sources", [])
        if detail.get("work_only") and self.current_sources:
            self.audit_button.pack(side="left")
        else:
            self.audit_button.pack_forget()
        if detail.get("work_only") and state == "completed":
            self.subtitle.set(self.subtitle.get() + "\n已排除 %d 件个人项目 · %d 件待确认" %
                              (detail.get("excluded_count", 0), detail.get("uncertain_count", 0)))
        fallback = {"queued": "已加入生成队列，可以继续处理其他待办。", "running": "正在整理背景、问题、实验结果和结论，可以离开此页面。",
                    "cancelled": "本次总结已中止。可以重新选择范围生成。", "failed": "生成失败：" + str(detail.get("error") or "请检查模型连接后重试。"),
                    "completed": "正在读取总结…"}
        self._set_text(self.current_content or fallback.get(state, "正在读取总结…"))
        available = "normal" if self.current_content else "disabled"
        self.copy_button.configure(state=available)
        self.export_button.configure(state=available)
        if state in ("queued", "running") and not self.app.demo:
            self.cancel_button.pack(side="right")
        else:
            self.cancel_button.pack_forget()

    def _set_text(self, content):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in content.splitlines():
            if re.match(r"^#{1,6} ", line):
                self.text.insert("end", re.sub(r"^#{1,6} ", "", line) + "\n", "heading")
            else:
                for index, part in enumerate(re.split(r"\*\*(.*?)\*\*", line)):
                    self.text.insert("end", part, "bold" if index % 2 else ())
                self.text.insert("end", "\n")
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    def new_summary(self):
        if self.app.demo:
            return
        if self.wizard and self.wizard.win.winfo_exists():
            self.wizard.win.lift()
        else:
            self.wizard = SummaryWizard(self)

    def open_schedule(self):
        if self.app.demo:
            return
        if self.schedule_dialog and self.schedule_dialog.win.winfo_exists():
            self.schedule_dialog.win.lift()
        else:
            self.schedule_dialog = SummaryScheduleDialog(self)

    def cancel(self):
        if self.selected_id and self.rows.get(self.selected_id, {}).get("status") in ("queued", "running"):
            self.app._rpc("summary_cancel", self.app._mutation_result, summary_id=self.selected_id)

    def show_audit(self):
        if not self.current_sources:
            return
        win = tk.Toplevel(self.app.root)
        win.title("工作范围筛选依据")
        win.geometry("640x500")
        win.transient(self.app.root)
        win.configure(bg=self.app.BG)
        body = ttk.Frame(win, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="只影响这份总结，原始待办保持原样。", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        text = tk.Text(body, wrap="word", font=(self.app.font_family, 11), bg=self.app.SURFACE,
                       fg=self.app.INK, relief="flat", padx=14, pady=14)
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        labels = {"work": "工作事项 · 已纳入", "non_work": "个人项目 · 已排除", "uncertain": "范围待确认 · 已保留"}
        for source in self.current_sources:
            text.insert("end", "%s\n%s\n%s\n\n" %
                        (source.get("title", "未命名待办") + ("（已归档）" if source.get("conversation_archived") else ""), labels.get(source.get("relevance"), "未分类"),
                         source.get("relevance_reason") or "未提供分类依据"))
        text.configure(state="disabled")

    def copy_content(self):
        if self.current_content:
            self.clipboard_clear()
            self.clipboard_append(self.current_content)
            self.app.status_var.set("总结 Markdown 已复制")

    def export_content(self):
        if not self.current_content:
            return
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", self.title.get())[:100] or "coindex-summary"
        destination = filedialog.asksaveasfilename(parent=self.app.root, title="导出总结", initialfile=name + ".md",
                                                   defaultextension=".md", filetypes=[("Markdown", "*.md")])
        if destination:
            try:
                pathlib.Path(destination).write_text(self.current_content + "\n", encoding="utf-8")
                self.app.status_var.set("总结已导出")
            except OSError as error:
                messagebox.showerror("导出失败", str(error), parent=self.app.root)


class SummaryWizard:
    def __init__(self, page):
        self.page, self.app = page, page.app
        self.win = tk.Toplevel(self.app.root)
        self.win.title("新建总结")
        self.win.geometry("650x720")
        self.win.minsize(600, 520)
        self.win.transient(self.app.root)
        self.win.configure(bg=self.app.BG)
        self.scope = tk.StringVar(value="active")
        self.preset = tk.StringVar(value="今天")
        self.start = tk.StringVar(value=today_string())
        self.end = tk.StringVar(value=today_string())
        self.work_only = tk.BooleanVar(value=False)
        self.work_context = tk.StringVar()
        self.preview_text = tk.StringVar(value="正在确认总结范围…")
        self.preview = None
        self.preview_request = None
        self.preview_serial = 0
        self.timer = None
        self.submitting = False
        body, actions, self.canvas = dialog_content(self.win, self.app)
        ttk.Label(body, text="你想总结什么？", font=(self.app.font_family, 18, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text="每个目标输出：问题背景、具体问题、目前实验结果、实验结论。", style="Muted.TLabel").pack(anchor="w", pady=(0, 20))
        ttk.Radiobutton(body, text="正在进行的全部待办", variable=self.scope, value="active").pack(anchor="w", pady=4)
        ttk.Label(body, text="包括稍后处理的待办和手动待办。", style="Muted.TLabel").pack(anchor="w", padx=22, pady=(0, 10))
        ttk.Radiobutton(body, text="全部已保存任务（含完成、归档）", variable=self.scope, value="all").pack(anchor="w", pady=4)
        ttk.Label(body, text="包括已完成、已结束及归档对话的历史任务。", style="Muted.TLabel").pack(anchor="w", padx=22, pady=(0, 10))
        ttk.Radiobutton(body, text="某个时间段的全部待办", variable=self.scope, value="period").pack(anchor="w", pady=4)
        ttk.Label(body, text="包括该时段新建、更新或完成的待办，以及已归档事项。", style="Muted.TLabel").pack(anchor="w", padx=22)
        self.period_fields = ttk.Frame(body)
        self.period_fields.pack(fill="x", padx=(22, 0), pady=(12, 0))
        self.preset_box = ttk.Combobox(self.period_fields, textvariable=self.preset,
                                      values=(*DAY_CHOICES, "自定义日期"), state="readonly", width=16)
        self.preset_box.pack(anchor="w")
        dates = ttk.Frame(self.period_fields)
        dates.pack(fill="x", pady=(10, 0))
        self.start_entry = ttk.Entry(dates, textvariable=self.start, width=15)
        self.start_entry.pack(side="left")
        ttk.Label(dates, text=" 至 ").pack(side="left", padx=8)
        self.end_entry = ttk.Entry(dates, textvariable=self.end, width=15)
        self.end_entry.pack(side="left")
        ttk.Label(body, text="按北京时间计算，包含起止日期当天。\n总结基于当前保存的进展，不还原过去某一时刻的状态。",
                  style="Muted.TLabel", wraplength=530).pack(anchor="w", pady=(16, 16))
        ttk.Checkbutton(body, text="仅总结工作事项（排除个人开源项目和自制应用）", variable=self.work_only).pack(anchor="w", pady=(0, 6))
        ttk.Label(body, text="工作项目 / 关键词或排除提示（可选，供模型判断）", style="Muted.TLabel").pack(anchor="w", pady=(0, 5))
        self.context_entry = ttk.Entry(body, textvariable=self.work_context)
        self.context_entry.pack(fill="x", pady=(0, 6))
        ttk.Label(body, text="无法确定的事项会保留并标注待确认，可在结果中查看筛选依据。", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        preview_panel = RoundedPanel(body, padding=16)
        preview_panel.pack(fill="x", pady=(0, 14))
        self.preview_label = tk.Label(preview_panel.body, textvariable=self.preview_text, bg=self.app.SURFACE, fg=self.app.INK,
                                     anchor="w", justify="left", wraplength=490, font=(self.app.font_family, 10))
        self.preview_label.pack(fill="x")
        self.preview_label.bind("<Configure>", lambda event: self.preview_label.configure(wraplength=max(200, event.width)))
        self.generate_button = ttk.Button(actions, text="生成总结", style="Accent.TButton", command=self.generate, state="disabled")
        self.generate_button.pack(side="right")
        ttk.Button(actions, text="取消", command=self.win.destroy).pack(side="right", padx=8)
        for var in (self.scope, self.preset, self.start, self.end, self.work_only, self.work_context):
            var.trace_add("write", self._changed)
        self.win.bind("<Destroy>", self._destroyed, add=True)
        self._changed()

    def _destroyed(self, event):
        if event.widget is self.win and self.timer:
            self.win.after_cancel(self.timer)
            self.timer = None

    def _request(self):
        values = range_request(self.scope.get(), self.preset.get(), self.start.get(), self.end.get())
        values.update(work_only=self.work_only.get(), work_context=self.work_context.get().strip())
        return values

    def _changed(self, *_args):
        if self.submitting:
            return
        self.preview_serial += 1
        self.preview = None
        self.generate_button.configure(state="disabled")
        period = self.scope.get() == "period"
        custom = period and self.preset.get() == "自定义日期"
        self.preset_box.configure(state="readonly" if period else "disabled")
        self.context_entry.configure(state="normal" if self.work_only.get() else "disabled")
        for entry in (self.start_entry, self.end_entry):
            entry.configure(state="normal" if custom else "disabled")
        if self.timer:
            self.win.after_cancel(self.timer)
        try:
            request = self._request()
        except ValueError as error:
            self.preview_text.set(str(error))
            return
        self.preview_text.set("正在确认总结范围…")
        serial = self.preview_serial
        self.timer = self.win.after(220, lambda: self._preview(request, serial))

    def _preview(self, request, serial):
        self.timer = None
        if not self.win.winfo_exists():
            return
        def done(response):
            if not self.win.winfo_exists() or serial != self.preview_serial:
                return
            if response.get("error"):
                self.preview_text.set("无法预览：" + str(response["error"]))
                return
            self.preview = response.get("result", {})
            self.preview_request = request
            count = self.preview.get("task_count", 0)
            dates = "正在进行的全部待办"
            if request["scope"] == "all":
                dates = "全部已保存任务（含完成、归档）"
            if request["scope"] == "period":
                dates = "%s 至 %s" % (self.preview.get("start_date", ""), self.preview.get("end_date", ""))
            qualifier = "候选待办（工作范围将在生成时筛选）" if request.get("work_only") else "待办"
            self.preview_text.set("%s\n共 %d 件%s%s" % (dates, count, qualifier, "，可以开始总结。" if count else "，请调整范围。"))
            if self.preview.get("archived_count", 0):
                self.preview_text.set(self.preview_text.get() + "\n已包含 %d 条归档对话的任务。" % self.preview["archived_count"])
            self.generate_button.configure(state="normal" if count else "disabled")
        if self.app._rpc("summary_preview", done, **request) is None:
            self.preview_text.set("服务暂时不可用，请稍后重新选择范围。")

    def generate(self):
        if self.submitting or not self.preview or not self.preview.get("task_count"):
            return
        try:
            request = self._request()
        except ValueError:
            return
        if request != self.preview_request:
            self._changed()
            return
        self.submitting = True
        self.generate_button.configure(state="disabled", text="正在提交…")
        def generated(response):
            if response.get("error"):
                if self.win.winfo_exists():
                    self.submitting = False
                    self.generate_button.configure(state="normal", text="生成总结")
                    self.preview_text.set("提交失败：" + str(response["error"]))
                return
            result = response.get("result", {})
            self.app._mutation_result(response)
            self.page.select(result.get("summary_id"))
            if self.win.winfo_exists():
                self.win.destroy()
        if self.app._rpc("summary_generate", generated, **request) is None:
            self.submitting = False
            if self.win.winfo_exists():
                self.generate_button.configure(state="normal", text="生成总结")
                self.preview_text.set("提交未成功，请检查服务状态。")


class SummaryScheduleDialog:
    def __init__(self, page):
        self.page, self.app = page, page.app
        settings = self.app.snapshot.get("summary_schedule", {})
        self.win = tk.Toplevel(self.app.root)
        self.win.title("自动总结")
        self.win.geometry("640x700")
        self.win.minsize(600, 520)
        self.win.transient(self.app.root)
        self.win.configure(bg=self.app.BG)
        self.enabled = tk.BooleanVar(value=settings.get("enabled", False))
        self.frequency = tk.StringVar(value=next((label for label, key in FREQUENCIES.items()
                                                 if key == settings.get("frequency", "daily")), "每天"))
        self.time = tk.StringVar(value="%02d:%02d" % divmod(settings.get("time_minutes", 1080), 60))
        self.weekday = tk.StringVar(value=WEEKDAYS[max(0, min(6, settings.get("weekday", 0)))])
        self.interval = tk.StringVar(value=str(settings.get("interval_hours", 24)))
        self.scope = tk.StringVar(value=next((label for label, key in SCOPES.items() if key == settings.get("scope")), "最近几天的全部待办"))
        self.days = tk.StringVar(value=str(settings.get("days", 1)))
        self.workdays = tk.BooleanVar(value=settings.get("workdays_only", False))
        self.work_only = tk.BooleanVar(value=settings.get("work_only", False))
        self.work_context = tk.StringVar(value=settings.get("work_context", ""))
        self.error = tk.StringVar()
        self.saving = False
        body, actions, self.canvas = dialog_content(self.win, self.app)
        ttk.Label(body, text="按你的节奏回顾工作", font=(self.app.font_family, 16, "bold")).pack(anchor="w", pady=(0, 16))
        ttk.Checkbutton(body, text="启用自动总结", variable=self.enabled).pack(anchor="w", pady=(0, 12))
        fields_panel = RoundedPanel(body, padding=16)
        fields_panel.pack(fill="x")
        self.fields = fields_panel.body
        self._field("频率", self.frequency, tuple(FREQUENCIES))
        self.time_entry = self._field("生成时间（北京时间 HH:MM）", self.time)
        self.weekday_box = self._field("每周哪一天", self.weekday, WEEKDAYS)
        self.interval_entry = self._field("间隔小时数（1–168）", self.interval)
        self._field("总结范围", self.scope, tuple(SCOPES))
        self.days_entry = self._field("回顾天数（1–366，含今天）", self.days)
        ttk.Checkbutton(body, text="只在中国大陆法定工作日生成（含调休）", variable=self.workdays).pack(anchor="w", pady=14)
        ttk.Checkbutton(body, text="仅总结工作事项（排除个人开源项目和自制应用）", variable=self.work_only).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text="工作项目 / 关键词或排除提示（可选）", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.context_entry = ttk.Entry(body, textvariable=self.work_context)
        self.context_entry.pack(fill="x", pady=(0, 12))
        ttk.Label(body, text="请保持 coindex 运行；休眠或退出期间不生成。\n「下班」也会暂停自动总结，恢复后继续按计划执行。",
                  style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(0, 10))
        tk.Label(body, textvariable=self.error, bg=self.app.BG, fg="#A34444", justify="left", wraplength=510).pack(fill="x")
        self.save_button = ttk.Button(actions, text="保存设置", style="Accent.TButton", command=self.save)
        self.save_button.pack(side="right")
        ttk.Button(actions, text="取消", command=self.win.destroy).pack(side="right", padx=8)
        for var in (self.frequency, self.scope, self.work_only):
            var.trace_add("write", self._availability)
        self._availability()

    def _field(self, label, var, choices=None):
        row = ttk.Frame(self.fields, style="Panel.TFrame")
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=label, width=27, style="Panel.TLabel").pack(side="left")
        widget = (ttk.Combobox(row, textvariable=var, values=choices, state="readonly", width=20)
                  if choices else ttk.Entry(row, textvariable=var, width=22))
        widget.pack(side="right", fill="x", expand=True)
        return widget

    def _availability(self, *_args):
        frequency = FREQUENCIES[self.frequency.get()]
        self.time_entry.configure(state="disabled" if frequency == "interval" else "normal")
        self.weekday_box.configure(state="readonly" if frequency == "weekly" else "disabled")
        self.interval_entry.configure(state="normal" if frequency == "interval" else "disabled")
        self.context_entry.configure(state="normal" if self.work_only.get() else "disabled")
        self.days_entry.configure(state="normal" if self.scope.get() == "最近几天的全部待办" else "disabled")

    def values(self):
        frequency = FREQUENCIES[self.frequency.get()]
        try:
            hours, minutes = (int(part) for part in self.time.get().split(":"))
            if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
                raise ValueError()
            interval = int(self.interval.get())
            days = int(self.days.get())
            if not 1 <= interval <= 168 or not 1 <= days <= 366:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("请检查时间（00:00–23:59）、间隔（1–168 小时）和天数（1–366）。") from exc
        return {"enabled": self.enabled.get(), "frequency": frequency, "time_minutes": hours * 60 + minutes,
                "weekday": WEEKDAYS.index(self.weekday.get()), "interval_hours": interval,
                "scope": SCOPES[self.scope.get()], "days": days, "workdays_only": self.workdays.get(),
                "work_only": self.work_only.get(), "work_context": self.work_context.get().strip()}

    def save(self):
        if self.saving:
            return
        try:
            values = self.values()
        except ValueError as error:
            self.error.set(str(error))
            return
        self.saving = True
        self.save_button.configure(state="disabled")
        def saved(response):
            if response.get("error"):
                if self.win.winfo_exists():
                    self.saving = False
                    self.save_button.configure(state="normal")
                    self.error.set(str(response["error"]))
                return
            self.app._mutation_result(response)
            if self.win.winfo_exists():
                self.win.destroy()
        if self.app._rpc("summary_settings", saved, values=values) is None:
            self.saving = False
            if self.win.winfo_exists():
                self.save_button.configure(state="normal")
                self.error.set("设置未保存，请检查服务状态。")
