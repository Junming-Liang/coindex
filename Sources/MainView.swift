import AppKit
import SwiftUI
import ServiceManagement

struct MainView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    @State private var closingId: String?
    @FocusState private var searchFocused: Bool

    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 216)
            Rectangle().fill(Palette.border).frame(width: 1)
            VStack(spacing: 0) {
                if model.filter == "summaries" { SummaryWorkspaceView() }
                else if model.filter == "task-map" { TaskMapWorkspaceView() }
                else {
                    header
                    Rectangle().fill(Palette.border).frame(height: 1)
                    if model.filter == "conversations" { conversationList }
                    else if model.tasks.isEmpty { emptyState }
                    else {
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 12) {
                                ForEach(model.tasks) { task in
                                    TaskCard(task: task, selected: task.id == model.selectedTaskId)
                                        .onTapGesture { model.selectedTaskId = task.id }
                                        .accessibilityAction(named: Text("查看任务详情")) { model.selectedTaskId = task.id }
                                }
                            }.padding(20)
                        }
                    }
                }
                footer
            }.frame(minWidth: 390, maxWidth: .infinity).background(Palette.canvas)
            if let task = model.selectedTask, model.filter != "conversations", model.filter != "summaries", model.filter != "task-map" {
                Rectangle().fill(Palette.border).frame(width: 1)
                detail(task).frame(width: 332)
            }
        }
        .foregroundStyle(Palette.ink).background(Palette.canvas).tint(Palette.accent).buttonStyle(CoindexButtonStyle())
        .frame(minWidth: 960, minHeight: 660)
        .onAppear {
            let action = openWindow
            model.reopenMainWindow = { action(id: "main") }
        }
        .sheet(isPresented: $model.showSettings) { SettingsView() }
        .sheet(isPresented: $model.showAppUpdate) { AppUpdateView() }
        .sheet(isPresented: $model.showPetSettings) { PetSettingsView(pet: model.pet) }
        .sheet(isPresented: $model.showManualEditor) { ManualTodoEditor(task: model.manualEditingTask) }
        .sheet(isPresented: $model.showTitleEditor) {
            if let task = model.titleEditingTask { TodoTitleEditor(task: task) }
        }
        .alert("结束这段对话的任务？", isPresented: Binding(get: { closingId != nil }, set: { if !$0 { closingId = nil } })) {
            Button("取消", role: .cancel) { closingId = nil }
            Button("结束任务", role: .destructive) {
                if let id = closingId { model.act("close_conversation", id: id) }
                closingId = nil
            }
        } message: {
            Text("本对话的所有待办会结束，之后自动扫描也会跳过它。可以在“所有对话”中恢复跟踪。")
        }
        .overlay(alignment: .bottom) {
            if !model.toast.isEmpty {
                Label(model.toast, systemImage: "checkmark.circle.fill")
                    .font(.callout).padding(.horizontal, 18).padding(.vertical, 12)
                    .background(Palette.surface, in: Capsule())
                    .overlay(Capsule().stroke(Palette.border)).shadow(color: .black.opacity(0.08), radius: 12, y: 4)
                    .padding(.bottom, 48).transition(.opacity)
            }
        }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                BrandBadge(size: 34)
                VStack(alignment: .leading, spacing: 2) {
                    Text("coindex").font(.system(size: 20, weight: .semibold)).tracking(-0.5)
                    Text("让每件事有下一步").font(.system(size: 10)).foregroundStyle(Palette.muted)
                }
            }.padding(.horizontal, 20).padding(.top, 24).padding(.bottom, 28)
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(spacing: 3) {
                        nav("全部待办", "square.stack", "all", model.count("all"))
                        nav("进行中", "play.circle", "running", model.count("running"))
                        nav("结果校对", "checkmark.square", "review", model.count("review"))
                        nav("继续推进", "arrow.right.circle", "continue", model.count("continue"))
                        nav("等待结果", "hourglass", "wait", model.count("wait"))
                        nav("需要决定", "questionmark.bubble", "decision", model.count("decision"))
                        nav("手动待办", "square.and.pencil", "manual", model.count("manual"))
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        sectionLabel("记录")
                        nav("总结", "doc.text", "summaries", nil)
                        nav("任务导图", "point.3.connected.trianglepath.dotted", "task-map", nil)
                        nav("稍后处理", "clock", "snoozed", nil)
                        nav("已完成 / 已忽略", "checkmark.circle", "completed", nil)
                        nav("所有对话", "text.bubble", "conversations", nil)
                    }
                    if model.filter != "summaries" && model.filter != "task-map" {
                        VStack(alignment: .leading, spacing: 3) {
                            sectionLabel("对话来源")
                            Button { model.hostFilter = "all" } label: {
                                HStack(spacing: 9) {
                                    Image(systemName: "desktopcomputer").frame(width: 18)
                                    Text("所有机器")
                                    Spacer()
                                    if model.hostFilter == "all" { Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)) }
                                }.font(.system(size: 12)).foregroundStyle(Palette.muted)
                                    .padding(.horizontal, 12).padding(.vertical, 8)
                                    .background(model.hostFilter == "all" ? Palette.subtle : .clear, in: RoundedRectangle(cornerRadius: 7))
                            }.buttonStyle(HoverPlainStyle())
                            ForEach(model.snapshot?.hosts ?? []) { host in
                                Button { model.hostFilter = host.id } label: {
                                    HStack(spacing: 12) {
                                        Circle().fill(host.status == "online" ? Palette.success : host.status == "offline" ? Color.orange : Palette.muted).frame(width: 5, height: 5).frame(width: 18)
                                        Text(model.hostName(host.id))
                                        Spacer()
                                        if model.hostFilter == host.id { Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)) }
                                    }.font(.system(size: 12)).foregroundStyle(Palette.muted)
                                        .padding(.horizontal, 12).padding(.vertical, 8)
                                        .background(model.hostFilter == host.id ? Palette.subtle : .clear, in: RoundedRectangle(cornerRadius: 7))
                                }.buttonStyle(HoverPlainStyle()).help(host.detail)
                            }
                        }
                    }
                }.padding(.horizontal, 12)
            }
            Spacer(minLength: 12)
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles").foregroundStyle(Palette.accent)
                    Text(model.snapshot?.model ?? "gpt-6-luna").fontWeight(.medium)
                    Text((model.snapshot?.effort ?? "max").uppercased()).font(.system(size: 9, weight: .semibold)).padding(.horizontal, 5).padding(.vertical, 2)
                        .background(Palette.accentWash, in: RoundedRectangle(cornerRadius: 4))
                }.font(.system(size: 11))
                HStack(spacing: 6) {
                    Circle().fill(model.isOffDuty ? Palette.muted : model.snapshot?.settings.automatic == true ? Palette.success : Palette.muted).frame(width: 5, height: 5)
                    Text(model.isOffDuty ? "已下班 · 更新暂停" : model.snapshot?.settings.automatic == true ? "自动更新已开启" : "自动更新已暂停")
                        .font(.system(size: 10)).foregroundStyle(Palette.muted)
                    Spacer(minLength: 0)
                }
                HStack(spacing: 6) {
                    Button { model.showPetSettings = true } label: { Label("宠物", systemImage: "pawprint") }
                    Spacer()
                    Button { model.showSettings = true } label: { Label("设置", systemImage: "slider.horizontal.3") }
                }.buttonStyle(HoverPlainStyle()).font(.system(size: 11)).foregroundStyle(Palette.muted).padding(.top, 4)
            }.padding(16).background(Palette.surface.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Palette.border)).padding(12)
        }.background(Palette.sidebar)
    }

    private func sectionLabel(_ title: String) -> some View {
        Text(title).font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.muted)
            .padding(.horizontal, 12).padding(.bottom, 7)
    }

    private func nav(_ title: String, _ symbol: String, _ filter: String, _ count: Int?) -> some View {
        let active = model.filter == filter
        return Button { model.filter = filter; model.selectedTaskId = nil } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol).font(.system(size: 13)).frame(width: 18)
                Text(title).font(.system(size: 12, weight: active ? .semibold : .regular))
                Spacer(minLength: 3)
                if let count {
                    Text("\(count)").font(.system(size: 10, weight: .medium)).monospacedDigit()
                        .frame(minWidth: 18).padding(.horizontal, 3).padding(.vertical, 2)
                        .background(active ? Palette.surface.opacity(0.6) : Color.clear, in: RoundedRectangle(cornerRadius: 4))
                }
            }.foregroundStyle(active ? Palette.accent : Palette.ink)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(active ? Palette.accentWash : .clear, in: RoundedRectangle(cornerRadius: 7))
        }.buttonStyle(HoverPlainStyle()).accessibilityIdentifier("filter-" + filter)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 8) {
                Text("工作台").foregroundStyle(Palette.muted)
                Image(systemName: "chevron.right").font(.system(size: 8)).foregroundStyle(Palette.muted)
                Text(pageTitle).fontWeight(.medium).lineLimit(1)
                Spacer(minLength: 8)
                if model.isDemo { Text("预览").font(.system(size: 10)).foregroundStyle(Palette.muted) }
                Button { model.toggleWorkday() } label: {
                    Image(systemName: model.isOffDuty ? "sun.max" : "moon")
                }.buttonStyle(QuietIconStyle()).disabled(model.isFinishingWorkday || model.isDemo)
                    .help(model.isOffDuty ? "提前上班" : "下班：中止更新，暂停到明天设定的开始时间")
                    .accessibilityLabel(model.isOffDuty ? "提前上班" : "下班").accessibilityIdentifier("workday-toggle")
                if model.syncing {
                    Button { model.cancelSync() } label: {
                        Label(model.isCancelling ? "正在中止" : "中止更新", systemImage: "stop.circle")
                    }.buttonStyle(CoindexButtonStyle()).disabled(model.isCancelling)
                }
                Button { model.sync() } label: {
                    HStack(spacing: 5) {
                        if model.syncing { ProgressView().controlSize(.mini) }
                        else { Image(systemName: "arrow.triangle.2.circlepath") }
                        Text(model.syncing ? "更新中" : "更新")
                    }
                }.buttonStyle(CoindexButtonStyle()).disabled(model.updateDisabled).help("立即更新 · ⌘R")
                Button { model.editManual() } label: { Label("新建待办", systemImage: "plus") }
                    .buttonStyle(CoindexButtonStyle(prominent: true)).help("新建待办 · ⌘N")
            }.font(.system(size: 11))
            HStack(alignment: .center, spacing: 16) {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 9) {
                        Text(pageTitle).font(.system(size: 25, weight: .semibold)).tracking(-0.6)
                        Text("\(visibleCount)").font(.system(size: 12, weight: .medium)).monospacedDigit()
                            .foregroundStyle(Palette.muted).padding(.horizontal, 7).padding(.vertical, 3)
                            .background(Palette.subtle, in: RoundedRectangle(cornerRadius: 5))
                    }
                    Text(pageSubtitle).font(.system(size: 11)).foregroundStyle(Palette.muted).lineLimit(2)
                }
                Spacer(minLength: 0)
                HStack(spacing: 7) {
                    Image(systemName: "magnifyingglass").foregroundStyle(Palette.muted)
                    TextField("搜索待办或对话", text: $model.search).textFieldStyle(.plain).focused($searchFocused)
                        .accessibilityIdentifier("task-search")
                    if !model.search.isEmpty {
                        Button { model.search = "" } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(HoverPlainStyle()).foregroundStyle(Palette.muted).help("清除搜索")
                    }
                }.font(.system(size: 12)).padding(.horizontal, 10).padding(.vertical, 9)
                    .frame(width: 180).background(Palette.surface, in: RoundedRectangle(cornerRadius: 7))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(searchFocused ? Palette.accent : Palette.border))
            }
        }.padding(.horizontal, 20).padding(.top, 18).padding(.bottom, 20).background(Palette.surface)
    }

    private var filteredConversations: [Conversation] {
        (model.snapshot?.conversations ?? []).filter {
            (model.hostFilter == "all" || $0.host == model.hostFilter) && (model.search.isEmpty || $0.title.localizedCaseInsensitiveContains(model.search))
        }
    }
    private var visibleCount: Int { model.filter == "conversations" ? filteredConversations.count : model.tasks.count }
    private var pageTitle: String {
        ["all": "全部待办", "running": "进行中", "review": "结果校对", "continue": "继续推进", "wait": "等待结果", "decision": "需要决定", "manual": "手动待办", "completed": "已完成 / 已忽略", "snoozed": "稍后处理", "conversations": "所有对话"][model.filter] ?? "待办"
    }
    private var pageSubtitle: String {
        if !model.search.isEmpty { return "搜索结果 · \(model.hostFilter == "all" ? "所有机器" : model.hostName(model.hostFilter))" }
        return ["all": "目标、当前进度与下一步，一处查看。", "running": "正在执行的任务与最新进度。", "review": "检查已提交的结果与产物。", "continue": "接着推进中断或未完成的工作。", "wait": "跟进外部任务，等待产出结果。", "decision": "需要你提供信息或作出选择。", "manual": "独立记录，无需关联 Codex 对话。", "completed": "已处理的待办，可随时恢复。", "snoozed": "暂缓的待办，到时回到列表。", "conversations": "查看进展，管理对话跟踪。"][model.filter] ?? ""
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: model.syncing ? "sparkles" : model.search.isEmpty ? "checkmark" : "magnifyingglass")
                .font(.system(size: 26, weight: .light)).foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64).background(Palette.accentWash, in: RoundedRectangle(cornerRadius: 18))
            Text(model.syncing ? "正在整理对话" : model.search.isEmpty ? "暂无待办" : "没有匹配的待办")
                .font(.system(size: 17, weight: .semibold))
            Text(!model.search.isEmpty ? "试试其他关键词，或清除搜索。" : model.snapshot?.pendingAnalysis ?? 0 > 0 ? "还有 \(model.snapshot?.pendingAnalysis ?? 0) 个对话待分析。" : "新的工作进展会在更新后出现在这里。")
                .font(.system(size: 12)).foregroundStyle(Palette.muted).multilineTextAlignment(.center).frame(maxWidth: 300)
            if !model.search.isEmpty {
                Button("清除搜索") { model.search = "" }.buttonStyle(CoindexButtonStyle())
            } else if model.filter == "manual" || model.filter == "all" {
                Button { model.editManual() } label: { Label("新建待办", systemImage: "plus") }.buttonStyle(CoindexButtonStyle())
            }
            if !(model.snapshot?.modelError ?? "").isEmpty {
                Button { model.showSettings = true } label: { Label("模型分析异常 · 查看诊断", systemImage: "exclamationmark.triangle") }
                    .buttonStyle(HoverPlainStyle()).font(.caption).foregroundStyle(.orange)
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(24)
    }

    private var conversationList: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                ForEach(filteredConversations) { conv in
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: conv.closed == 1 ? "checkmark.seal" : "text.bubble")
                            .font(.system(size: 15)).foregroundStyle(conv.closed == 1 ? Palette.muted : Palette.accent)
                            .frame(width: 32, height: 32).background(Palette.subtle, in: RoundedRectangle(cornerRadius: 8))
                        VStack(alignment: .leading, spacing: 7) {
                            Text(conv.title).font(.system(size: 14, weight: .semibold)).lineLimit(2)
                            Text(conv.needsAnalysis == true ? "最新记录待整理" : conv.summary.isEmpty ? "等待分析最近记录" : conv.summary)
                                .font(.system(size: 12)).foregroundStyle(Palette.muted).lineLimit(2)
                            Text("\(model.hostName(conv.host)) · \(conv.stateTitle) · \(relativeTime(conv.updatedAt))")
                                .font(.system(size: 10)).foregroundStyle(Palette.muted)
                        }
                        Spacer(minLength: 8)
                        if conv.archived == 1 { Text("已归档").font(.caption).foregroundStyle(Palette.muted) }
                        else if conv.closed == 1 { Button("恢复跟踪") { model.act("reopen_conversation", id: conv.id) }.buttonStyle(CoindexButtonStyle()) }
                        else { Button("结束任务") { closingId = conv.id }.buttonStyle(CoindexButtonStyle()) }
                    }.padding(16).background(Palette.surface, in: RoundedRectangle(cornerRadius: 10))
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Palette.border))
                }
            }.padding(20)
        }
    }

    private var footer: some View {
        HStack(spacing: 7) {
            if model.isFinishingWorkday { ProgressView().controlSize(.mini); Text("正在切换上下班状态…") }
            else if model.isOffDuty { Image(systemName:"moon.fill"); Text("已下班 · \(detectionTime(model.snapshot?.schedule?.offDutyUntil)) 恢复检测") }
            else if model.isCancelling { ProgressView().controlSize(.mini); Text("正在中止本次更新…") }
            else if model.syncing { ProgressView().controlSize(.mini); Text(model.snapshot?.sync.phase ?? "开始更新…") }
            else if model.snapshot?.sync.cancelled == true && model.snapshot?.settings.automatic != true { Image(systemName: "stop.circle"); Text("更新已中止 · 自动更新已暂停") }
            else { Image(systemName: "clock.arrow.circlepath"); Text("上次更新：\(relativeTime(model.snapshot?.lastSync ?? 0))") }
            Spacer()
            if !model.syncing, !model.isOffDuty, model.snapshot?.settings.automatic == true {
                Text("下次：\(detectionTime(model.snapshot?.schedule?.nextAt))")
            }
            let backlog = (model.snapshot?.hosts ?? []).reduce(0) { $0 + $1.remainingFiles }
            if backlog > 0 { Text("历史回填 \(backlog) 个文件") }
            if model.snapshot?.pendingAnalysis ?? 0 > 0 { Text("待分析 \(model.snapshot?.pendingAnalysis ?? 0)") }
            if !model.error.isEmpty || !(model.snapshot?.modelError ?? "").isEmpty {
                Button { model.showSettings = true } label: { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange) }.buttonStyle(HoverPlainStyle()).help(model.error.isEmpty ? model.snapshot?.modelError ?? "查看诊断" : model.error)
            }
        }.font(.system(size: 10)).foregroundStyle(Palette.muted).lineLimit(1).padding(.horizontal, 20).padding(.vertical, 11).background(Palette.surface)
            .overlay(alignment: .top) { Rectangle().fill(Palette.border).frame(height: 1) }
    }

    private func detail(_ task: TodoTask) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Label("任务详情", systemImage: "sidebar.right").font(.system(size: 11, weight: .medium)).foregroundStyle(Palette.muted)
                    Spacer()
                    Button { model.selectedTaskId = nil } label: { Image(systemName: "xmark") }.buttonStyle(QuietIconStyle()).help("收起详情")
                }
                VStack(alignment: .leading, spacing: 10) {
                    StatusBadge(task: task)
                    Text(task.title).font(.system(size: 22, weight: .semibold)).tracking(-0.4).textSelection(.enabled)
                    Text(task.detail).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                }
                if task.isManual {
                    Button("编辑待办") { model.editManual(task) }
                } else {
                    VStack(alignment:.leading,spacing:6) {
                        Button { model.editTitle(task) } label: { Label("修改标题", systemImage:"pencil") }
                            .accessibilityIdentifier("detail-edit-title-\(task.id)")
                        if task.hasCustomTitle { Text("手动标题，自动更新不会覆盖").font(.caption).foregroundStyle(.secondary) }
                    }
                    detailSection(task.isRunning ? "当前进度" : "停住位置", text: task.stopPoint)
                    detailSection(task.isRunning ? "接下来" : "下一步", text: task.nextAction)
                    Button { model.copy(task.nextAction) } label: { Label("复制下一步", systemImage: "doc.on.doc") }.controlSize(.small)
                    if task.isOpen { NudgeControl(task: task, detailed: true) }
                }
                if task.isOpen {
                    HStack {
                        Button { model.act("complete", id: task.id) } label: { Label("完成", systemImage: "checkmark") }.buttonStyle(CoindexButtonStyle(prominent: true))
                        Button("稍后一小时") { model.act("snooze", id: task.id, value: 60) }
                    }.controlSize(.regular)
                } else { Button("恢复待办") { model.act("reopen", id: task.id) } }
                if !task.isManual {
                if !task.artifact.isEmpty { detailSection("对应结果", text: task.artifact) }
                DisclosureGroup("原文依据") {
                    VStack(alignment: .leading, spacing: 8) {
                    Text("“\(task.evidence)”").font(.callout).foregroundStyle(.secondary).textSelection(.enabled).padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Palette.subtle, in: RoundedRectangle(cornerRadius: 8))
                    Text("判断把握 \(Int(task.confidence * 100))% · 来源于对话最后记录").font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                }
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Text("原始对话").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    Text(task.conversationTitle).font(.callout).textSelection(.enabled)
                    Text(model.hostName(task.host)).font(.caption).foregroundStyle(Palette.accent)
                    Text(task.cwd).font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary).textSelection(.enabled)
                    HStack {
                        Button("打开 Codex") { model.openConversation(task.threadId, host: task.host) }
                        Button("复制来源") { model.copy("主机: \(task.host)\n对话: \(task.threadId)\n文件: \(task.path)") }
                    }.controlSize(.small)
                }
                }
                if task.isOpen {
                    Button("忽略此待办") { model.act("dismiss", id: task.id) }.controlSize(.small)
                }
                if !task.isManual {
                    Button("结束本对话的所有任务", role: .destructive) { closingId = task.conversationId }.buttonStyle(HoverPlainStyle()).font(.caption).foregroundStyle(.secondary)
                }
            }.padding(20)
        }.background(Palette.surface)
    }

    private func detailSection(_ title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.accent)
            Text(text).font(.system(size: 13)).lineSpacing(3).textSelection(.enabled)
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.subtle, in: RoundedRectangle(cornerRadius: 9))
    }
}

struct TaskCard: View {
    @EnvironmentObject var model: AppModel
    let task: TodoTask
    let selected: Bool
    @State private var hovered = false
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Button { model.act(task.isOpen ? "complete" : "reopen", id: task.id) } label: {
                Image(systemName: task.isOpen ? "circle" : "checkmark.circle.fill")
                    .font(.system(size: 20, weight: .light)).foregroundStyle(task.isOpen ? Palette.muted : Palette.success)
                    .frame(width: 24, height: 26).contentShape(Rectangle())
            }.buttonStyle(HoverPlainStyle()).padding(.top, 31).help(task.isOpen ? "标记完成" : "恢复待办")
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    StatusBadge(task: task)
                    if task.priority == 1 { Label("优先", systemImage: "flag.fill").font(.system(size: 10)).foregroundStyle(.orange) }
                    Spacer()
                    Text(task.isManual ? "手动添加" : model.hostName(task.host)).font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.muted)
                }
                HStack(alignment: .top, spacing: 8) {
                    Text(task.title).font(.system(size: 16, weight: .semibold)).tracking(-0.2)
                        .foregroundStyle(Palette.ink).lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                    Button { model.editTitle(task) } label: { Image(systemName: task.hasCustomTitle ? "pencil.circle.fill" : "pencil") }
                        .buttonStyle(HoverPlainStyle()).foregroundStyle(Palette.muted).padding(.top, 2)
                        .help(task.hasCustomTitle ? "修改手动标题；自动更新不会覆盖" : "修改标题；保存后自动更新不会覆盖")
                        .accessibilityLabel("修改标题").accessibilityIdentifier("edit-title-\(task.id)")
                }
                if task.isManual {
                    if !task.detail.isEmpty { Text(task.detail).font(.system(size: 12)).foregroundStyle(Palette.muted).lineLimit(3) }
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        cardLine(task.isRunning ? "当前进度" : "停住位置", text: task.stopPoint, next: false)
                        cardLine(task.isRunning ? "接下来" : "下一步", text: task.nextAction, next: true)
                    }.padding(11).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Palette.subtle.opacity(0.7), in: RoundedRectangle(cornerRadius: 7))
                }
                HStack(spacing: 8) {
                    if !task.isManual {
                        Label(task.conversationTitle, systemImage: "text.bubble").lineLimit(1)
                    }
                    Spacer(minLength: 4)
                    Text(relativeTime(task.conversationUpdatedAt)).fixedSize()
                    if task.isOpen && !task.isManual { NudgeControl(task: task, detailed: false) }
                    else { Image(systemName: "chevron.right").font(.system(size: 9)) }
                }.font(.system(size: 10)).foregroundStyle(Palette.muted)
                if let record = model.latestNudge(task) {
                    Text(record.summary).font(.system(size: 10)).foregroundStyle(record.status == "unknown" || record.status == "failed" ? Color.orange : Palette.muted).lineLimit(2)
                }
            }
        }.padding(16).background(Palette.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(selected ? Palette.accent : hovered ? Palette.muted.opacity(0.6) : Palette.border, lineWidth: selected ? 1.5 : 1))
            .overlay(alignment: .leading) {
                if selected { Capsule().fill(Palette.accent).frame(width: 3, height: 28).padding(.leading, 1) }
            }
            .contentShape(RoundedRectangle(cornerRadius: 12)).onHover { hovered = $0 }
            .contextMenu {
                Button("修改标题") { model.editTitle(task) }
                if task.isManual { Button("编辑待办") { model.editManual(task) } }
                else { Button("复制下一步") { model.copy(task.nextAction) } }
                if task.isOpen && !task.isManual { Button("一键催办") { model.nudge(task) }.disabled(model.nudgeDisabled(task)) }
                Button("稍后一小时") { model.act("snooze", id: task.id, value: 60) }
                Button("忽略") { model.act("dismiss", id: task.id) }
            }
    }

    private func cardLine(_ label: String, text: String, next: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(label).font(.system(size: 10, weight: .medium)).foregroundStyle(next ? Palette.accent : Palette.muted)
                .frame(width: 45, alignment: .leading)
            Text(text).font(.system(size: 12, weight: next ? .medium : .regular))
                .foregroundStyle(next ? Palette.ink : Palette.muted).lineLimit(2)
        }
    }
}

struct TodoTitleEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @FocusState private var titleFocused: Bool
    @State private var title: String
    @State private var saving = false
    @State private var error = ""
    let task: TodoTask

    init(task: TodoTask) {
        self.task = task
        _title = State(initialValue:task.title)
    }

    private var valid: Bool { !title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && title.count <= 100 }
    private func save() {
        guard valid, !saving else { return }
        saving = true
        model.saveTitle(title:title) { message in
            saving = false
            if let message { error = message } else { dismiss() }
        }
    }

    var body: some View {
        VStack(alignment:.leading,spacing:18) {
            Text("修改标题").font(.title2).fontWeight(.semibold)
            TextField("这项任务整体要做什么？",text:$title)
                .textFieldStyle(.plain).coindexInput().focused($titleFocused)
                .accessibilityIdentifier("todo-title-field").onSubmit { save() }
            HStack {
                Text(task.isManual ? "只修改标题，保留备注和优先级。" : "保存后标题固定，自动更新只刷新进度和下一步。")
                    .font(.callout).foregroundStyle(.secondary)
                Spacer()
                Text("\(title.count)/100").font(.caption).foregroundStyle(.secondary)
            }
            if !error.isEmpty { Text(error).font(.callout).foregroundStyle(.red) }
            HStack {
                Spacer()
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction).disabled(saving)
                Button(saving ? "正在保存…" : "保存") { save() }
                    .buttonStyle(CoindexButtonStyle(prominent: true)).keyboardShortcut(.defaultAction).disabled(saving || !valid)
            }
        }.padding(28).frame(width:540).background(Palette.canvas).foregroundStyle(Palette.ink).tint(Palette.accent).buttonStyle(CoindexButtonStyle())
            .interactiveDismissDisabled(saving).onAppear { titleFocused = true }
    }
}

struct NudgeControl: View {
    @EnvironmentObject var model: AppModel
    let task: TodoTask
    let detailed: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Button { model.nudge(task) } label: {
                    Label(model.nudgePending(task) ? "发送中…" : "一键催办", systemImage: model.nudgePending(task) ? "hourglass" : "paperplane")
                }.buttonStyle(CoindexButtonStyle()).controlSize(.small).disabled(model.nudgeDisabled(task))
                    .help("把此任务的进度和下一步发回原 Codex 对话，继续推进")
                    .accessibilityIdentifier("nudge-" + task.id)
                if detailed, let record = model.latestNudge(task) {
                    Text(record.summary).font(.system(size: 10)).foregroundStyle(record.status == "unknown" || record.status == "failed" ? Color.orange : Color.secondary)
                        .lineLimit(detailed ? nil : 2)
                }
            }
            if detailed {
                Text("运行中追加催办，停止后继续推进；沿用原对话的模型和权限。").font(.caption).foregroundStyle(.secondary)
                if model.latestNudge(task)?.status == "unknown" {
                    Text(model.latestNudge(task)?.error ?? "").font(.caption).foregroundStyle(.orange)
                    HStack {
                        Button("核对原对话") { model.openConversation(task.threadId, host: task.host) }
                        Button("确认未送达后重试") { model.nudge(task,retryUnknown:true) }.disabled(model.nudgePending(task))
                    }.controlSize(.small)
                }
            }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    @State private var login = SMAppService.mainApp.status == .enabled
    @State private var loginError = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 10) { BrandBadge(size: 28); Text("设置").font(.system(size: 22, weight: .semibold)); Spacer(); Button("完成") { dismiss() }.buttonStyle(CoindexButtonStyle()).keyboardShortcut(.defaultAction) }
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    SettingsSection("应用版本", symbol: "shippingbox") {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Text("coindex \(model.appVersion)").font(.headline)
                                Spacer()
                                Button(model.checkingAppUpdate ? "正在检查…" : "检查版本更新") { model.checkForAppUpdates() }
                                    .disabled(model.checkingAppUpdate || model.appUpdateChecksDisabled)
                                    .accessibilityIdentifier("check-app-updates")
                            }
                            Text("启动时检查新版本，显示更新内容后由你选择下载或跳过该版本。")
                                .font(.caption).foregroundStyle(Palette.muted)
                            if !model.appUpdateMessage.isEmpty { Text(model.appUpdateMessage).font(.caption).foregroundStyle(Palette.muted) }
                        }
                    }
                    ConnectionSettingsView()
                    SettingsSection("更新与启动", symbol: "arrow.triangle.2.circlepath") {
                        VStack(alignment: .leading, spacing: 14) {
                            Toggle("自动整理对话", isOn: Binding(get: { model.snapshot?.settings.automatic ?? false }, set: { model.settings(["automatic": $0]) }))
                            settingPicker("更新间隔", value: model.snapshot?.settings.intervalSeconds ?? 1800, options: [(60, "1 分钟"), (120, "2 分钟"), (300, "5 分钟"), (600, "10 分钟"), (1800,"30 分钟"), (3600,"1 小时")], key: "interval_seconds")
                            settingPicker("中断续办的等待时间", value: model.snapshot?.settings.idleMinutes ?? 10, options: [(5, "5 分钟"), (10, "10 分钟"), (30, "30 分钟"), (60, "1 小时")], key: "idle_minutes")
                            settingPicker("对话历史范围", value: model.snapshot?.settings.historyDays ?? 0, options: [(0, "全部历史（逐批回填）"), (7, "最近 7 天"), (30, "最近 30 天"), (90, "最近 90 天")], key: "history_days")
                            Toggle("登录 Mac 时启动", isOn: $login).onChange(of: login) { _, value in
                                do {
                                    if value { try SMAppService.mainApp.register() }
                                    else { try SMAppService.mainApp.unregister() }
                                    loginError = ""
                                } catch { loginError = error.localizedDescription }
                            }
                            if !loginError.isEmpty { Text(loginError).font(.caption).foregroundStyle(.orange) }
                            Text("关闭主窗口后，菜单栏仍会继续更新。退出 App 或 Mac 休眠时暂停，重新打开或唤醒后继续。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    SettingsSection("检测时间 · 北京时间", symbol: "calendar.badge.clock") {
                        VStack(alignment:.leading,spacing:12) {
                            Toggle("只在法定工作日检测（含调休补班）",isOn:Binding(get:{model.snapshot?.settings.workdaysOnly ?? true},set:{model.settings(["workdays_only":$0])}))
                            Toggle("限定每天的检测时段",isOn:Binding(get:{model.snapshot?.settings.workHoursEnabled ?? false},set:{model.settings(["work_hours_enabled":$0])}))
                            if model.snapshot?.settings.workHoursEnabled == true {
                                HStack {
                                    DatePicker("从",selection:clockBinding("work_start_minutes",fallback:540),displayedComponents:.hourAndMinute)
                                    DatePicker("到",selection:clockBinding("work_end_minutes",fallback:1080),displayedComponents:.hourAndMinute)
                                }
                                if (model.snapshot?.settings.workEndMinutes ?? 1080) < (model.snapshot?.settings.workStartMinutes ?? 540) {
                                    Text("跨午夜时段按开始日期的工作日安排。").font(.caption).foregroundStyle(.secondary)
                                }
                            } else { Text("全天检测").font(.caption).foregroundStyle(.secondary) }
                            if let schedule = model.snapshot?.schedule {
                                Text("今天：\(schedule.dayLabel)").font(.callout)
                                if model.isOffDuty {
                                    Text("已下班：\(detectionTime(schedule.offDutyUntil)) 结束暂停").font(.callout).foregroundStyle(Palette.accent)
                                    Button("提前上班") { model.toggleWorkday() }.controlSize(.small).disabled(model.isFinishingWorkday)
                                }
                                Text(model.snapshot?.settings.automatic == true ? "下次检测：\(detectionTime(schedule.nextAt))" : "自动更新已暂停").font(.caption).foregroundStyle(.secondary)
                                Text("调休数据：\(relativeTime(schedule.calendarUpdatedAt))").font(.caption).foregroundStyle(.secondary)
                                if !schedule.calendarError.isEmpty { Text(schedule.calendarError).font(.caption).foregroundStyle(.orange) }
                                if let paper = schedule.calendarPapers.first,let url = URL(string:paper) { Link("查看节假日安排来源",destination:url).font(.caption) }
                            }
                            Button("更新节假日数据") { model.refreshCalendar() }.controlSize(.small).disabled(model.isOffDuty || model.isFinishingWorkday)
                            Text("下班后暂停到次日设定的开始时间（全天检测为次日零点），可提前上班。休息日和时段外仍可手动更新；下班暂停期间需先恢复。节假日数据每日刷新，离线时使用缓存。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    SettingsSection("分析与诊断", symbol: "sparkles") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("\(model.snapshot?.model ?? "gpt-6-luna") · \(model.snapshot?.effort ?? "max")").font(.headline).foregroundStyle(Palette.accent)
                            Text("复用本机 Codex 登录，每轮最多分析 6 个已变动对话，未变化时不调用模型。对话摘录会发送给该模型进行分析；常见密钥格式会预先遮蔽。")
                                .font(.caption).foregroundStyle(.secondary)
                            Text("使用连接设置中的模型。SSH 或模型失败时保留旧待办，并在下一轮重试。")
                                .font(.caption).foregroundStyle(.secondary)
                            Text("最近分析：\(relativeTime(model.snapshot?.lastAnalysis ?? 0))").font(.caption)
                            if !(model.snapshot?.modelError ?? "").isEmpty {
                                Text(model.snapshot?.modelError ?? "").font(.system(size: 10, design: .monospaced)).foregroundStyle(.orange).textSelection(.enabled)
                            }
                            if !model.error.isEmpty { Text(model.error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                            HStack {
                                Button("重新分析未结束对话") { model.sync(force: true) }.disabled(model.updateDisabled)
                                Button("打开数据文件夹") { NSWorkspace.shared.open(model.dataDirectory) }
                            }.controlSize(.small)
                        }
                    }
                }
            }
        }.padding(24).frame(width: 620, height: 760).background(Palette.canvas).foregroundStyle(Palette.ink).font(.system(size: 13)).buttonStyle(CoindexButtonStyle()).toggleStyle(.switch).controlSize(.small).tint(Palette.accent).environment(\.timeZone,TimeZone(identifier:"Asia/Shanghai")!)
    }

    private func settingPicker(_ label: String, value: Int, options: [(Int, String)], key: String) -> some View {
        HStack {
            Text(label)
            Spacer()
            Picker(label, selection: Binding(get: { value }, set: { model.settings([key: $0]) })) {
                ForEach(options, id: \.0) { option in Text(option.1).tag(option.0) }
            }.labelsHidden().frame(width: 210)
        }.font(.callout)
    }

    private func clockBinding(_ key: String,fallback: Int) -> Binding<Date> {
        var calendar = Calendar(identifier:.gregorian)
        calendar.timeZone = TimeZone(identifier:"Asia/Shanghai")!
        return Binding(get:{
            let minutes = key == "work_start_minutes" ? model.snapshot?.settings.workStartMinutes : model.snapshot?.settings.workEndMinutes
            let value = minutes ?? fallback
            return calendar.date(from:DateComponents(year:2026,month:1,day:1,hour:value/60,minute:value%60))!
        },set:{date in
            model.settings([key:calendar.component(.hour,from:date)*60+calendar.component(.minute,from:date)])
        })
    }
}

struct ManualTodoEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    @State private var title: String
    @State private var note: String
    @State private var priority: Int
    @State private var saving = false
    @State private var error = ""
    let task: TodoTask?

    init(task: TodoTask?) {
        self.task = task
        _title = State(initialValue:task?.title ?? "")
        _note = State(initialValue:task?.detail ?? "")
        _priority = State(initialValue:task?.priority ?? 2)
    }

    var body: some View {
        VStack(alignment:.leading,spacing:18) {
            Text(task == nil ? "新建待办" : "编辑待办").font(.title2).fontWeight(.semibold)
            TextField("要做什么？",text:$title).textFieldStyle(.plain).coindexInput()
            VStack(alignment:.leading,spacing:8) {
                Text("备注（可选）").font(.callout).foregroundStyle(.secondary)
                TextEditor(text:$note).font(.callout).scrollContentBackground(.hidden).frame(height:150).coindexInput()
            }
            Picker("优先级",selection:$priority) { Text("优先处理").tag(1);Text("一般").tag(2);Text("低优先").tag(3) }.pickerStyle(.segmented)
            if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange) }
            HStack {
                Text("无需关联对话").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction).disabled(saving)
                Button(saving ? "正在保存…" : "保存") {
                    saving = true
                    model.saveManual(title:title,detail:note,priority:priority) { message in
                        saving = false
                        if let message { error = message } else { dismiss() }
                    }
                }.buttonStyle(CoindexButtonStyle(prominent: true)).keyboardShortcut(.defaultAction)
                    .disabled(saving || title.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
            }
        }.padding(28).frame(width:540).background(Palette.canvas).foregroundStyle(Palette.ink).tint(Palette.accent).buttonStyle(CoindexButtonStyle())
    }
}
