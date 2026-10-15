import AppKit
import Combine
import Foundation

@MainActor
final class AppModel: ObservableObject {
    @Published var snapshot: Snapshot?
    @Published var error = ""
    @Published var filter = "all"
    @Published var hostFilter = "all"
    @Published var search = ""
    @Published var selectedTaskId: String?
    @Published var showSettings = false
    @Published var showPetSettings = false
    @Published var selectedSummaryId: String?
    @Published var summaryDetail: SummaryDetail?
    @Published var summaryLoading = false
    @Published var summaryError = ""
    @Published var summaryDialogPresented = false
    @Published var showAppUpdate = false
    @Published var appUpdateMessage = ""
    @Published private(set) var checkingAppUpdate = false
    private var didCheckAppUpdate = false
    private var manuallyCheckingAppUpdate = false
    private var observedUpdateChecking = false
    private var updateCheckBaseline: Double = 0
    private var presentedUpdateVersions: Set<String> = []
    let pet = PetController()
    var reopenMainWindow: (() -> Void)?
    @Published var showManualEditor = false
    var manualEditingTask: TodoTask?
    @Published var showTitleEditor = false
    var titleEditingTask: TodoTask?
    @Published var toast = ""
    @Published var isCancelling = false
    @Published var isFinishingWorkday = false
    @Published private var requestingNudges: Set<String> = []
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var timer: Timer?
    private var requestId = 0
    private var callbacks: [Int: (Data) -> Void] = [:]
    private var failures: [Int: (String) -> Void] = [:]
    private var awaitingSync = false
    private var didOfferConnectionSetup = false
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
    let dataDirectory: URL
    let isDemo: Bool

    init() {
        isDemo = ProcessInfo.processInfo.arguments.contains("--demo")
        let overridden = ProcessInfo.processInfo.environment["CODEX_TODO_DATA_DIR"]
        dataDirectory = URL(fileURLWithPath: overridden ?? NSHomeDirectory() + "/Library/Application Support/CodexTodo")
        if isDemo {
            if let path = Bundle.main.url(forResource: "demo", withExtension: "json"),
               let data = try? Data(contentsOf: path) {
                snapshot = try? decoder.decode(Snapshot.self, from: data)
            }
            return
        }
        start()
    }

    var appVersion: String { snapshot?.appUpdate?.currentVersion ?? Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "开发版" }
    var appUpdateChecksDisabled: Bool {
        isDemo || ProcessInfo.processInfo.arguments.contains("--test") ||
        ProcessInfo.processInfo.environment["COINDEX_DISABLE_UPDATE_CHECK"] == "1" ||
        ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
    }
    var summaries: [TodoSummary] { snapshot?.summaries ?? [] }
    var selectedSummary: TodoSummary? { summaries.first { $0.id == selectedSummaryId } }
    var summaryPending: Bool { summaries.contains { $0.pending } }
    var syncing: Bool { isCancelling || awaitingSync || snapshot?.sync.running == true }
    var isOffDuty: Bool { snapshot?.schedule?.offDuty == true }
    var updateDisabled: Bool { syncing || isOffDuty || isFinishingWorkday || isDemo }
    var openCount: Int { snapshot?.tasks.filter { $0.isOpen && !$0.isSnoozed }.count ?? 0 }
    var selectedTask: TodoTask? { snapshot?.tasks.first { $0.id == selectedTaskId } }
    var tasks: [TodoTask] { filteredTasks(for: filter) }

    private func filteredTasks(for filter: String) -> [TodoTask] {
        (snapshot?.tasks ?? []).filter { task in
            let stateMatches: Bool
            if filter == "completed" { stateMatches = !task.isOpen }
            else if filter == "snoozed" { stateMatches = task.isOpen && task.isSnoozed }
            else { stateMatches = task.isOpen && !task.isSnoozed && (filter == "all" || task.kind == filter) }
            let text = task.title + task.detail + task.conversationTitle + task.artifact
            return stateMatches && (hostFilter == "all" || task.host == hostFilter) && (search.isEmpty || text.localizedCaseInsensitiveContains(search))
        }
    }

    func count(_ kind: String) -> Int {
        filteredTasks(for: kind).count
    }

    private func start() {
        guard let script = Bundle.main.url(forResource: "service", withExtension: "py", subdirectory: "backend") else {
            error = "App 包中缺少采集服务，请重新运行构建脚本。"
            return
        }
        let proc = Process()
        let readPipe = Pipe()
        let writePipe = Pipe()
        let errors = Pipe()
        // System Python is present on this Mac; support Homebrew and a custom runtime too.
        let candidates = [ProcessInfo.processInfo.environment["CODEX_TODO_PYTHON"] ?? "", "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        guard let python = candidates.first(where: { !$0.isEmpty && FileManager.default.isExecutableFile(atPath: $0) }) else {
            error = "找不到 Python 3，安装后重新打开 App。"
            return
        }
        proc.executableURL = URL(fileURLWithPath: python)
        proc.arguments = [script.path, "--data-dir", dataDirectory.path, "serve"]
        proc.standardInput = writePipe
        proc.standardOutput = readPipe
        proc.standardError = errors
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment.removeValue(forKey: "CODEX_SANDBOX_NETWORK_DISABLED")
        environment.removeValue(forKey: "CODEX_THREAD_ID")
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + (environment["PATH"] ?? "")
        proc.environment = environment
        errors.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
        let buffer = LineBuffer()
        readPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            for line in buffer.append(data) {
                Task { @MainActor [weak self] in self?.receive(line) }
            }
        }
        proc.terminationHandler = { [weak self] process in
            Task { @MainActor [weak self] in
                self?.awaitingSync = false
                self?.isCancelling = false
                if process.terminationStatus != 0 {
                    self?.error = "采集服务已停止（\(process.terminationStatus)）。退出并重新打开 App 可恢复。"
                }
            }
        }
        do {
            try proc.run()
            process = proc
            input = writePipe.fileHandleForWriting
            output = readPipe.fileHandleForReading
            refresh()
            timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in self?.tick() }
            }
        } catch { self.error = "采集服务无法启动：\(error.localizedDescription)" }
    }

    private func request(_ method: String, values: [String: Any] = [:], failure: ((String) -> Void)? = nil, completion: ((Data) -> Void)? = nil) {
        guard let input, process?.isRunning == true else {
            failure?("采集服务未运行，请重新打开 App。")
            return
        }
        requestId += 1
        var request = values
        request["id"] = requestId
        request["method"] = method
        if let completion { callbacks[requestId] = completion }
        if let failure { failures[requestId] = failure }
        do {
            var data = try JSONSerialization.data(withJSONObject: request)
            data.append(10)
            try input.write(contentsOf: data)
        } catch {
            callbacks.removeValue(forKey: requestId)
            failures.removeValue(forKey: requestId)?(error.localizedDescription)
            self.error = error.localizedDescription
        }
    }

    private func receive(_ data: Data) {
        guard let envelope = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        guard let id = envelope["id"] as? Int else { return }
        let callback = callbacks.removeValue(forKey: id)
        let failure = failures.removeValue(forKey: id)
        if let error = envelope["error"] as? String {
            self.error = error
            failure?(error)
            return
        }
        if let callback, let result = envelope["result"], let resultData = try? JSONSerialization.data(withJSONObject: result) {
            callback(resultData)
        }
    }

    func refresh(checkAutomatic: Bool = false) {
        request("snapshot", completion: { [weak self] data in
            guard let self else { return }
            do {
                self.applySnapshot(try self.decoder.decode(Snapshot.self, from: data))
                if !self.didOfferConnectionSetup {
                    self.didOfferConnectionSetup = true
                    if self.snapshot?.settings.connectionSetupComplete == false { self.showSettings = true }
                }
                self.error = ""
                if !self.didCheckAppUpdate, !self.appUpdateChecksDisabled {
                    self.didCheckAppUpdate = true
                    self.checkForAppUpdates(automatic: true)
                }
                if checkAutomatic, self.snapshot?.settings.connectionSetupComplete != false, self.snapshot?.schedule?.due == true, !self.updateDisabled { self.sync(automatic:true) }
            } catch { self.error = "无法读取待办数据：\(error.localizedDescription)" }
        })
    }

    private func tick() {
        refresh(checkAutomatic:true)
    }

    private func applySnapshot(_ value: Snapshot) {
        let prior = Dictionary(uniqueKeysWithValues: (snapshot?.nudges ?? []).map { ($0.id, $0.status) })
        if snapshot != nil {
            for record in value.nudges ?? [] where prior[record.id] != record.status {
                if record.status == "sent" { showToast("催办已送达原对话") }
                else if record.status == "failed" || record.status == "unknown" { showToast(record.summary) }
            }
        }
        let oldSummary = selectedSummary
        snapshot = value
        receiveAppUpdate(value.appUpdate)
        if let selected = selectedSummary,
           oldSummary?.status != selected.status || oldSummary?.finishedAt != selected.finishedAt {
            loadSummary(selected.id)
        }
    }

    func latestNudge(_ task: TodoTask) -> NudgeRecord? {
        snapshot?.nudges?.first { $0.conversationId == task.conversationId }
    }

    func nudgePending(_ task: TodoTask) -> Bool {
        requestingNudges.contains(task.conversationId) || latestNudge(task)?.pending == true
    }

    func nudgeDisabled(_ task: TodoTask) -> Bool {
        if isDemo || !task.isOpen || task.isManual || nudgePending(task) { return true }
        guard let record = latestNudge(task) else { return false }
        return record.status == "unknown" || (record.status == "sent" && Date().timeIntervalSince1970 - record.updatedAt < 30)
    }

    func nudge(_ task: TodoTask, retryUnknown: Bool = false) {
        guard !isDemo, task.isOpen, !task.isManual, !nudgePending(task) else { return }
        requestingNudges.insert(task.conversationId)
        let values: [String:Any] = ["entity_id":task.id,"action_id":UUID().uuidString.lowercased(),"retry_unknown":retryUnknown]
        request("nudge", values:values, failure: { [weak self] message in
            self?.requestingNudges.remove(task.conversationId)
            self?.showToast(message)
        }) { [weak self] data in
            guard let self else { return }
            self.requestingNudges.remove(task.conversationId)
            do { self.applySnapshot(try self.decoder.decode(Snapshot.self,from:data)) }
            catch { self.error = "催办状态读取失败，请先核对原对话"; self.refresh() }
        }
    }

    func sync(force: Bool = false, automatic: Bool = false) {
        guard !updateDisabled else { return }
        awaitingSync = true
        request("sync", values: ["force": force,"automatic":automatic], failure: { [weak self] message in
            self?.awaitingSync = false
            self?.error = message
        }) { [weak self] _ in
            self?.awaitingSync = false
            self?.refresh()
        }
    }

    func toggleWorkday() {
        guard !isDemo, !isFinishingWorkday else { return }
        let resuming = isOffDuty
        isFinishingWorkday = true
        request(resuming ? "resume_workday" : "finish_workday", failure: { [weak self] message in
            self?.isFinishingWorkday = false
            self?.showToast(message)
        }) { [weak self] data in
            guard let self else { return }
            self.isFinishingWorkday = false
            self.awaitingSync = false
            self.isCancelling = false
            do {
                self.applySnapshot(try self.decoder.decode(Snapshot.self,from:data))
                self.showToast(resuming ? "已结束下班暂停" : "已下班，\(detectionTime(self.snapshot?.schedule?.offDutyUntil)) 恢复检测")
            } catch { self.error = "无法读取下班状态：\(error.localizedDescription)"; self.refresh() }
        }
    }

    func cancelSync() {
        guard !isDemo, !isCancelling else { return }
        isCancelling = true
        request("cancel_sync", failure: { [weak self] message in
            self?.isCancelling = false
            self?.error = "中止请求未完成：\(message)"
        }) { [weak self] data in
            guard let self else { return }
            do {
                self.snapshot = try self.decoder.decode(Snapshot.self, from: data)
                self.awaitingSync = false
                self.isCancelling = false
                self.showToast(self.snapshot?.sync.cancelled == true ? "已中止更新，自动更新已暂停" : "自动更新已暂停")
            } catch {
                self.isCancelling = false
                self.error = "中止请求未完成：\(error.localizedDescription)"
            }
        }
    }

    func act(_ action: String, id: String, value: Int? = nil) {
        guard !isDemo else { showToast("演示数据仅用于预览；实际任务在正常模式处理。"); return }
        var values: [String: Any] = ["action": action, "entity_id": id]
        if let value { values["value"] = value }
        request("act", values: values, completion: { [weak self] data in
            guard let self else { return }
            self.snapshot = try? self.decoder.decode(Snapshot.self, from: data)
            self.showToast(["complete": "待办已完成", "dismiss": "待办已忽略", "snooze": "一小时后再提醒", "close_conversation": "对话已结束，后续扫描将跳过", "reopen_conversation": "对话已恢复跟踪", "reopen": "待办已恢复"][action] ?? "已保存")
        })
    }

    func settings(_ values: [String: Any]) {
        guard !isDemo else { return }
        request("settings", values: ["values": values], completion: { [weak self] data in
            guard let self else { return }
            self.snapshot = try? self.decoder.decode(Snapshot.self, from: data)
        })
    }

    func refreshCalendar() {
        guard !isOffDuty, !isFinishingWorkday else { return }
        request("refresh_calendar",completion: { [weak self] _ in self?.showToast("正在获取节假日和调休安排") })
    }

    func editManual(_ task: TodoTask? = nil) {
        manualEditingTask = task
        showSettings = false
        showTitleEditor = false
        showManualEditor = true
    }

    func editTitle(_ task: TodoTask) {
        titleEditingTask = task
        showSettings = false
        showManualEditor = false
        showTitleEditor = true
    }

    func saveTitle(title: String, completion: @escaping (String?) -> Void) {
        guard !isDemo else { completion("演示模式无法保存标题"); return }
        guard let task = titleEditingTask else { completion("请重新选择待办"); return }
        request("rename_task", values:["entity_id":task.id,"title":title], failure:{ completion($0) }) { [weak self] data in
            guard let self else { return }
            do {
                let result = try self.decoder.decode(TaskSaveResult.self,from:data)
                self.snapshot = result.snapshot
                self.selectedTaskId = result.taskId
                self.showToast(task.isManual ? "标题已保存" : "标题已保存，自动更新不会覆盖")
                completion(nil)
            } catch { completion(error.localizedDescription) }
        }
    }

    func saveManual(title: String, detail: String, priority: Int, completion: @escaping (String?) -> Void) {
        if isDemo { completion("演示模式无法保存待办"); return }
        var values: [String:Any] = ["title":title,"detail":detail,"priority":priority]
        if let task = manualEditingTask { values["entity_id"] = task.id }
        request("save_manual",values:values,failure: { completion($0) }) { [weak self] data in
            guard let self else { return }
            do {
                let result = try self.decoder.decode(TaskSaveResult.self,from:data)
                self.snapshot = result.snapshot
                self.selectedTaskId = result.taskId
                self.filter = result.snapshot.tasks.first(where:{$0.id==result.taskId})?.isOpen == true ? "manual" : "completed"
                self.hostFilter = "all"
                self.showToast("待办已保存")
                completion(nil)
            } catch { completion(error.localizedDescription) }
        }
    }

    func checkForAppUpdates(automatic: Bool = false) {
        guard !appUpdateChecksDisabled, !checkingAppUpdate else { return }
        didCheckAppUpdate = true
        checkingAppUpdate = true
        manuallyCheckingAppUpdate = !automatic
        observedUpdateChecking = false
        updateCheckBaseline = snapshot?.appUpdate?.checkedAt ?? 0
        appUpdateMessage = "正在检查版本更新…"
        request("check_updates", values: ["automatic": automatic], failure: { [weak self] message in
            guard let self else { return }
            self.checkingAppUpdate = false
            self.manuallyCheckingAppUpdate = false
            self.appUpdateMessage = "检查失败：" + message
            if !automatic { self.showToast(self.appUpdateMessage) }
        }) { [weak self] _ in self?.refresh() }
    }

    private func receiveAppUpdate(_ update: AppUpdate?) {
        guard let update, !appUpdateChecksDisabled, didCheckAppUpdate else { return }
        if update.checking {
            checkingAppUpdate = true
            observedUpdateChecking = true
            return
        }
        if checkingAppUpdate {
            guard observedUpdateChecking || update.checkedAt > updateCheckBaseline else { return }
            checkingAppUpdate = false
            if !update.error.isEmpty {
                appUpdateMessage = "检查失败：" + update.error
                if manuallyCheckingAppUpdate { showToast(appUpdateMessage) }
                manuallyCheckingAppUpdate = false
                return
            }
            appUpdateMessage = update.available ? "发现新版本 \(update.version)" : "已是最新版本"
            if manuallyCheckingAppUpdate {
                if update.available {
                    presentedUpdateVersions.remove(update.version)
                    if showSettings { showSettings = false }
                } else { showToast("已是最新版本 \(update.currentVersion)") }
                manuallyCheckingAppUpdate = false
            }
        }
        presentAppUpdateIfReady()
    }

    func presentAppUpdateIfReady() {
        guard !appUpdateChecksDisabled, !checkingAppUpdate, let update = snapshot?.appUpdate,
              update.available, update.shouldPrompt, !update.version.isEmpty,
              !presentedUpdateVersions.contains(update.version), !showAppUpdate,
              !showSettings, !showPetSettings, !showManualEditor, !showTitleEditor, !summaryDialogPresented else { return }
        // Allow a settings sheet to finish dismissing before opening release notes.
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(350))
            guard let self, !self.showSettings, !self.showPetSettings, !self.showManualEditor,
                  !self.showTitleEditor, !self.summaryDialogPresented, !self.showAppUpdate, !self.checkingAppUpdate,
                  self.snapshot?.appUpdate?.version == update.version,
                  self.snapshot?.appUpdate?.shouldPrompt == true,
                  !self.presentedUpdateVersions.contains(update.version) else { return }
            self.presentedUpdateVersions.insert(update.version)
            self.showAppUpdate = true
        }
    }

    func skipAppUpdate(completion: @escaping (String?) -> Void) {
        guard let update = snapshot?.appUpdate, !appUpdateChecksDisabled else { completion("没有可跳过的版本"); return }
        request("skip_update", values: ["version": update.version], failure: { completion($0) }) { [weak self] data in
            guard let self else { return }
            do {
                self.applySnapshot(try self.decoder.decode(Snapshot.self, from: data))
                self.showAppUpdate = false
                self.appUpdateMessage = "已跳过 \(update.version)，下个版本再提醒"
                completion(nil)
            } catch { completion(error.localizedDescription) }
        }
    }

    func downloadAppUpdate(completion: @escaping (String?) -> Void) {
        guard let update = snapshot?.appUpdate, !appUpdateChecksDisabled else { completion("没有可下载的版本"); return }
        request("open_update", values: ["version": update.version], failure: { completion($0) }) { [weak self] _ in
            self?.showAppUpdate = false
            self?.showToast((update.downloadUrl.isEmpty || update.downloadUrl == update.url) ? "已打开发布页，请查看适用于这台 Mac 的安装包" : "已打开下载链接，下载完成后安装新版")
            completion(nil)
        }
    }

    func selectSummary(_ id: String) {
        guard selectedSummaryId != id || summaryDetail == nil else { return }
        selectedSummaryId = id
        summaryDetail = nil
        loadSummary(id)
    }

    func loadSummary(_ id: String) {
        guard !isDemo else { summaryLoading = false; return }
        summaryLoading = true
        summaryError = ""
        request("summary_detail", values: ["summary_id": id], failure: { [weak self] message in
            guard let self, self.selectedSummaryId == id else { return }
            self.summaryLoading = false
            self.summaryError = message
        }) { [weak self] data in
            guard let self, self.selectedSummaryId == id else { return }
            self.summaryLoading = false
            do { self.summaryDetail = try self.decoder.decode(SummaryDetail.self, from: data) }
            catch { self.summaryError = "无法读取总结：\(error.localizedDescription)" }
        }
    }

    func previewSummary(_ values: [String: Any], completion: @escaping (SummaryPreview?, String?) -> Void) {
        guard !isDemo else { completion(nil, "演示模式不会调用模型；请在正常模式生成总结。"); return }
        request("summary_preview", values: values, failure: { completion(nil, $0) }) { [weak self] data in
            guard let self else { return }
            do { completion(try self.decoder.decode(SummaryPreview.self, from: data), nil) }
            catch { completion(nil, "无法预览总结范围：\(error.localizedDescription)") }
        }
    }

    func generateSummary(_ values: [String: Any], completion: @escaping (String?) -> Void) {
        guard !isDemo else { completion("演示模式不会调用模型"); return }
        request("summary_generate", values: values, failure: { completion($0) }) { [weak self] data in
            guard let self else { return }
            do {
                let result = try self.decoder.decode(SummaryGenerationResult.self, from: data)
                self.applySnapshot(result.snapshot)
                self.filter = "summaries"
                self.selectSummary(result.summaryId)
                completion(nil)
            } catch { completion("无法读取生成状态：\(error.localizedDescription)") }
        }
    }

    func cancelSummary(_ id: String) {
        request("summary_cancel", values: ["summary_id": id], failure: { [weak self] message in self?.summaryError = message }) { [weak self] data in
            guard let self else { return }
            do { self.applySnapshot(try self.decoder.decode(Snapshot.self, from: data)) }
            catch { self.summaryError = error.localizedDescription }
        }
    }

    func saveSummarySettings(_ values: [String: Any], completion: @escaping (String?) -> Void) {
        guard !isDemo else { completion("演示模式无法保存自动总结设置"); return }
        request("summary_settings", values: ["values": values], failure: { completion($0) }) { [weak self] data in
            guard let self else { return }
            do {
                self.applySnapshot(try self.decoder.decode(Snapshot.self, from: data))
                self.showToast("自动总结设置已保存")
                completion(nil)
            } catch { completion(error.localizedDescription) }
        }
    }

    func exportSummary() {
        guard let detail = summaryDetail, let summary = selectedSummary, !detail.content.isEmpty else { return }
        let panel = NSSavePanel()
        panel.title = "导出总结"
        panel.nameFieldStringValue = summary.title.replacingOccurrences(of: "/", with: "-").replacingOccurrences(of: ":", with: "-") + ".md"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        do {
            try detail.content.write(to: destination, atomically: true, encoding: .utf8)
            showToast("总结已导出")
        } catch { summaryError = "导出失败：\(error.localizedDescription)" }
    }

    func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        showToast("已复制")
    }

    func hostName(_ id: String) -> String {
        snapshot?.hosts.first(where: { $0.id == id })?.name ?? displayHost(id)
    }

    func saveConnections(_ values: [String: Any], completion: @escaping (String?) -> Void) {
        guard !isDemo else { completion("演示模式无法修改连接"); return }
        request("settings", values: ["values": values], failure: { completion($0) }) { [weak self] data in
            guard let self else { return }
            do {
                self.applySnapshot(try self.decoder.decode(Snapshot.self, from: data))
                completion(nil)
            } catch { completion(error.localizedDescription) }
        }
    }

    func checkConnection(_ connection: SSHConnection? = nil, completion: @escaping (ConnectionCheck?, String?) -> Void) {
        request("check_connection", values: connection.map { ["profile": $0.values] } ?? [:], failure: { completion(nil, $0) }) { [weak self] data in
            guard let self else { return }
            do { completion(try self.decoder.decode(ConnectionCheck.self, from: data), nil) }
            catch { completion(nil, error.localizedDescription) }
        }
    }

    func discoverSSHAliases(completion: @escaping ([String]) -> Void) {
        request("ssh_aliases", completion: { data in
            let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            completion(result?["aliases"] as? [String] ?? [])
        })
    }

    func connectInTerminal(_ connection: SSHConnection) {
        request("ssh_terminal_command", values: ["profile": connection.values], completion: { [weak self] data in
            guard let self, let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let command = result["command"] as? String else { return }
            do {
                let folder = self.dataDirectory.appendingPathComponent("ssh-setup", isDirectory: true)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                let script = folder.appendingPathComponent("connect-" + UUID().uuidString + ".command")
                try ("#!/bin/sh\n" + command + "\n/bin/rm -f -- \"$0\"\n").write(to: script, atomically: true, encoding: .utf8)
                try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
                if !NSWorkspace.shared.open(script) { self.showToast("无法打开终端，请检查 Terminal 设置") }
            } catch { self.showToast(error.localizedDescription) }
        })
    }

    func openConversation(_ id: String, host: String = "mac") {
        var parts = URLComponents()
        parts.scheme = "codex"; parts.host = "threads"; parts.path = "/" + id
        let connection = snapshot?.settings.remoteHosts?.first { $0.id == host }
        let hostId = host == "mac" ? "local" : connection?.hostId.isEmpty == false ? connection!.hostId : "remote-ssh-discovered:" + host
        parts.queryItems = [URLQueryItem(name: "hostId", value: hostId)]
        guard let url = parts.url else { return }
        openCodex(url, fallback: id)
    }

    func openCodex(_ url: URL? = nil, fallback: String = "") {
        let app = snapshot?.settings.codexApp ?? ""
        if !app.isEmpty {
            NSWorkspace.shared.open(url.map { [$0] } ?? [], withApplicationAt: URL(fileURLWithPath: (app as NSString).expandingTildeInPath), configuration: NSWorkspace.OpenConfiguration()) { [weak self] _, error in
                if error != nil { Task { @MainActor in self?.showToast("无法打开所选 Codex 应用，请检查连接设置") } }
            }
        } else if let target = url ?? URL(string: "codex://") {
            if !NSWorkspace.shared.open(target) {
                if !fallback.isEmpty { copy(fallback) }
                showToast("请先安装或选择 Codex 应用；对话 ID 可在 Codex 中查找")
            }
        }
    }

    func showToast(_ text: String) {
        toast = text
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            if self?.toast == text { self?.toast = "" }
        }
    }

    func shutdown() {
        pet.shutdown()
        timer?.invalidate()
        try? input?.close()
        output?.readabilityHandler = nil
        process?.terminate()
    }
}

final class LineBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    func append(_ value: Data) -> [Data] {
        lock.lock()
        defer { lock.unlock() }
        data.append(value)
        var lines: [Data] = []
        while let index = data.firstIndex(of: 10) {
            lines.append(data.prefix(upTo: index))
            data.removeSubrange(...index)
        }
        return lines
    }
}
