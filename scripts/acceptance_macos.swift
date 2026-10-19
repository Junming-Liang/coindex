// External AX smoke test of the unchanged installed release application.
import AppKit
import ApplicationServices
import Foundation

let pid = pid_t(CommandLine.arguments[1])!
let out = URL(fileURLWithPath: CommandLine.arguments[2])
let app = AXUIElementCreateApplication(pid)
var checks: [String] = []
func attr(_ e: AXUIElement, _ key: String) -> AnyObject? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(e, key as CFString, &value) == .success else { return nil }
    return value
}
func tree(_ e: AXUIElement, _ depth: Int = 0) -> [AXUIElement] {
    if depth > 30 { return [] }
    return [e] + ((attr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? []).flatMap { tree($0, depth + 1) }
}
func nodes() -> [AXUIElement] { ((attr(app, kAXWindowsAttribute) as? [AXUIElement]) ?? []).flatMap { tree($0) } }
func text(_ e: AXUIElement) -> String {
    [kAXRoleAttribute, kAXIdentifierAttribute, kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute].map { String(describing: attr(e, $0) ?? "" as NSString) }.joined(separator: " | ")
}
func dump(_ name: String) {
    try? nodes().map(text).joined(separator: "\n").write(to: out.appendingPathComponent(name + ".ax.txt"), atomically: true, encoding: .utf8)
    if CGPreflightScreenCaptureAccess() {
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        p.arguments = ["-x", out.appendingPathComponent(name + ".png").path]
        do { try p.run(); p.waitUntilExit() } catch { print("Screenshot launch failed: \(error)"); exit(1) }
        guard p.terminationStatus == 0, let bytes = try? Data(contentsOf: out.appendingPathComponent(name + ".png")), bytes.count > 100, bytes.starts(with: [137,80,78,71,13,10,26,10]), let bitmap = NSBitmapImageRep(data: bytes), bitmap.pixelsWide > 100, bitmap.pixelsHigh > 100 else {
            print("Screenshot missing/failed: " + name); exit(1)
        }
    }
}
func fail(_ message: String) -> Never {
    print("FAIL: \(message)"); dump("failure")
    try? (["result": "failed", "reason": message, "checks": checks] as [String: Any]).json().write(to: out.appendingPathComponent("macos-result.json"))
    exit(1)
}
extension Dictionary where Key == String, Value == Any {
    func json() -> Data { (try? JSONSerialization.data(withJSONObject: self, options: [.prettyPrinted, .sortedKeys])) ?? Data() }
}
func element(_ id: String) -> AXUIElement {
    for _ in 0..<30 {
        if let e = nodes().first(where: { attr($0, kAXIdentifierAttribute) as? String == id }) { return e }
        Thread.sleep(forTimeInterval: 0.2)
    }
    fail("AX identifier missing: " + id)
}
func press(_ id: String) {
    guard AXUIElementPerformAction(element(id), kAXPressAction as CFString) == .success else { fail("AXPress: " + id) }
    Thread.sleep(forTimeInterval: 0.5)
}
func contains(_ s: String) -> Bool { nodes().contains { text($0).contains(s) } }
func expect(_ yes: Bool, _ label: String) { if !yes { fail(label) }; checks.append(label); print("PASS: " + label) }
func pressLabel(_ label: String) {
    guard let e = nodes().first(where: { attr($0, kAXRoleAttribute) as? String == kAXButtonRole && tree($0).map(text).joined(separator: " ").contains(label) }),
          AXUIElementPerformAction(e, kAXPressAction as CFString) == .success else { fail("Button label unavailable: " + label) }
    Thread.sleep(forTimeInterval: 0.6)
}
func count(_ id: String, _ n: Int) {
    let label = tree(element(id)).map(text).joined(separator: " ")
    expect(label.range(of: "(^|[^0-9])" + String(n) + "([^0-9]|$)", options: .regularExpression) != nil, id + " count=" + String(n))
}
func cancelSheet() {
    guard let e = nodes().first(where: { attr($0, kAXRoleAttribute) as? String == kAXButtonRole && ((attr($0, kAXTitleAttribute) as? String == "取消") || (attr($0, kAXDescriptionAttribute) as? String == "取消")) }),
          AXUIElementPerformAction(e, kAXPressAction as CFString) == .success else { fail("Cancel sheet unavailable") }
    Thread.sleep(forTimeInterval: 0.5)
}
let trusted = AXIsProcessTrusted()
let capture = CGPreflightScreenCaptureAccess()
print("AX trusted=\(trusted), screen capture allowed=\(capture). No permission requests or TCC changes.")
guard trusted else { fail("Runner Accessibility permission unavailable; UI acceptance blocked") }
NSRunningApplication(processIdentifier: pid)?.activate(options: [.activateIgnoringOtherApps])
Thread.sleep(forTimeInterval: 2)
_ = element("filter-all")
expect(contains("验收文档全文搜索"), "installed demo renders task")
count("filter-all", 5); count("filter-review", 2); count("filter-wait", 1)
dump("01-demo")
pressLabel("dev-server")
expect(contains("验收文档全文搜索") && contains("降低图片上传等待时间") && !contains("发布新版桌面应用"), "source filter dev-server selects its two tasks")
count("filter-all", 2); count("filter-review", 1); count("filter-wait", 1)
dump("01b-source")
pressLabel("所有机器")
press("filter-review")
expect(contains("验收文档全文搜索") && contains("发布新版桌面应用") && !contains("降低图片上传等待时间"), "review filter selects the two review tasks")
dump("02-review")
press("filter-wait")
expect(contains("降低图片上传等待时间") && !contains("验收文档全文搜索"), "wait filter selects wait task")
dump("03-wait")
press("filter-all")
let search = element("task-search")
guard AXUIElementSetAttributeValue(search, kAXValueAttribute as CFString, "zz-coindex-no-match" as CFString) == .success else { fail("search AXValue not writable") }
Thread.sleep(forTimeInterval: 1)
expect(!contains("验收文档全文搜索") && !contains("降低图片上传等待时间"), "no-match search removes tasks")
count("filter-all", 0); count("filter-review", 0); count("filter-wait", 0)
dump("04-search-empty")
guard AXUIElementSetAttributeValue(search, kAXValueAttribute as CFString, "" as CFString) == .success else { fail("clear search failed") }
Thread.sleep(forTimeInterval: 1)
expect(contains("验收文档全文搜索"), "clearing search restores tasks")
press("filter-summaries")
press("summary-create")
_ = element("summary-generate")
expect(contains("演示模式"), "summary composer is visible and demo safety disclosed")
dump("05-summary-composer")
cancelSheet()
press("summary-schedule")
expect(contains("自动生成并保存总结") && contains("保存设置"), "automatic summary settings panel opens")
guard let toggle = nodes().first(where: { [kAXCheckBoxRole, "AXSwitch"].contains(attr($0, kAXRoleAttribute) as? String ?? "") && text($0).contains("自动生成并保存总结") }) else { fail("Automatic summary toggle not exposed") }
let oldToggle = String(describing: attr(toggle, kAXValueAttribute))
guard AXUIElementPerformAction(toggle, kAXPressAction as CFString) == .success else { fail("Automatic summary toggle cannot be pressed") }
Thread.sleep(forTimeInterval: 0.5)
expect(String(describing: attr(toggle, kAXValueAttribute)) != oldToggle, "summary schedule toggle changes draft state")
dump("06-summary-schedule")
cancelSheet()
expect(capture, "runner permits screenshots")
try (["result": "passed", "checks": checks, "scope": "Unchanged installed app demo UI. Summary persistence separately tested via packaged backend; no real model."] as [String: Any]).json().write(to: out.appendingPathComponent("macos-result.json"))
