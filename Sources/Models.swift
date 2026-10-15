import Foundation

struct TodoTask: Decodable, Identifiable {
    let id: String
    let conversationId: String
    let semanticKey: String
    let kind: String
    let title: String
    let titleOverride: String?
    let detail: String
    let progress: String?
    let evidence: String
    let nextAction: String
    let artifact: String
    let priority: Int
    let confidence: Double
    let status: String
    let createdAt: Double
    let updatedAt: Double
    let snoozedUntil: Double
    let host: String
    let threadId: String
    let conversationTitle: String
    let cwd: String
    let path: String
    let summary: String
    let conversationUpdatedAt: Double
    var isOpen: Bool { status == "open" }
    var isManual: Bool { kind == "manual" }
    var isRunning: Bool { kind == "running" }
    var hasCustomTitle: Bool { titleOverride?.isEmpty == false }
    var stopPoint: String { (progress?.isEmpty == false ? progress : nil) ?? "停止位置待整理" }
    var isSnoozed: Bool { snoozedUntil > Date().timeIntervalSince1970 }
    var kindTitle: String { ["running":"进行中", "review": "结果校对", "continue": "继续推进", "wait": "等待结果", "decision": "需要决定", "manual": "手动待办"][kind] ?? kind }
    var symbol: String { ["running":"play.circle", "review": "checkmark.square", "continue": "arrow.right.circle", "wait": "hourglass", "decision": "questionmark.bubble", "manual": "square.and.pencil"][kind] ?? "circle" }
}

struct Conversation: Decodable, Identifiable {
    let id: String
    let host: String
    let threadId: String
    let title: String
    let cwd: String
    let path: String
    let updatedAt: Double
    let analysisState: String?
    let summary: String
    let closed: Int
    let archived: Int?
    let active: Bool
    let executionState: String?
    let needsAnalysis: Bool?
    var stateTitle: String {
        if archived == 1 { return "已归档，不再跟踪" }
        if closed == 1 { return "手动结束" }
        if executionState == "running" { return needsAnalysis == true ? "进行中 · 待整理" : "进行中" }
        if needsAnalysis == true { return "待整理最新进度" }
        return ["running":"进行中", "submitted": "已提交", "unfinished": "未完成", "waiting": "等待中", "completed": "已完成", "informational": "已处理", "uncertain": "需确认"][analysisState ?? ""] ?? (active ? "运行中 / 待分析" : "待分析")
    }
}

struct HostStatus: Decodable, Identifiable {
    let id: String
    let status: String
    let detail: String
    let checkedAt: Double
    let totalFiles: Int
    let remainingFiles: Int
    let root: String
    let name: String?
}

struct TodoSettings: Decodable {
    var automatic: Bool
    var intervalSeconds: Int
    var idleMinutes: Int
    var batchSize: Int
    var historyDays: Int
    var enabledHosts: [String]
    var sourceLimit: Int
    var workdaysOnly: Bool
    var workHoursEnabled: Bool
    var workStartMinutes: Int
    var workEndMinutes: Int
    var codexHome: String?
    var codexCli: String?
    var codexApp: String?
    var remoteHosts: [SSHConnection]?
    var analysisModel: String?
    var analysisEffort: String?
    var connectionSetupComplete: Bool?
}

struct SSHConnection: Decodable, Identifiable {
    var id: String
    var name: String
    var hostname: String
    var user: String
    var port: Int
    var identityFile: String
    var codexHome: String
    var python: String
    var codexCli: String
    var hostId: String
    static func empty(_ id: String = "") -> SSHConnection {
        SSHConnection(id: id, name: id, hostname: "", user: "", port: 0, identityFile: "", codexHome: "", python: "", codexCli: "", hostId: "")
    }
    var values: [String: Any] {
        ["id": id, "name": name, "hostname": hostname, "user": user, "port": port, "identity_file": identityFile,
         "codex_home": codexHome, "python": python, "codex_cli": codexCli, "host_id": hostId]
    }
}

struct ConnectionCheck: Decodable {
    let ok: Bool
    let detail: String
    let root: String?
    let cli: String?
    let version: String?
    let sessionsReady: Bool?
    let loginReady: Bool?
    let desktopReady: Bool?
}

struct DetectionSchedule: Decodable {
    let due: Bool
    let nextAt: Double?
    let summary: String
    let dayLabel: String
    let calendarUpdatedAt: Double
    let calendarPapers: [String]
    let calendarError: String
    let offDuty: Bool?
    let offDutyUntil: Double?
}

struct TaskSaveResult: Decodable {
    let taskId: String
    let snapshot: Snapshot
}

struct SyncStatus: Decodable {
    var running: Bool?
    var phase: String?
    var cancelled: Bool?
}

struct NudgeRecord: Decodable, Identifiable {
    let actionId: String
    let taskId: String
    let conversationId: String
    let status: String
    let createdAt: Double
    let updatedAt: Double
    let error: String
    let attention: String?
    var id: String { actionId }
    var pending: Bool { status == "queued" || status == "sending" }
    var summary: String {
        if pending { return "正在发送催办…" }
        if status == "sent" { return attention?.isEmpty == false ? "催办已送达 · \(attention!)" : "催办已送达 · \(relativeTime(updatedAt))" }
        if status == "unknown" { return "送达未确认，请核对原对话" }
        if status == "failed" { return "催办未发送：\(error)" }
        return "已核对上次催办"
    }
}

struct Snapshot: Decodable {
    let tasks: [TodoTask]
    let conversations: [Conversation]
    let hosts: [HostStatus]
    let settings: TodoSettings
    let model: String
    let effort: String
    let pendingAnalysis: Int
    let lastSync: Double
    let lastAnalysis: Double
    let modelError: String
    let sync: SyncStatus
    let schedule: DetectionSchedule?
    let nudges: [NudgeRecord]?
    let summaries: [TodoSummary]?
    let summarySchedule: SummarySchedule?
    let appUpdate: AppUpdate?
}

func displayHost(_ host: String) -> String { ["mac":"这台 Mac","manual":"手动添加"][host] ?? host }

func detectionTime(_ stamp: Double?) -> String {
    guard let stamp else { return "等待工作日数据" }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier:"zh_CN")
    formatter.timeZone = TimeZone(identifier:"Asia/Shanghai")
    formatter.dateFormat = "M月d日 HH:mm"
    return formatter.string(from:Date(timeIntervalSince1970:stamp))
}

func relativeTime(_ stamp: Double) -> String {
    if stamp <= 0 { return "尚未同步" }
    let seconds = max(0, Int(Date().timeIntervalSince1970 - stamp))
    if seconds < 60 { return "刚刚" }
    if seconds < 3600 { return "\(seconds / 60) 分钟前" }
    if seconds < 86400 { return "\(seconds / 3600) 小时前" }
    return "\(seconds / 86400) 天前"
}


struct TodoSummary: Decodable, Identifiable {
    let id: String
    let title: String
    let status: String
    let scope: String
    let startDate: String
    let endDate: String
    let createdAt: Double
    let finishedAt: Double
    let taskCount: Int
    let origin: String
    let error: String
    let model: String
    let effort: String
    let workOnly: Bool?
    let excludedCount: Int?
    let uncertainCount: Int?
    var pending: Bool { status == "queued" || status == "running" }
    var includedCount: Int { workOnly == true && status == "completed" ? max(0, taskCount - (excludedCount ?? 0)) : taskCount }
    var statusTitle: String {
        ["queued": "等待生成", "running": "生成中", "completed": "已完成", "failed": "生成失败", "cancelled": "已中止"][status] ?? status
    }
    var scopeTitle: String { scope == "all" ? "全部已保存任务（含完成、归档）" : scope == "active" ? "全部未完成待办（含稍后处理）" : startDate == endDate ? startDate : "\(startDate) — \(endDate)" }
}

struct SummarySource: Decodable, Identifiable {
    let id: String
    let title: String
    let status: String
    let host: String?
    let progress: String?
    let detail: String?
    let nextAction: String?
    let relevance: String?
    let relevanceReason: String?
    let conversationArchived: Bool?
}

struct SummaryDetail: Decodable {
    let id: String
    let content: String
    let sources: [SummarySource]
}

struct SummaryPreview: Decodable {
    let title: String
    let taskCount: Int
    let counts: [String: Int]
    let startDate: String
    let endDate: String
    let archivedCount: Int?
}

struct SummaryGenerationResult: Decodable {
    let summaryId: String
    let snapshot: Snapshot
}

struct SummarySchedule: Decodable {
    var enabled: Bool
    var frequency: String
    var timeMinutes: Int
    var weekday: Int
    var intervalHours: Int
    var scope: String
    var days: Int
    var workdaysOnly: Bool
    var workOnly: Bool
    var workContext: String
    let nextAt: Double?
    let lastAt: Double
    let description: String

    static var defaults: SummarySchedule {
        SummarySchedule(enabled: false, frequency: "daily", timeMinutes: 1080, weekday: 0, intervalHours: 24,
                        scope: "period", days: 1, workdaysOnly: false, workOnly: false, workContext: "", nextAt: nil, lastAt: 0, description: "自动总结未开启")
    }
    var values: [String: Any] {
        ["enabled": enabled, "frequency": frequency, "time_minutes": timeMinutes, "weekday": weekday,
         "interval_hours": intervalHours, "scope": scope, "days": days, "workdays_only": workdaysOnly,
         "work_only": workOnly, "work_context": workContext]
    }
}

enum SummaryDates {
    static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return calendar
    }
    static func string(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
}


struct AppUpdate: Decodable {
    let currentVersion: String
    let checking: Bool
    let available: Bool
    let version: String
    let title: String
    let notes: String
    let url: String
    let downloadUrl: String
    let publishedAt: String
    let error: String
    let checkedAt: Double
    let skippedVersion: String
    let shouldPrompt: Bool
}
