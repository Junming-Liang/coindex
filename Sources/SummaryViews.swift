import AppKit
import SwiftUI

struct SummaryWorkspaceView: View {
    @EnvironmentObject var model: AppModel
    @State private var creating = false
    @State private var scheduling = false

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("总结").font(.system(size: 25, weight: .semibold)).tracking(-0.6)
                    Text("按专项汇报进展、结果与下一步，整理文档和配图。").font(.system(size: 12)).foregroundStyle(Palette.muted)
                }
                Spacer()
                Button { scheduling = true } label: {
                    Label("自动总结", systemImage: "calendar.badge.clock")
                }.accessibilityIdentifier("summary-schedule")
                Button { creating = true } label: {
                    Label("新建总结", systemImage: "plus")
                }.buttonStyle(CoindexButtonStyle(prominent: true)).accessibilityIdentifier("summary-create")
            }.padding(20).background(Palette.surface)
            HStack(spacing: 8) {
                Circle().fill(model.snapshot?.summarySchedule?.enabled == true ? Palette.success : Palette.muted).frame(width: 5, height: 5)
                Text(model.snapshot?.summarySchedule?.description ?? "自动总结未开启")
                    .font(.system(size: 11)).foregroundStyle(Palette.muted)
                Spacer()
                if model.snapshot?.summarySchedule?.enabled == true, let next = model.snapshot?.summarySchedule?.nextAt {
                    Text("下次：\(detectionTime(next))").font(.system(size: 11)).foregroundStyle(Palette.muted)
                }
            }.padding(.horizontal, 20).padding(.vertical, 12)
            Rectangle().fill(Palette.border).frame(height: 1)
            if model.summaries.isEmpty { emptyState }
            else {
                HStack(spacing: 0) {
                    history.frame(width: 224)
                    Rectangle().fill(Palette.border).frame(width: 1)
                    detail.frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .sheet(isPresented: $creating) { SummaryComposer() }
        .sheet(isPresented: $scheduling) { SummaryScheduleEditor(settings: model.snapshot?.summarySchedule ?? .defaults) }
        .onAppear {
            if model.selectedSummaryId == nil, let first = model.summaries.first { model.selectSummary(first.id) }
        }
        .onChange(of: creating) { _, value in model.summaryDialogPresented = value || scheduling }
        .onChange(of: scheduling) { _, value in model.summaryDialogPresented = value || creating }
        .onDisappear { model.summaryDialogPresented = false }
        .onChange(of: model.summaries.first?.id) { _, id in
            if model.selectedSummaryId == nil, let id { model.selectSummary(id) }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: "doc.text").font(.system(size: 28, weight: .light)).foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64).background(Palette.accentWash, in: RoundedRectangle(cornerRadius: 18))
            Text("把进展整理成一份总结").font(.system(size: 18, weight: .semibold))
            Text("选择待办和时间范围，整理专项进展、实验结论和相关产物。支持只总结工作内容。")
                .font(.system(size: 12)).foregroundStyle(Palette.muted).multilineTextAlignment(.center).frame(maxWidth: 330)
            Button("选择总结范围") { creating = true }.buttonStyle(CoindexButtonStyle(prominent: true))
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var history: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 6) {
                Text("最近 \(model.summaries.count) 份").font(.system(size: 10, weight: .medium)).foregroundStyle(Palette.muted).padding(.horizontal, 10).padding(.vertical, 8)
                ForEach(model.summaries) { summary in
                    Button { model.selectSummary(summary.id) } label: {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(summary.title).font(.system(size: 12, weight: .medium)).lineLimit(2).multilineTextAlignment(.leading)
                            Text("\(summary.includedCount) 条待办 · \(summary.statusTitle)")
                                .font(.system(size: 10)).foregroundStyle(summary.status == "failed" ? Color.orange : Palette.muted)
                            Text("\(summary.origin == "automatic" ? "自动" : "手动") · \(detectionTime(summary.createdAt))")
                                .font(.system(size: 10)).foregroundStyle(Palette.muted)
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(10)
                            .background(model.selectedSummaryId == summary.id ? Palette.accentWash : Color.clear, in: RoundedRectangle(cornerRadius: 8))
                    }.buttonStyle(HoverPlainStyle()).accessibilityIdentifier("summary-" + summary.id)
                }
            }.padding(10)
        }.background(Palette.sidebar.opacity(0.5))
    }

    @ViewBuilder private var detail: some View {
        if let summary = model.selectedSummary {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(summary.title).font(.system(size: 22, weight: .semibold)).textSelection(.enabled)
                        Text("\(summary.scopeTitle) · \(summary.includedCount) 条待办\(summary.workOnly == true ? " · 仅工作" : "")")
                            .font(.system(size: 11)).foregroundStyle(Palette.muted)
                        Text("\(summary.model) · \(summary.effort) · \(detectionTime(summary.createdAt))")
                            .font(.system(size: 10)).foregroundStyle(Palette.muted)
                    }
                    HStack(spacing: 8) {
                        if summary.pending {
                            ProgressView().controlSize(.small)
                            Text(summary.statusTitle).font(.callout)
                            Spacer()
                            Button("中止生成") { model.cancelSummary(summary.id) }.accessibilityIdentifier("summary-cancel")
                        } else if summary.status == "completed" {
                            Button { model.copy(model.summaryDetail?.content ?? "") } label: { Label("复制", systemImage: "doc.on.doc") }
                                .disabled(model.summaryDetail?.content.isEmpty != false)
                            Button { model.exportSummary() } label: { Label("导出 Markdown", systemImage: "square.and.arrow.up") }
                                .disabled(model.summaryDetail?.content.isEmpty != false)
                            Spacer()
                        } else {
                            Label(summary.statusTitle, systemImage: summary.status == "failed" ? "exclamationmark.triangle" : "stop.circle")
                                .font(.callout).foregroundStyle(summary.status == "failed" ? Color.orange : Palette.muted)
                        }
                    }
                    if summary.workOnly == true, !summary.pending {
                        Text("候选 \(summary.taskCount) 条，已排除 \(summary.excludedCount ?? 0) 条非工作待办；\(summary.uncertainCount ?? 0) 条归属不明，保留并标记待核对。")
                            .font(.caption).foregroundStyle(Palette.muted)
                    }
                    if !summary.error.isEmpty { Text(summary.error).font(.callout).foregroundStyle(.orange).textSelection(.enabled) }
                    if !model.summaryError.isEmpty {
                        Text(model.summaryError).font(.callout).foregroundStyle(.orange)
                        Button("重新加载") { model.loadSummary(summary.id) }
                    }
                    if model.summaryLoading { ProgressView("正在读取总结…").controlSize(.small) }
                    if let report = model.summaryDetail, report.id == summary.id {
                        if !report.content.isEmpty { CoindexMarkdown(content: report.content) }
                        if !report.sources.isEmpty {
                            Divider()
                            DisclosureGroup("参与总结的 \(report.sources.filter { $0.relevance != "non_work" }.count) 条待办") {
                                VStack(alignment: .leading, spacing: 12) {
                                    Text("按生成时保存的记录回顾；后续待办变化不会改写这份总结。")
                                        .font(.caption).foregroundStyle(Palette.muted)
                                    ForEach(report.sources.filter { $0.relevance != "non_work" }) { source in sourceRow(source) }
                                }.padding(.top, 12).frame(maxWidth: .infinity, alignment: .leading)
                            }.font(.system(size: 12, weight: .medium))
                            if report.sources.contains(where: { $0.relevance == "non_work" }) {
                                DisclosureGroup("已排除的非工作待办（\(report.sources.filter { $0.relevance == "non_work" }.count) 条）") {
                                    VStack(alignment: .leading, spacing: 12) {
                                        ForEach(report.sources.filter { $0.relevance == "non_work" }) { source in sourceRow(source) }
                                    }.padding(.top, 12).frame(maxWidth: .infinity, alignment: .leading)
                                }.font(.system(size: 12, weight: .medium))
                            }
                        }
                    }
                    if summary.pending { Text("生成在后台继续，可切换到其他待办。退出 App 会中断生成。")
                        .font(.caption).foregroundStyle(Palette.muted) }
                    Text("基于本地保存的待办记录；时间段筛选新增、更新或完成的待办，进展以生成时记录为准。")
                        .font(.system(size: 10)).foregroundStyle(Palette.muted)
                }.frame(maxWidth: 760, alignment: .leading).padding(24).frame(maxWidth: .infinity, alignment: .leading)
            }
        } else { Text("选择一份总结查看").foregroundStyle(Palette.muted) }
    }
    private func sourceRow(_ source: SummarySource) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(source.title).font(.system(size: 12, weight: .medium))
            Text("\(summaryStatusTitle(source.status))\(source.conversationArchived == true ? " · 已归档" : "")\(source.host.map { " · \(model.hostName($0))" } ?? "")")
                .font(.system(size: 10)).foregroundStyle(Palette.muted)
            if source.relevance == "uncertain" { Text("工作归属待核对").font(.caption).foregroundStyle(.orange) }
            if let reason = source.relevanceReason, !reason.isEmpty { Text(reason).font(.caption).foregroundStyle(Palette.muted) }
            if source.relevance != "non_work" {
                if let progress = source.progress, !progress.isEmpty { Text(progress).font(.caption).foregroundStyle(Palette.muted) }
                if let next = source.nextAction, !next.isEmpty { Text("下一步：\(next)").font(.caption) }
            }
        }.textSelection(.enabled)
    }
}

struct SummaryComposer: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var scope = "active"
    @State private var preset = "1"
    @State private var startDate = Date()
    @State private var endDate = Date()
    @State private var workOnly = false
    @State private var workContext = ""
    @State private var preview: SummaryPreview?
    @State private var busy = false
    @State private var error = ""

    private var values: [String: Any] {
        var result: [String: Any] = ["scope": scope, "work_only": workOnly, "work_context": workContext]
        if scope == "period" {
            if preset == "custom" {
                result["start_date"] = SummaryDates.string(startDate)
                result["end_date"] = SummaryDates.string(endDate)
            } else { result["days"] = Int(preset) ?? 1 }
        }
        return result
    }
    private var valid: Bool { scope != "period" || preset != "custom" || SummaryDates.string(startDate) <= SummaryDates.string(endDate) }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text(preview == nil ? "总结什么？" : "确认总结范围").font(.system(size: 22, weight: .semibold))
                Spacer()
                Text(preview == nil ? "1 / 2" : "2 / 2").font(.caption).foregroundStyle(Palette.muted)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let preview { confirmation(preview) }
                    else { selection }
                    if !error.isEmpty { Text(error).font(.callout).foregroundStyle(.orange).textSelection(.enabled) }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 420)
            HStack {
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction).disabled(busy)
                Spacer()
                if preview != nil { Button("上一步") { preview = nil; error = "" }.disabled(busy) }
                Button(busy ? "请稍候…" : preview == nil ? "预览范围" : "开始生成") {
                    busy = true
                    error = ""
                    if preview == nil {
                        model.previewSummary(values) { result, message in
                            busy = false
                            preview = result
                            error = message ?? ""
                        }
                    } else {
                        model.generateSummary(values) { message in
                            busy = false
                            if let message { error = message } else { dismiss() }
                        }
                    }
                }.buttonStyle(CoindexButtonStyle(prominent: true)).keyboardShortcut(.defaultAction)
                    .disabled(busy || !valid || model.isDemo || preview?.taskCount == 0 || model.summaryPending)
                    .accessibilityIdentifier("summary-generate")
            }
            if model.summaryPending { Text("已有一份总结正在生成，完成或中止后可再创建。").font(.caption).foregroundStyle(Palette.muted) }
            if model.isDemo { Text("演示模式仅供预览，请在正常模式生成总结。").font(.caption).foregroundStyle(Palette.muted) }
        }.padding(28).frame(width: 540).background(Palette.canvas).foregroundStyle(Palette.ink)
            .buttonStyle(CoindexButtonStyle()).toggleStyle(.switch).tint(Palette.accent).environment(\.timeZone, SummaryDates.calendar.timeZone)
    }

    private var selection: some View {
        VStack(alignment: .leading, spacing: 16) {
            scopeOption("active", title: "所有未完成待办", detail: "包括进行中、等待结果、需要决定、稍后处理等未完成待办。")
            scopeOption("all", title: "全部已保存任务（含完成、归档）", detail: "查看所有机器的历史任务，包括已完成、已结束及归档对话的任务。")
            scopeOption("period", title: "一个时间段的全部待办", detail: "汇总期间新增、更新或完成的待办，包含已完成、已归档和手动任务。")
            if scope == "period" {
                Picker("时间段", selection: $preset) {
                    Text("今天").tag("1"); Text("近 3 天").tag("3"); Text("近一周").tag("7"); Text("自定义").tag("custom")
                }.pickerStyle(.segmented)
                if preset == "custom" {
                    HStack {
                        DatePicker("开始", selection: $startDate, in: ...Date(), displayedComponents: .date)
                        DatePicker("结束", selection: $endDate, in: ...Date(), displayedComponents: .date)
                    }.font(.callout)
                    if !valid { Text("结束日期不能早于开始日期。").font(.caption).foregroundStyle(.orange) }
                }
                Text("按北京时间计算，包含开始和结束当天；近 3 天与近一周包含今天。")
                    .font(.caption).foregroundStyle(Palette.muted)
            }
            Divider()
            Toggle("只总结工作内容", isOn: $workOnly)
            if workOnly {
                TextField("工作项目 / 关键词或排除范围（可选）", text: $workContext).textFieldStyle(.plain).coindexInput()
                Text("自动排除个人开源项目、自制 App 等非工作内容；归属不明的保留并标记待核对。")
                    .font(.caption).foregroundStyle(Palette.muted)
            }
        }
    }

    private func scopeOption(_ value: String, title: String, detail: String) -> some View {
        Button { scope = value } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: scope == value ? "largecircle.fill.circle" : "circle").foregroundStyle(scope == value ? Palette.accent : Palette.muted)
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.system(size: 13, weight: .semibold))
                    Text(detail).font(.system(size: 11)).foregroundStyle(Palette.muted).multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
            }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
                .background(scope == value ? Palette.accentWash : Palette.surface, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(scope == value ? Palette.accent.opacity(0.4) : Palette.border))
        }.buttonStyle(HoverPlainStyle()).accessibilityAddTraits(scope == value ? .isSelected : [])
    }

    private func confirmation(_ preview: SummaryPreview) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(preview.title).font(.headline)
            Text("\(preview.taskCount) 条\(workOnly ? "候选待办" : "待办")").font(.system(size: 28, weight: .semibold)).foregroundStyle(Palette.accent)
            if scope == "period" {
                Text("\(preview.startDate) — \(preview.endDate)（含首尾日期）").font(.callout)
            } else { Text(scope == "all" ? "全部机器、全部已保存任务，包含已完成和已归档任务。" : "全部机器、全部未完成待办，包含稍后处理。").font(.callout) }
            ForEach(preview.counts.keys.sorted(), id: \.self) { status in
                HStack { Text(summaryStatusTitle(status)); Spacer(); Text("\(preview.counts[status] ?? 0)") }.font(.callout).foregroundStyle(Palette.muted)
            }
            if let count = preview.archivedCount, count > 0 {
                Text("已包含 \(count) 条归档对话的任务。").font(.caption).foregroundStyle(Palette.muted)
            }
            if preview.taskCount == 0 { Text("这个范围暂无待办，请返回选择其他时间。").font(.callout).foregroundStyle(Palette.muted) }
            if workOnly { Text("这是筛选前的数量；生成时识别工作内容，并保留排除原因供核对。").font(.caption).foregroundStyle(Palette.muted) }
            Text("按专项整理进展、结果与结论；有记录时附下一步、风险及文档和图片。未验证结果会明确标注。")
                .font(.caption).foregroundStyle(Palette.muted)
            Text("使用 \(model.snapshot?.model ?? "gpt-6-luna") · \(model.snapshot?.effort ?? "max")，保留生成时的独立副本。")
                .font(.caption).foregroundStyle(Palette.muted)
        }.padding(18).background(Palette.surface, in: RoundedRectangle(cornerRadius: 12))
    }
}

struct SummaryScheduleEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var settings: SummarySchedule
    @State private var saving = false
    @State private var error = ""
    init(settings: SummarySchedule) { _settings = State(initialValue: settings) }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("自动总结").font(.system(size: 22, weight: .semibold))
            Toggle("自动生成并保存总结", isOn: $settings.enabled)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 16) {
                        Picker("频率", selection: $settings.frequency) {
                            Text("每天").tag("daily"); Text("每周").tag("weekly"); Text("固定间隔").tag("interval")
                        }.pickerStyle(.segmented)
                        if settings.frequency == "weekly" {
                            Picker("每周", selection: $settings.weekday) {
                                ForEach(Array(["一", "二", "三", "四", "五", "六", "日"].enumerated()), id: \.offset) { day in Text("星期\(day.element)").tag(day.offset) }
                            }
                        }
                        if settings.frequency == "interval" {
                            Stepper("每 \(settings.intervalHours) 小时", value: $settings.intervalHours, in: 1...168)
                        } else { DatePicker("生成时间 · 北京时间", selection: timeBinding, displayedComponents: .hourAndMinute) }
                        Divider()
                        Picker("总结范围", selection: $settings.scope) {
                            Text("所有未完成待办").tag("active"); Text("最近一段时间的全部待办").tag("period")
                            Text("全部已保存任务（含完成、归档）").tag("all")
                        }
                        if settings.scope == "period" { Stepper("近 \(settings.days) 天（包含当天）", value: $settings.days, in: 1...366) }
                        Toggle("只总结工作内容", isOn: $settings.workOnly)
                        if settings.workOnly {
                            TextField("工作项目 / 关键词或排除范围（可选）", text: $settings.workContext).textFieldStyle(.plain).coindexInput()
                            Text("排除明确的非工作内容；归属不明的保留并标记待核对。").font(.caption).foregroundStyle(Palette.muted)
                        }
                        Toggle("仅法定工作日（含调休）", isOn: $settings.workdaysOnly)
                    }.font(.callout).disabled(!settings.enabled)
                    Text("App 运行时自动生成；下班期间暂停。退出或休眠时不会生成，恢复后按计划检查，不补发所有错过的总结。")
                        .font(.caption).foregroundStyle(Palette.muted)
                    if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange) }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 360)
            HStack {
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction).disabled(saving)
                Spacer()
                Button(saving ? "保存中…" : "保存设置") {
                    saving = true
                    model.saveSummarySettings(settings.values) { message in
                        saving = false
                        if let message { error = message } else { dismiss() }
                    }
                }.buttonStyle(CoindexButtonStyle(prominent: true)).keyboardShortcut(.defaultAction).disabled(saving || model.isDemo)
            }
        }.padding(28).frame(width: 540).background(Palette.canvas).foregroundStyle(Palette.ink).tint(Palette.accent)
            .buttonStyle(CoindexButtonStyle()).toggleStyle(.switch).environment(\.timeZone, SummaryDates.calendar.timeZone)
    }

    private var timeBinding: Binding<Date> {
        Binding(get: {
            SummaryDates.calendar.date(from: DateComponents(year: 2026, month: 1, day: 1, hour: settings.timeMinutes / 60, minute: settings.timeMinutes % 60))!
        }, set: { date in
            settings.timeMinutes = SummaryDates.calendar.component(.hour, from: date) * 60 + SummaryDates.calendar.component(.minute, from: date)
        })
    }
}

struct CoindexMarkdown: View {
    let content: String
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(Array(content.components(separatedBy: .newlines).enumerated()), id: \.offset) { line in
                let text = line.element
                if text.hasPrefix("### ") { paragraph(String(text.dropFirst(4)), size: 14, weight: .semibold).padding(.top, 8) }
                else if text.hasPrefix("## ") { paragraph(String(text.dropFirst(3)), size: 16, weight: .semibold).padding(.top, 12) }
                else if text.hasPrefix("# ") { paragraph(String(text.dropFirst(2)), size: 19, weight: .semibold).padding(.top, 12) }
                else if text == "---" { Divider().padding(.vertical, 8) }
                else if text.isEmpty { Spacer().frame(height: 3) }
                else if let image = SummaryMarkdownImage(text) { SummaryArtifactImage(image: image) }
                else if text.hasPrefix("- ") || text.hasPrefix("* ") {
                    HStack(alignment: .top, spacing: 8) { Text("•"); paragraph(String(text.dropFirst(2))) }.padding(.leading, 4)
                } else { paragraph(text) }
            }
        }.textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
    }
    private func paragraph(_ text: String, size: CGFloat = 13, weight: Font.Weight = .regular) -> some View {
        Text((try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text))
            .font(.system(size: size, weight: weight)).lineSpacing(4).fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct SummaryMarkdownImage {
    let caption: String
    let url: URL

    init?(_ text: String) {
        guard text.hasPrefix("!["), text.hasSuffix(")"), let separator = text.range(of: "](", options: .backwards) else { return nil }
        caption = String(text[text.index(text.startIndex, offsetBy: 2)..<separator.lowerBound])
        let destination = String(text[separator.upperBound..<text.index(before: text.endIndex)])
        if destination.hasPrefix("/"), !destination.hasPrefix("//"), let path = destination.removingPercentEncoding {
            url = URL(fileURLWithPath: path)
        } else if let value = URL(string: destination), ["http", "https"].contains(value.scheme?.lowercased() ?? ""), value.host != nil {
            url = value
        } else { return nil }
    }
}

private struct SummaryArtifactImage: View {
    let image: SummaryMarkdownImage

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if image.url.isFileURL {
                if let loaded = NSImage(contentsOf: image.url) { preview(Image(nsImage: loaded)) }
                else { unavailable }
            } else {
                AsyncImage(url: image.url) { phase in
                    if let loaded = phase.image { preview(loaded) }
                    else if phase.error != nil { unavailable }
                    else { ProgressView().controlSize(.small).padding(12) }
                }
            }
            Text((try? AttributedString(markdown: image.caption)) ?? AttributedString(image.caption))
                .font(.caption).foregroundStyle(Palette.muted)
            Link("打开原图", destination: image.url).font(.caption)
        }.padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading)
    }

    private func preview(_ value: Image) -> some View {
        value.resizable().scaledToFit().frame(maxWidth: 660, maxHeight: 360, alignment: .leading)
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private var unavailable: some View {
        Label("图片暂不可预览，可打开原图查看", systemImage: "photo")
            .font(.caption).foregroundStyle(Palette.muted)
    }
}

private func summaryStatusTitle(_ status: String) -> String {
    ["open": "未完成", "completed": "已完成", "done": "手动完成", "resolved": "已解决", "dismissed": "已忽略", "archived": "已归档", "closed": "已结束", "conversation_closed": "对话已结束", "conversation_archived": "对话已归档"][status] ?? status
}
