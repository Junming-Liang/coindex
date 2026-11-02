"""Optional task-map canvas; standard Tk only, no browser or task mutations."""
import json
import time
import tkinter as tk
from tkinter import ttk, font as tkfont

SCOPES = {"所有未完成": "active", "近一周（含归档）": "period", "全部（含完成、归档）": "all"}
STATES = {"running": "进行中", "continue": "继续推进", "wait": "等待结果", "review": "结果校对",
          "decision": "需要决定", "manual": "手动任务", "done": "已完成", "resolved": "已解决",
          "conversation_archived": "已归档", "conversation_closed": "已结束", "dismissed": "已忽略"}


class TaskMapPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.document = None
        self.selected_id = None
        self.zoom = 1.0
        self.auto_fit = True
        self.serial = 0
        self.inflight = False
        self.timer = None
        self.signature = None
        self.scope = tk.StringVar(value="所有未完成")
        self.search = tk.StringVar()
        self.status = tk.StringVar(value="按需分析关系；原待办列表继续保留。")
        self.counter = tk.StringVar()
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 10))
        scope = ttk.Combobox(controls, textvariable=self.scope, values=tuple(SCOPES), width=24, state="readonly")
        scope.pack(side="left", padx=(0, 10))
        scope.bind("<<ComboboxSelected>>", lambda _e: self.change_scope())
        entry = ttk.Entry(controls, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.analyze_button = ttk.Button(controls, text="分析关系", style="Accent.TButton", command=self.analyze)
        self.analyze_button.pack(side="right")
        self.cancel_button = ttk.Button(controls, text="中止分析", command=self.cancel)
        legend = ttk.Frame(self)
        legend.pack(fill="x", pady=(0, 10))
        ttk.Label(legend, text="··· 同类问题    → 递进关系", style="Muted.TLabel").pack(side="left")
        ttk.Button(legend, text="适应窗口", command=self.fit).pack(side="right")
        ttk.Button(legend, text="＋", width=3, command=lambda: self.set_zoom(self.zoom+.15)).pack(side="right", padx=3)
        ttk.Button(legend, text="−", width=3, command=lambda: self.set_zoom(self.zoom-.15)).pack(side="right")
        ttk.Label(legend, textvariable=self.counter, style="Muted.TLabel").pack(side="right", padx=12)
        self.locator = ttk.Combobox(self, state="readonly")
        self.locator.pack(fill="x", pady=(0, 8))
        self.locator.set("定位任务：可用键盘选择节点")
        self.locator.bind("<<ComboboxSelected>>", self.locate)
        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", wraplength=660, justify="left").pack(anchor="w", pady=(0, 10))
        split = ttk.Frame(self)
        split.pack(fill="both", expand=True)
        area = ttk.Frame(split)
        area.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=app.BG, highlightthickness=1, highlightbackground=app.BORDER, takefocus=True)
        yscroll = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        xscroll = ttk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.bind("<Configure>", lambda _e: self.fit() if self.auto_fit else None)
        area.rowconfigure(0, weight=1); area.columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns"); xscroll.grid(row=1, column=0, sticky="ew")
        self.inspector = ttk.Frame(split, width=270, padding=(14, 0, 0, 0))
        self.inspector.pack_propagate(False)
        close = ttk.Frame(self.inspector)
        close.pack(fill="x", pady=(0, 8))
        ttk.Label(close, text="任务与关系", font=(app.font_family, 12, "bold")).pack(side="left")
        ttk.Button(close, text="×", width=3, command=lambda: self.select(None)).pack(side="right")
        self.text = tk.Text(self.inspector, wrap="word", width=27, font=(app.font_family, 10), bg=app.SURFACE,
                            fg=app.INK, relief="flat", padx=12, pady=12, state="disabled")
        self.text.pack(fill="both", expand=True)
        self.list_button = ttk.Button(self.inspector, text="在列表中查看", command=self.show_in_list)
        self.list_button.pack(fill="x", pady=(10, 0))
        self.canvas.bind("<Button-1>", lambda _e: self.canvas.focus_set(), add=True)
        self.canvas.bind("<Button-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(sequence, self.wheel)
        for key, axis, delta in (("Left", "x", -1), ("Right", "x", 1), ("Up", "y", -1), ("Down", "y", 1)):
            self.canvas.bind("<"+key+">", lambda _e, a=axis, d=delta: getattr(self.canvas, a+"view_scroll")(d, "units"))
        self.search.trace_add("write", lambda *_: self.draw())

    def show(self):
        self.refresh()
        if self.timer is None:
            self.timer = self.after(3000, self.poll)

    def hide(self):
        self.serial += 1
        self.inflight = False
        if self.timer:
            self.after_cancel(self.timer)
            self.timer = None

    def poll(self):
        self.timer = None
        if self.app.tab == "task-map":
            self.refresh()
            self.timer = self.after(3000, self.poll)

    def change_scope(self):
        self.serial += 1
        self.inflight = False
        self.selected_id = None
        self.document = None
        self.signature = None
        self.refresh()

    def refresh(self, method="task_map_detail"):
        if self.inflight:
            return
        if self.app.demo:
            from taskmap import demo_document
            self.accept(self.app.snapshot.get("task_map") or demo_document(self.app.snapshot.get("tasks", [])))
            return
        self.inflight = True
        self.serial += 1
        serial = self.serial
        values = {"scope": SCOPES[self.scope.get()], "days": 7}
        if method == "task_map_cancel": values["job_id"] = (self.document or {}).get("job_id", "")
        def done(response):
            if not self.winfo_exists() or serial != self.serial: return
            self.inflight = False
            if response.get("error"):
                self.status.set(str(response["error"]))
                return
            self.accept(response.get("result", {}))
        if self.app._rpc(method, done, **values) is None:
            self.inflight = False
            self.status.set("服务暂时不可用，可以稍后重试；原有任务保持不变。")

    def accept(self, document):
        self.analyze_button.configure(text="重新分析关系" if document.get("analysed") else "分析关系",
                                      state="disabled" if self.app.demo or document.get("busy") or not document.get("nodes") else "normal")
        self.cancel_button.configure(state="normal")
        signature = json.dumps(document, sort_keys=True, ensure_ascii=False)
        if signature == self.signature: return
        self.signature = signature
        self.document = document
        self.analyze_button.configure(text="重新分析关系" if document.get("analysed") else "分析关系",
                                      state="disabled" if self.app.demo or document.get("busy") or not document.get("nodes") else "normal")
        if document.get("status") in ("queued", "running"):
            self.cancel_button.pack(side="right", padx=(0, 8), before=self.analyze_button)
            self.status.set("正在分析问题主题和连线，可以继续浏览或中止。")
        else:
            self.cancel_button.pack_forget()
            self.status.set("演示数据 · 不会调用模型或修改任务。" if self.app.demo else
                            document.get("error") or ("任务已有变化，节点已同步；AI 连线来自上次分析，可重新分析。" if document.get("outdated") else
                            "AI 归纳的关系；点选节点查看两端依据，未连线不代表不存在关联。" if document.get("analysed") else
                            "已按任务阶段预排。点击“分析关系”识别同类问题与递进关系，会使用配置中的模型。"))
        self.locator.configure(values=tuple(n["title"] for n in document.get("nodes", [])))
        if self.selected_id not in {n["id"] for n in document.get("nodes", [])}: self.selected_id = None
        self.draw()
        self.update_inspector()
        if self.auto_fit: self.fit()

    def analyze(self):
        if not self.app.demo: self.refresh("task_map_analyze")

    def cancel(self):
        if not self.app.demo: self.refresh("task_map_cancel")

    def set_zoom(self, zoom):
        self.auto_fit = False
        self.zoom = max(.35, min(1.7, zoom))
        self.draw()

    def fit(self):
        self.auto_fit = True
        if not self.document: return
        self.zoom = max(.65, min(1.0, (max(100, self.canvas.winfo_width())-20)/self.document["width"],
                                 (max(100, self.canvas.winfo_height())-12)/self.document["height"]))
        self.draw()

    def wheel(self, event):
        delta = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
        if event.state & 4:
            self.set_zoom(self.zoom-delta*.1)
        else:
            getattr(self.canvas, "xview_scroll" if event.state & 1 else "yview_scroll")(delta*3, "units")
        return "break"

    def draw(self):
        if not self.document: return
        graph, z = self.document, self.zoom
        x, y = self.canvas.xview()[0], self.canvas.yview()[0]
        self.canvas.delete("all")
        query = self.search.get().strip().casefold()
        nodes = [n for n in graph.get("nodes", []) if not query or query in " ".join(str(n.get(k, "")) for k in ("title", "detail", "progress", "next_action", "topic")).casefold()]
        visible = {n["id"]: n for n in nodes}
        self.counter.set("%d / %d 项 · 归档 %d · %d%%" % (len(nodes), len(graph.get("nodes", [])), graph.get("archived_count", 0), int(z*100)))
        self.canvas.configure(scrollregion=(0, 0, graph.get("width", 640)*z, graph.get("height", 360)*z))
        if not nodes:
            self.canvas.create_text(24, 34, anchor="nw", text="没有匹配的任务，请调整搜索或范围。", fill=self.app.MUTED, font=(self.app.font_family, 11))
            return
        for group in graph.get("groups", []):
            self.canvas.create_rectangle(20*z, group["y"]*z, (graph["width"]-20)*z, (group["y"]+group["height"])*z,
                                         fill=self.app.SURFACE, outline=self.app.BORDER)
            self.canvas.create_text(40*z, (group["y"]+22)*z, text=group["title"], anchor="w", fill=self.app.MUTED,
                                    font=(self.app.font_family, max(8, int(11*z)), "bold"))
            self.canvas.create_text((graph["width"]-40)*z, (group["y"]+22)*z, text="%d 个任务" % group.get("count", 0),
                                    anchor="e", fill=self.app.MUTED, font=(self.app.font_family, max(8, int(9*z))))
        w, h = graph.get("node_width", 244), graph.get("node_height", 126)
        for edge in graph.get("edges", []):
            if edge["source"] not in visible or edge["target"] not in visible: continue
            selected = self.selected_id in (edge["source"], edge["target"])
            options = {"fill": self.app.ACCENT if selected or edge["kind"] == "progression" else self.app.MUTED,
                       "width": 2 if selected else 1.3}
            if edge["kind"] == "related": options["dash"] = (5, 5)
            else: options["arrow"] = "last"
            points = [coordinate for point in edge["points"] for coordinate in point]
            self.canvas.create_line(*(p*z for p in points), **options)
        for node in nodes:
            nx, ny = node["x"]*z, node["y"]*z
            tag = "node:"+node["id"]
            self.canvas.create_rectangle(nx, ny, nx+w*z, ny+h*z, fill=self.app.SUBTLE,
                                         outline=self.app.ACCENT if node["id"] == self.selected_id else self.app.BORDER,
                                         width=2 if node["id"] == self.selected_id else 1, tags=tag)
            state = STATES.get(node["kind"] if node.get("status") == "open" else node.get("status"), node.get("status", ""))
            self.canvas.create_text(nx+12*z, ny+15*z, text=state+(" · 已归档" if node.get("conversation_archived") else ""), anchor="w",
                                    fill=self.app.ACCENT, font=(self.app.font_family, max(8, int(9*z))), tags=tag)
            title_font = (self.app.font_family, max(8, int(11*z)), "bold")
            title = self.wrap(node["title"], title_font, (w-24)*z, 2)
            self.canvas.create_text(nx+12*z, ny+34*z, text=title, anchor="nw", width=(w-24)*z, fill=self.app.INK,
                                    font=title_font, tags=tag)
            progress = node.get("progress") or node.get("detail") or "尚未记录进展"
            progress_font = (self.app.font_family, max(8, int(9*z)))
            self.canvas.create_text(nx+12*z, ny+85*z, text=self.wrap(progress, progress_font, (w-24)*z, 1), anchor="nw", width=(w-24)*z,
                                    fill=self.app.MUTED, font=(self.app.font_family, max(8, int(9*z))), tags=tag)
            self.canvas.tag_bind(tag, "<Button-1>", lambda _e, ident=node["id"]: self.select(ident))
        offset = max(0, (self.canvas.winfo_width()-graph["width"]*z)/2)
        if offset: self.canvas.move("all", offset, 0)
        self.canvas.xview_moveto(x); self.canvas.yview_moveto(y)

    def wrap(self, value, font, width, limit):
        measure = tkfont.Font(root=self.app.root, font=font)
        lines, current = [], ""
        for character in " ".join(value.split()):
            if current and measure.measure(current+character) > width:
                lines.append(current)
                if len(lines) == limit:
                    last = lines[-1]
                    while last and measure.measure(last+"…") > width: last = last[:-1]
                    return "\n".join(lines[:-1]+[last+"…"])
                current = ""
            current += character
        return "\n".join(lines+[current])

    def select(self, ident):
        self.selected_id = ident
        self.draw()
        self.update_inspector()

    def locate(self, _event=None):
        index = self.locator.current()
        nodes = (self.document or {}).get("nodes", [])
        if index < 0 or index >= len(nodes): return
        node = nodes[index]
        self.search.set("")
        self.select(node["id"])
        self.canvas.xview_moveto(max(0, (node["x"]-40)/self.document["width"]))
        self.canvas.yview_moveto(max(0, (node["y"]-60)/self.document["height"]))

    def update_inspector(self):
        node = next((n for n in (self.document or {}).get("nodes", []) if n["id"] == self.selected_id), None)
        if not node:
            self.inspector.pack_forget()
            return
        if not self.inspector.winfo_manager(): self.inspector.pack(side="right", fill="y")
        lines = [node["title"], "", "整体目标", node.get("detail", ""), "", "停住位置", node.get("progress") or "尚未记录", "", "下一步", node.get("next_action", ""), "", "AI 归纳的关系"]
        for edge in self.document.get("edges", []):
            if self.selected_id in (edge["source"], edge["target"]):
                lines += ["", "递进 →" if edge["kind"] == "progression" else "同类关联 ···", edge["reason"],
                          "起点记录："+edge["source_quote"], "终点记录："+edge["target_quote"]]
        lines += ["", "连线不会合并任务，也不代表已确认的执行依赖。"]
        value = "\n".join(lines)
        if self.text.get("1.0", "end-1c") != value:
            self.text.configure(state="normal"); self.text.delete("1.0", "end"); self.text.insert("1.0", value); self.text.configure(state="disabled")
        self.list_button.configure(state="normal" if any(t["id"] == node["id"] for t in self.app.snapshot.get("tasks", [])) else "disabled")

    def show_in_list(self):
        node = next((n for n in (self.document or {}).get("nodes", []) if n["id"] == self.selected_id), None)
        if not node: return
        self.app.search_var.set("")
        self.app.host_var.set("全部来源")
        self.app.kind_var.set("全部类型")
        task = next((t for t in self.app.snapshot.get("tasks", []) if t["id"] == node["id"]), node)
        self.app.show_inactive = node.get("status") != "open" or task.get("snoozed_until", 0) > time.time()
        self.app.inactive_var.set(self.app.show_inactive)
        self.app._switch("tasks")
        self.app._select_task(node["id"])
