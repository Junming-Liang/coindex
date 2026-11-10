import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ConnectionSettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var home = ""
    @State private var cli = ""
    @State private var app = ""
    @State private var modelName = "gpt-6-luna"
    @State private var effort = "max"
    @State private var checking = false
    @State private var result: ConnectionCheck?
    @State private var message = ""
    @State private var editor: SSHConnection?
    @State private var editingExisting = false
    @State private var claudeEnabled = false
    @State private var claudeHome = ""
    @State private var claudeMessage = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            SettingsSection("连接你的 Codex", symbol: "link") {
                VStack(alignment: .leading, spacing: 12) {
                    Text("先在 Codex 中登录并创建一个会话，再检查连接。默认自动寻找本机安装与数据目录。")
                        .font(.callout).foregroundStyle(Palette.muted)
                    pathField("Codex 应用", value: $app, placeholder: "自动使用系统关联的 Codex", directories: false, apps: true)
                    pathField("会话与登录目录", value: $home, placeholder: "自动发现（通常为 ~/.codex）", directories: true)
                    DisclosureGroup("高级连接设置") {
                        VStack(alignment: .leading, spacing: 10) {
                            pathField("Codex CLI", value: $cli, placeholder: "自动发现，可选择自定义安装", directories: false)
                            Text("CLI 路径优先于应用内的 CLI；会话读取、分析登录和桌面连接使用同一个数据目录。")
                                .font(.caption).foregroundStyle(Palette.muted)
                            TextField("分析模型", text: $modelName).textFieldStyle(.roundedBorder)
                            Picker("推理强度", selection: $effort) {
                                ForEach(["minimal", "low", "medium", "high", "xhigh", "max", "ultra"], id: \.self) { Text($0).tag($0) }
                            }
                            Text("填写你的 Codex 账号可用的模型；模型无法调用时保留旧待办。连接检查不调用模型。")
                                .font(.caption).foregroundStyle(Palette.muted)
                        }.padding(.top, 8)
                    }
                    HStack {
                        Button(checking ? "正在检查…" : "保存并检查连接") { saveAndCheck() }
                            .buttonStyle(CoindexButtonStyle(prominent: true)).disabled(checking || model.syncing || model.isDemo)
                        Button("打开 Codex 登录") { model.openCodex() }
                    }
                    if model.syncing { Text("请先中止当前更新，再修改连接。").font(.caption).foregroundStyle(.orange) }
                    if let result {
                        Label(result.ok ? "采集与登录已就绪" : "连接需要处理", systemImage: result.ok ? "checkmark.circle.fill" : "exclamationmark.triangle")
                            .foregroundStyle(result.ok ? Palette.success : .orange)
                        Text(result.detail).font(.caption).foregroundStyle(Palette.muted).textSelection(.enabled)
                        if let cli = result.cli, !cli.isEmpty { Text(cli).font(.caption2).foregroundStyle(Palette.muted).textSelection(.enabled) }
                    }
                    if !message.isEmpty { Text(message).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                }
            }
            SettingsSection("Claude Code 来源", symbol: "bubble.left.and.text.bubble.right") {
                VStack(alignment: .leading, spacing: 12) {
                    Toggle("同时整理 Claude Code 会话", isOn: $claudeEnabled)
                    pathField("Claude 数据目录", value: $claudeHome, placeholder: "自动使用 ~/.claude（或 CLAUDE_CONFIG_DIR）", directories: true)
                    Text("读取 Claude 的 projects 会话目录，与 Codex 待办合并展示；分析仍使用你的 Codex 模型。Claude 待办暂不支持一键催办，可复制恢复命令在终端继续。")
                        .font(.caption).foregroundStyle(Palette.muted)
                    Button("保存 Claude 来源") {
                        claudeMessage = ""
                        model.saveConnections(["claude_enabled": claudeEnabled, "claude_home": claudeHome]) { error in
                            claudeMessage = error ?? "已保存，下次更新时生效"
                        }
                    }.buttonStyle(CoindexButtonStyle()).disabled(model.syncing || model.isDemo)
                    if let ready = result?.claudeReady {
                        Text(ready ? "Claude 会话目录可读取" : "Claude 会话目录暂不可读取，请检查路径或先创建会话")
                            .font(.caption).foregroundStyle(ready ? Palette.success : .orange)
                    }
                    if !claudeMessage.isEmpty { Text(claudeMessage).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                }
            }
            SettingsSection("会话来源与 SSH", symbol: "desktopcomputer") {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(model.snapshot?.hosts ?? []) { host in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Toggle(model.hostName(host.id), isOn: Binding(get: { model.snapshot?.settings.enabledHosts.contains(host.id) ?? false }, set: { enabled in
                                    var hosts = model.snapshot?.settings.enabledHosts ?? []
                                    hosts.removeAll { $0 == host.id }
                                    if enabled { hosts.append(host.id) }
                                    model.settings(["enabled_hosts": hosts])
                                }))
                                Spacer()
                                Text(model.snapshot?.settings.enabledHosts.contains(host.id) == false ? "已停用" : host.status == "online" ? "已连接" : host.status == "offline" ? "连接失败" : "等待同步")
                                    .font(.caption).foregroundStyle(host.status == "online" ? Palette.success : Palette.muted)
                                if host.id != "mac", let connection = model.snapshot?.settings.remoteHosts?.first(where: { $0.id == host.id }) {
                                    Button("设置") { editingExisting = true; editor = connection }
                                        .disabled(model.syncing || model.isDemo)
                                }
                            }
                            Text(host.detail).font(.caption).foregroundStyle(Palette.muted).textSelection(.enabled)
                            if host.remainingFiles > 0 { Text("还有 \(host.remainingFiles) 个历史文件等待回填").font(.caption2).foregroundStyle(Palette.muted) }
                        }
                    }
                    Button { editingExisting = false; editor = .empty() } label: { Label("添加 SSH 机器…", systemImage: "plus") }
                        .disabled(model.syncing || model.isDemo)
                    Text("连接你自己的机器后，直接读取其 Codex 会话（启用 Claude 来源时也包括 Claude 会话）。支持已有 SSH 别名、跳板机配置与自定义数据目录，远程需要 Python 3。")
                        .font(.caption).foregroundStyle(Palette.muted)
                }
            }
        }
        .onAppear {
            home = model.snapshot?.settings.codexHome ?? ""
            cli = model.snapshot?.settings.codexCli ?? ""
            app = model.snapshot?.settings.codexApp ?? ""
            modelName = model.snapshot?.model ?? "gpt-6-luna"
            effort = model.snapshot?.effort ?? "max"
            claudeEnabled = model.snapshot?.settings.claudeEnabled ?? false
            claudeHome = model.snapshot?.settings.claudeHome ?? ""
        }
        .sheet(item: $editor) { connection in SSHConnectionEditor(connection: connection, existing: editingExisting) }
    }

    private func pathField(_ label: String, value: Binding<String>, placeholder: String, directories: Bool, apps: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption).foregroundStyle(Palette.muted)
            HStack {
                TextField(placeholder, text: value).textFieldStyle(.roundedBorder)
                Button("选择…") {
                    let panel = NSOpenPanel()
                    panel.canChooseDirectories = directories; panel.canChooseFiles = !directories
                    panel.allowsMultipleSelection = false
                    panel.showsHiddenFiles = true
                    panel.treatsFilePackagesAsDirectories = false
                    panel.message = apps ? "选择 Codex 或 ChatGPT 应用" : "选择" + label
                    if apps { panel.allowedContentTypes = [.applicationBundle] }
                    if panel.runModal() == .OK, let selected = panel.url { value.wrappedValue = selected.path; result = nil }
                }
            }
        }
    }

    private func saveAndCheck() {
        checking = true; result = nil; message = ""
        model.saveConnections(["codex_home": home, "codex_cli": cli, "codex_app": app,
                               "analysis_model": modelName, "analysis_effort": effort]) { error in
            if let error { message = error; checking = false; return }
            model.checkConnection { checked, error in
                result = checked; message = error ?? ""; checking = false
                if checked?.ok == true { model.settings(["connection_setup_complete": true]) }
            }
        }
    }
}

struct SSHConnectionEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State var connection: SSHConnection
    let existing: Bool
    @State private var useAlias = true
    @State private var aliases: [String] = []
    @State private var port = ""
    @State private var enable = false
    @State private var checking = false
    @State private var saving = false
    @State private var checked: ConnectionCheck?
    @State private var checkedKey = ""
    @State private var message = ""
    @State private var showRemove = false
    private var candidate: SSHConnection {
        var entry = connection
        entry.port = port.trimmingCharacters(in: .whitespaces).isEmpty ? 0 : Int(port) ?? -1
        return entry
    }
    private var candidateKey: String { String(data: (try? JSONSerialization.data(withJSONObject: candidate.values, options: .sortedKeys)) ?? Data(), encoding: .utf8) ?? "" }
    private var tested: Bool { checked?.ok == true && checkedKey == candidateKey }
    private var valid: Bool { !connection.id.isEmpty && (useAlias || !connection.hostname.isEmpty) }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(existing ? "SSH 连接设置" : "添加 SSH 机器").font(.system(size: 22, weight: .semibold))
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("1 · 选择连接方式").font(.headline)
                    if !existing {
                        Picker("连接方式", selection: $useAlias) {
                            Text("已有 SSH 别名").tag(true)
                            Text("新机器").tag(false)
                        }.pickerStyle(.segmented)
                    }
                    if useAlias && !existing {
                        if !aliases.isEmpty {
                            Picker("从 SSH 配置中选择", selection: $connection.id) {
                                Text("请选择或在下方填写").tag("")
                                ForEach(aliases, id: \.self) { Text($0).tag($0) }
                                if !connection.id.isEmpty && !aliases.contains(connection.id) { Text(connection.id).tag(connection.id) }
                            }
                        } else { Text("未发现已有别名。可以填写别名，或选择“新机器”输入地址。").font(.caption).foregroundStyle(Palette.muted) }
                    }
                    TextField(useAlias ? "SSH 别名" : "连接名称，例如 work-server", text: $connection.id).textFieldStyle(.roundedBorder).disabled(existing)
                    TextField("显示名称（可选）", text: $connection.name).textFieldStyle(.roundedBorder)
                    if !useAlias || existing && !connection.hostname.isEmpty {
                        TextField("机器地址 / IP", text: $connection.hostname).textFieldStyle(.roundedBorder)
                        HStack {
                            TextField("用户名（留空使用 SSH 配置）", text: $connection.user)
                            TextField("端口（留空使用 SSH 配置）", text: $port).frame(width: 200)
                        }.textFieldStyle(.roundedBorder)
                    }
                    DisclosureGroup("高级连接设置") {
                        VStack(alignment: .leading, spacing: 9) {
                            if useAlias && !(existing && !connection.hostname.isEmpty) {
                                TextField("地址覆盖（可选）", text: $connection.hostname)
                                TextField("用户名覆盖（可选）", text: $connection.user)
                                TextField("端口覆盖（可选）", text: $port)
                            }
                            HStack {
                                TextField("密钥文件路径（可选，复用 ssh-agent）", text: $connection.identityFile)
                                Button("选择…") {
                                    let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.showsHiddenFiles = true
                                    if panel.runModal() == .OK, let url = panel.url { connection.identityFile = url.path }
                                }
                            }
                            TextField("远程 Codex 数据目录（默认 ~/.codex）", text: $connection.codexHome)
                            TextField("远程 Claude 数据目录（默认 ~/.claude）", text: Binding(get: { connection.claudeHome ?? "" }, set: { connection.claudeHome = $0 }))
                            TextField("远程 Python 路径（默认 python3）", text: $connection.python)
                            TextField("远程 Codex CLI 路径（催办时自动发现）", text: $connection.codexCli)
                            TextField("Codex 桌面主机 ID（可选）", text: $connection.hostId)
                            Text("已有别名会沿用 ~/.ssh/config，包括跳板机。留空的项目在目标机器自动发现。")
                                .font(.caption).foregroundStyle(Palette.muted)
                        }.textFieldStyle(.roundedBorder).padding(.top, 8)
                    }
                    Divider()
                    Text("2 · 首次连接与密钥登录").font(.headline)
                    Text("在终端连接，核对机器指纹，使用自己的密钥或 ssh-agent 登录。自动读取需要免交互登录；密码仅在终端输入。")
                        .font(.callout).foregroundStyle(Palette.muted)
                    HStack {
                        Button("在终端连接") { model.connectInTerminal(candidate) }.disabled(!valid || checking)
                        Button("复制 SSH 配置引导") { model.copy(setupPrompt) }.disabled(!valid)
                    }
                    Text("远程需已运行过 Codex，并安装 Python 3。连接配置保存在 coindex，不改写你的 SSH 配置；免交互登录未完成时会给出错误提示。")
                        .font(.caption).foregroundStyle(Palette.muted)
                    Divider()
                    Text("3 · 检查会话目录").font(.headline)
                    Button(checking ? "正在测试…" : "测试 SSH 与会话读取") { test() }
                        .disabled(!valid || checking || saving)
                    if let checked {
                        Label(tested ? "会话读取已就绪" : checkedKey != candidateKey ? "设置已修改，请重新测试" : "连接需要处理", systemImage: tested ? "checkmark.circle.fill" : "exclamationmark.triangle")
                            .foregroundStyle(tested ? Palette.success : .orange)
                        Text(checked.detail).font(.caption).foregroundStyle(Palette.muted).textSelection(.enabled)
                        if let root = checked.root { Text(root).font(.caption2).foregroundStyle(Palette.muted).textSelection(.enabled) }
                    }
                    Toggle("保存后读取这台机器的会话", isOn: $enable)
                    if enable && !tested { Text("测试通过后可启用；也可以关闭此开关，先保存连接。").font(.caption).foregroundStyle(Palette.muted) }
                    if !message.isEmpty { Text(message).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                }
            }
            HStack {
                if existing { Button("移除连接", role: .destructive) { showRemove = true }.disabled(saving || checking) }
                Spacer()
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction).disabled(saving)
                Button(saving ? "正在保存…" : "保存连接") { save() }
                    .buttonStyle(CoindexButtonStyle(prominent: true)).disabled(!valid || saving || checking || enable && !tested)
            }
        }.padding(24).frame(width: 570, height: 720).background(Palette.canvas).foregroundStyle(Palette.ink)
            .buttonStyle(CoindexButtonStyle()).toggleStyle(.switch).tint(Palette.accent)
            .onAppear {
                useAlias = connection.hostname.isEmpty
                port = connection.port == 0 ? "" : String(connection.port)
                enable = model.snapshot?.settings.enabledHosts.contains(connection.id) ?? false
                model.discoverSSHAliases { aliases = $0 }
            }
            .alert("移除这个 SSH 连接？", isPresented: $showRemove) {
                Button("取消", role: .cancel) { }
                Button("移除", role: .destructive) { remove() }
            } message: { Text("停止读取这台机器。已有会话和待办保留，重新添加相同名称可继续跟踪。") }
    }

    private var setupPrompt: String {
        """
        请引导我为 coindex 配置 SSH 连接 \(connection.id)。目标地址：\(connection.hostname.isEmpty ? "复用已有 SSH 别名" : connection.hostname)。用户名：\(connection.user.isEmpty ? "使用已有配置或向我确认" : connection.user)。
        先检查现有 SSH 配置和 ssh-agent，只询问缺少的信息。使用现有密钥或 macOS 钥匙串，不要让我把密码、私钥或令牌贴到聊天。
        修改 SSH 配置前备份；首次连接请让我核对主机指纹，不能关闭主机密钥检查。向远程安装公钥前说明并取得我的同意。
        验证 SSH BatchMode=yes、StrictHostKeyChecking=yes 的免交互登录，再只读确认目标机器的 Python 3 和 Codex sessions 目录。
        完成后告诉我该在 coindex 的 SSH 设置中填写什么，然后让我点击“测试 SSH 与会话读取”。不要读取或输出登录凭据。
        """
    }

    private func test() {
        checking = true; message = ""; checked = nil
        let key = candidateKey
        model.checkConnection(candidate) { result, error in
            checking = false; checked = result; checkedKey = key; message = error ?? ""
            if result?.ok == true && candidateKey == key { enable = true }
        }
    }

    private func save() {
        var connections = model.snapshot?.settings.remoteHosts ?? []
        if !existing && connections.contains(where: { $0.id == connection.id }) { message = "连接名称已存在，请换一个名称或编辑已有连接。"; return }
        connections.removeAll { $0.id == connection.id }; connections.append(candidate)
        var enabled = model.snapshot?.settings.enabledHosts ?? ["mac"]
        enabled.removeAll { $0 == connection.id }; if enable { enabled.append(connection.id) }
        persist(connections, enabled: enabled)
    }

    private func remove() {
        persist((model.snapshot?.settings.remoteHosts ?? []).filter { $0.id != connection.id },
                enabled: (model.snapshot?.settings.enabledHosts ?? []).filter { $0 != connection.id })
    }

    private func persist(_ connections: [SSHConnection], enabled: [String]) {
        saving = true; message = ""
        model.saveConnections(["remote_hosts": connections.map(\.values), "enabled_hosts": enabled]) { error in
            saving = false
            if let error { message = error } else { dismiss() }
        }
    }
}
