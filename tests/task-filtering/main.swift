import Foundation

func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
}

func task(_ id: String, host: String, kind: String, status: String = "open", snoozedUntil: Double = 0,
          title: String = "Example", detail: String = "", conversationTitle: String = "", artifact: String = "") -> TodoTask {
    TodoTask(id: id, conversationId: id, semanticKey: id, kind: kind, title: title, titleOverride: nil,
             detail: detail, progress: nil, evidence: "", nextAction: "", artifact: artifact, priority: 1,
             confidence: 1, status: status, createdAt: 1, updatedAt: 1, snoozedUntil: snoozedUntil,
             host: host, threadId: id, conversationTitle: conversationTitle, cwd: "", path: "",
             summary: "", conversationUpdatedAt: 1)
}

func snapshot(_ tasks: [TodoTask]) -> Snapshot {
    let settings = TodoSettings(automatic: false, intervalSeconds: 1800, idleMinutes: 10, batchSize: 6,
                               historyDays: 0, enabledHosts: ["mac", "server-a", "server-b"], sourceLimit: 120,
                               workdaysOnly: false, workHoursEnabled: false, workStartMinutes: 540,
                               workEndMinutes: 1080, codexHome: nil, codexCli: nil, codexApp: nil,
                               remoteHosts: nil, analysisModel: nil, analysisEffort: nil, connectionSetupComplete: nil)
    return Snapshot(tasks: tasks, conversations: [], hosts: [], settings: settings, model: "", effort: "",
                    pendingAnalysis: 0, lastSync: 0, lastAnalysis: 0, modelError: "",
                    sync: SyncStatus(running: false, phase: nil, cancelled: nil), schedule: nil, nudges: nil,
                    summaries: nil, summarySchedule: nil, appUpdate: nil)
}

@MainActor
func verifyTaskFiltering() {
    // Demo mode prevents the real collector, scheduler and model connections from starting.
    precondition(ProcessInfo.processInfo.arguments.contains("--demo"))
    let model = AppModel()
    let fixtures = [
        task("a-wait", host: "server-a", kind: "wait"),
        task("b-review", host: "server-b", kind: "review", title: "Documents Search",
             detail: "body-keyword", conversationTitle: "topic-keyword", artifact: "artifact-keyword"),
        task("mac-review", host: "mac", kind: "review"),
        task("b-continue", host: "server-b", kind: "continue"),
        task("b-wait", host: "server-b", kind: "wait"),
        task("a-done", host: "server-a", kind: "review", status: "done"),
        task("a-dismissed", host: "server-a", kind: "wait", status: "dismissed"),
        task("a-snoozed", host: "server-a", kind: "continue", snoozedUntil: Date().timeIntervalSince1970 + 86400)
    ]
    model.snapshot = snapshot(fixtures)
    expect(model.count("all") == 5 && model.tasks.count == 5, "All machines should show five open tasks")
    expect(model.count("review") == 2 && model.count("continue") == 1 && model.count("wait") == 2,
           "Global category totals must exclude completed, ignored and snoozed records")

    model.hostFilter = "server-a"
    expect(model.count("all") == 1 && model.tasks.map(\.id) == ["a-wait"], "Machine selection must scope both badge and list")
    expect(model.count("wait") == 1 && model.count("review") == 0 && model.count("continue") == 0,
           "Category badges must use the selected machine")

    model.hostFilter = "server-b"
    model.filter = "wait"
    expect(model.tasks.map(\.id) == ["b-wait"], "The list must apply the selected category")
    expect(model.count("all") == 3 && model.count("review") == 1 && model.count("continue") == 1,
           "Switching category must not erase other category badges")

    model.filter = "all"
    for query in ["DOCUMENTS", "body-keyword", "TOPIC-KEYWORD", "artifact-keyword"] {
        model.search = query
        expect(model.count("all") == 1 && model.count("review") == 1 && model.tasks.map(\.id) == ["b-review"],
               "Search must scope badges and list using every existing searchable field: \(query)")
        model.hostFilter = "server-a"
        expect(model.count("all") == 0 && model.tasks.isEmpty, "Search must also respect machine selection")
        model.hostFilter = "server-b"
    }
    model.search = "no matching task"
    expect(model.count("all") == 0 && model.tasks.isEmpty, "An unmatched search must have zero badges")
    expect(model.openCount == 5, "The menu bar total must retain its global scope")

    model.search = ""
    model.hostFilter = "server-a"
    model.filter = "completed"
    expect(Set(model.tasks.map(\.id)) == Set(["a-done", "a-dismissed"]), "Processed records must remain accessible")
    expect(model.count("all") == 1, "Processed records must not enter open task badges")
    model.filter = "snoozed"
    expect(model.tasks.map(\.id) == ["a-snoozed"] && model.count("all") == 1,
           "Snoozed records must remain separate from open task badges")

    model.snapshot = snapshot(fixtures + [task("manual", host: "manual", kind: "manual")])
    model.filter = "all"
    model.hostFilter = "all"
    expect(model.count("manual") == 1 && model.count("all") == 6, "All machines must include manual tasks")
    model.hostFilter = "server-a"
    expect(model.count("manual") == 0 && model.count("all") == model.tasks.count, "A machine scope must also apply to manual task badges")

    model.snapshot = nil
    expect(model.count("all") == 0 && model.tasks.isEmpty && model.openCount == 0, "Missing snapshots must show zero tasks")
    print("Verified machine and category scopes, all search fields, processed/snoozed/manual tasks, and global menu totals")
}

MainActor.assumeIsolated { verifyTaskFiltering() }
