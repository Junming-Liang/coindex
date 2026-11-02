import SwiftUI

struct TaskMapWorkspaceView: View {
    @EnvironmentObject var model: AppModel
    @State private var graph: TaskMapDocument?
    @State private var scope = "active"
    @State private var search = ""
    @State private var selected: String?
    @State private var zoom = 1.0
    @State private var autoFit = true
    @State private var viewport = CGSize(width: 900, height: 600)
    @State private var loading = false
    @State private var error = ""
    @State private var requestSerial = 0
    private let poll = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    init(preview: TaskMapDocument? = nil) { _graph = State(initialValue: preview) }

    private var visible: [TaskMapNode] {
        (graph?.nodes ?? []).filter { search.isEmpty || ($0.title + $0.detail + $0.progress + $0.nextAction + $0.topic).localizedCaseInsensitiveContains(search) }
    }
    private var selectedNode: TaskMapNode? { graph?.nodes.first { $0.id == selected } }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("任务导图").font(.system(size: 25, weight: .semibold)).tracking(-0.6)
                        Text("同类问题分组对齐，递进关系从左向右。")
                            .font(.system(size: 12)).foregroundStyle(Palette.muted)
                    }
                    Spacer()
                    if graph?.status == "queued" || graph?.status == "running" {
                        Button("中止分析") { load("task_map_cancel") }.disabled(loading)
                    }
                    Button { load("task_map_analyze") } label: {
                        Label(graph?.analysed == true ? "重新分析关系" : "分析关系", systemImage: "sparkles")
                    }.buttonStyle(CoindexButtonStyle(prominent: true))
                        .disabled(loading || graph?.busy == true || graph?.nodes.isEmpty != false || model.isDemo)
                        .accessibilityIdentifier("task-map-analyze")
                }
                HStack(spacing: 12) {
                    Picker("范围", selection: $scope) {
                        Text("所有未完成").tag("active")
                        Text("近一周（含归档）").tag("period")
                        Text("全部（含完成、归档）").tag("all")
                    }.labelsHidden().frame(width: 190).accessibilityIdentifier("task-map-scope")
                    TextField("搜索问题、进度或下一步", text: $search).textFieldStyle(.plain).coindexInput()
                        .accessibilityIdentifier("task-map-search")
                    Button { autoFit = false; zoom = max(0.35, zoom-0.15) } label: { Image(systemName: "minus.magnifyingglass") }.help("缩小")
                    Text("\(Int(zoom*100))%").font(.caption.monospacedDigit()).frame(width: 42)
                    Button { autoFit = false; zoom = min(1.7, zoom+0.15) } label: { Image(systemName: "plus.magnifyingglass") }.help("放大")
                    Button("适应宽度") { autoFit = true; fit() }.help("保持文字清晰，可用滚动条或触控板平移")
                }
                HStack(spacing: 12) {
                    Label("同类问题 · 虚线", systemImage: "link").foregroundStyle(Palette.muted)
                    Label("递进关系 · 箭头", systemImage: "arrow.right").foregroundStyle(Palette.accent)
                    Spacer()
                    Text("\(visible.count) / \(graph?.nodes.count ?? 0) 个任务 · 归档 \(graph?.archivedCount ?? 0)")
                }.font(.system(size: 11))
            }.padding(20).background(Palette.surface)
            Divider()
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(statusText).font(.system(size: 11)).foregroundStyle(Palette.muted)
                        .padding(.horizontal, 20).padding(.vertical, 12).textSelection(.enabled)
                    if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange).padding(.horizontal, 20) }
                    if let graph, !graph.nodes.isEmpty {
                        ScrollView([.horizontal, .vertical]) {
                            diagram(graph).frame(width: graph.width, height: graph.height)
                                .scaleEffect(zoom, anchor: .topLeading)
                                .frame(width: graph.width*zoom, height: graph.height*zoom, alignment: .topLeading)
                                .frame(minWidth: viewport.width, alignment: .top)
                        }.background(GeometryReader { proxy in
                            Color.clear.onAppear { viewport = proxy.size; if autoFit { fit() } }
                                .onChange(of: proxy.size) { _, size in viewport = size; if autoFit { fit() } }
                        }).accessibilityIdentifier("task-map-canvas")
                    } else {
                        VStack(spacing: 12) {
                            Image(systemName: "point.3.connected.trianglepath.dotted").font(.system(size: 30)).foregroundStyle(Palette.accent)
                            Text(loading ? "正在读取任务…" : "这个范围还没有任务").font(.headline)
                            Text("可以切换范围，或回到列表添加待办。").font(.caption).foregroundStyle(Palette.muted)
                            Button("回到待办列表") { model.filter = "all" }
                        }.frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                if let node = selectedNode {
                    Divider()
                    inspector(node).frame(width: 286)
                }
            }
        }.background(Palette.canvas)
            .onAppear { load() }
            .onChange(of: scope) { _, _ in selected = nil; graph = nil; load(force: true) }
            .onReceive(poll) { _ in load() }
            .onDisappear { requestSerial += 1; loading = false }
    }

    private var statusText: String {
        guard let graph else { return "只读视图，不改变任务状态。" }
        if !graph.error.isEmpty { return graph.error + "；原有关系和任务已保留。" }
        if graph.status == "queued" || graph.status == "running" { return "正在分析问题主题和连线；可以继续浏览或中止。" }
        if graph.busy { return "其他范围的导图正在分析，切回原范围可查看进度或中止。" }
        if graph.outdated { return "任务已有变化，节点已同步；AI 连线来自上次分析，可重新分析。" }
        if model.isDemo { return "演示数据 · 关系仅供预览，不会调用模型或修改任务。" }
        return graph.analysed ? "连线为 AI 归纳，点选节点查看两端依据；没有连线不代表不存在关联。" : "已按现有任务阶段预排。点击“分析关系”识别同类问题与递进关系，会使用配置中的模型。"
    }

    private func diagram(_ graph: TaskMapDocument) -> some View {
        let ids = Set(visible.map(\.id))
        return ZStack(alignment: .topLeading) {
            Canvas { context, size in
                for group in graph.groups {
                    let rect = CGRect(x: 20, y: group.y, width: graph.width-40, height: group.height)
                    context.fill(Path(roundedRect: rect, cornerRadius: 14), with: .color(Palette.surface))
                    context.stroke(Path(roundedRect: rect, cornerRadius: 14), with: .color(Palette.border), lineWidth: 1)
                    context.draw(Text(group.title).font(.system(size: 13, weight: .semibold)).foregroundColor(Palette.muted),
                                 at: CGPoint(x: 40, y: group.y+23), anchor: .leading)
                    context.draw(Text("\(group.count) 个任务").font(.system(size: 10)).foregroundColor(Palette.muted),
                                 at: CGPoint(x: graph.width-40, y: group.y+23), anchor: .trailing)
                }
                for edge in graph.edges where ids.contains(edge.source) && ids.contains(edge.target) {
                    guard let first = edge.points.first, let last = edge.points.last,
                          edge.points.allSatisfy({ $0.count == 2 }) else { continue }
                    let related = edge.kind == "related"
                    let highlighted = selected == edge.source || selected == edge.target
                    let end = CGPoint(x: last[0], y: last[1])
                    var path = Path()
                    path.move(to: CGPoint(x: first[0], y: first[1]))
                    for point in edge.points.dropFirst() { path.addLine(to: CGPoint(x: point[0], y: point[1])) }
                    let color = highlighted ? Palette.accent : (related ? Palette.muted.opacity(0.5) : Palette.accent.opacity(0.65))
                    context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: highlighted ? 2.5 : 1.4, lineCap: .round, lineJoin: .round, dash: related ? [5, 5] : []))
                    if !related {
                        var arrow = Path()
                        arrow.move(to: CGPoint(x: end.x-8, y: end.y-5)); arrow.addLine(to: end); arrow.addLine(to: CGPoint(x: end.x-8, y: end.y+5))
                        context.stroke(arrow, with: .color(color), lineWidth: 1.6)
                    }
                }
            }
            ForEach(visible) { node in
                Button { selected = node.id } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(node.stateTitle).font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.accent)
                            Spacer()
                            Text(node.conversationArchived ? "已归档" : model.hostName(node.host)).font(.system(size: 10)).foregroundStyle(Palette.muted)
                        }
                        Text(node.title).font(.system(size: 13, weight: .semibold)).foregroundStyle(Palette.ink).lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                        Text(node.progress.isEmpty ? node.detail : node.progress).font(.system(size: 11)).foregroundStyle(Palette.muted).lineLimit(2)
                    }.padding(13).frame(width: graph.nodeWidth, height: graph.nodeHeight, alignment: .topLeading)
                        .background(Palette.subtle.opacity(0.65), in: RoundedRectangle(cornerRadius: 10))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(selected == node.id ? Palette.accent : Palette.border, lineWidth: selected == node.id ? 2 : 1))
                }.buttonStyle(HoverPlainStyle()).position(x: node.x+graph.nodeWidth/2, y: node.y+graph.nodeHeight/2)
                    .accessibilityIdentifier("task-map-node-"+node.id)
                    .accessibilityLabel(node.title + "，" + node.stateTitle)
            }
        }
    }

    private func inspector(_ node: TaskMapNode) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack { Text("任务与关系").font(.headline); Spacer(); Button { selected = nil } label: { Image(systemName: "xmark") }.help("关闭详情") }
                Text(node.title).font(.system(size: 18, weight: .semibold)).textSelection(.enabled)
                Text(node.stateTitle + (node.conversationArchived ? " · 已归档" : "")).font(.caption).foregroundStyle(Palette.accent)
                field("整体目标", node.detail)
                field("停住位置", node.progress.isEmpty ? "尚未记录" : node.progress)
                field("下一步", node.nextAction)
                if model.snapshot?.tasks.contains(where: { $0.id == node.id }) == true {
                    Button("在列表中查看") {
                        model.search = ""; model.hostFilter = "all"
                        model.filter = node.status != "open" ? "completed" : model.snapshot?.tasks.first(where: { $0.id == node.id })?.isSnoozed == true ? "snoozed" : "all"
                        model.selectedTaskId = node.id
                    }
                }
                Divider()
                Text("AI 归纳的关系").font(.headline)
                ForEach((graph?.edges ?? []).filter { $0.source == node.id || $0.target == node.id }) { edge in
                    VStack(alignment: .leading, spacing: 7) {
                        Text(edge.kind == "progression" ? "递进 →" : "同类关联 ···").font(.caption).foregroundStyle(Palette.accent)
                        if let neighbour = graph?.nodes.first(where: { $0.id == (edge.source == node.id ? edge.target : edge.source) }) {
                            Button(neighbour.title) { selected = neighbour.id }.font(.system(size: 12, weight: .medium))
                        }
                        Text(edge.reason).font(.system(size: 12))
                        Text("起点记录：\(edge.sourceQuote)\n终点记录：\(edge.targetQuote)").font(.system(size: 11)).foregroundStyle(Palette.muted).textSelection(.enabled)
                    }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Palette.subtle, in: RoundedRectangle(cornerRadius: 9))
                }
                Text("连线不会合并任务，也不代表已确认的执行依赖。").font(.caption).foregroundStyle(Palette.muted)
            }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
        }.background(Palette.surface)
    }

    private func field(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 11, weight: .medium)).foregroundStyle(Palette.muted)
            Text(text.isEmpty ? "尚未记录" : text).font(.system(size: 12)).textSelection(.enabled)
        }
    }

    private func load(_ method: String = "task_map_detail", force: Bool = false) {
        if loading && !force { return }
        requestSerial += 1
        let serial = requestSerial
        loading = true
        model.requestTaskMap(method, scope: scope, jobId: graph?.jobId ?? "") { value, message in
            guard serial == requestSerial else { return }
            loading = false
            error = message ?? ""
            if let value, value != graph {
                graph = value
                if autoFit { fit() }
                if let selected, !value.nodes.contains(where: { $0.id == selected }) { self.selected = nil }
            }
        }
    }

    private func fit() {
        guard let graph else { return }
        zoom = max(0.35, min(1, (viewport.width-20)/graph.width))
    }
}
