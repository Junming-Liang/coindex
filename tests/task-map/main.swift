import AppKit
import SwiftUI

@MainActor
func renderTaskMap() throws {
    precondition(CommandLine.arguments.contains("--demo"), "Preview must never start the real service")
    let args = CommandLine.arguments.filter { $0 != "--demo" }
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    let snapshot = try decoder.decode(Snapshot.self, from: Data(contentsOf: URL(fileURLWithPath: args[1])))
    let graph = snapshot.taskMap!
    precondition(!graph.nodes.isEmpty && graph.edges.contains { $0.kind == "progression" })
    let model = AppModel()
    model.snapshot = snapshot
    let output = URL(fileURLWithPath: args[2])
    try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
    for (name, appearance, scheme) in [("light", NSAppearance.Name.aqua, ColorScheme.light), ("dark", .darkAqua, .dark)] {
        NSApplication.shared.appearance = NSAppearance(named: appearance)
        let view = TaskMapWorkspaceView(preview: graph).environmentObject(model).environment(\.colorScheme, scheme)
            .frame(width: 1200, height: 820)
        // Host without showing or activating a window: ImageRenderer does not
        // render native ScrollView/TextField backing views on macOS.
        let host = NSHostingView(rootView: view)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 820), styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: appearance)
        window.contentView = host
        host.frame = NSRect(x: 0, y: 0, width: 1200, height: 820)
        host.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(0.15))
        host.layoutSubtreeIfNeeded()
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
            fatalError("Task map preview could not render")
        }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]) else { fatalError("PNG encoding failed") }
        precondition(bitmap.pixelsWide >= 1200 && bitmap.pixelsHigh >= 820)
        try png.write(to: output.appendingPathComponent("task-map-"+name+".png"))
        window.close()
    }
    print("Task map models decoded and native light/dark previews rendered")
}

MainActor.assumeIsolated {
    _ = NSApplication.shared
    do { try renderTaskMap() }
    catch { fatalError(String(describing: error)) }
}
