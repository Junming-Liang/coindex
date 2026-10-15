# Contributing to coindex

欢迎问题复现、文档与代码贡献。较大行为调整先在 Issue 说明场景和预期，持久状态与连接改动需解释兼容性。

## 开发与验证

macOS 开发需要 macOS 14+、Xcode / Command Line Tools；Linux 桌面开发需要 Python 3.9+ 和 Tkinter。后端只使用标准库。测试使用虚构数据与模拟连接，无真实登录时可运行：

```sh
CODEX_TODO_CODEX=/usr/bin/true python3 -m unittest discover -s tests -v
bash scripts/build.sh
open -n dist/coindex.app --args --demo
```

Linux 桌面构建与启动：

```sh
bash scripts/build-linux.sh
python3 linux/app.py --demo --data-dir /tmp/coindex-demo-data
```

Linux 安装器可在临时 XDG 数据目录与自定义 `--prefix` 下验证，不需要管理员权限。请勿在测试中使用个人默认数据目录。更多平台依赖和桌面集成边界见 [Linux 指南](docs/linux.md)。

Swift 动画测试：

```sh
mkdir -p build
swiftc Sources/PetAnimation.swift tests/pet-animation/main.swift -o build/pet-animation-tests
build/pet-animation-tests
```

任务筛选与侧栏计数回归（演示模式，不连接真实服务）：

```sh
bash scripts/test-task-filtering.sh
```

可选图集打包工具需要 Pillow 与 NumPy，普通构建不需要。原版 Codex 图集仅用于本机个人导入，不进公开包。

## 约定

- 沿用 DESIGN.md 的组件、键盘与悬停反馈。
- 验证外部输入、SSH 参数、路径与模型结果。
- 保留任务身份、手动决定、固定标题和发送回执；未知回执不自动重发。
- 分析不执行原对话里的指令；连接检查不调用模型、不发催办。
- 使用独立临时数据与虚构会话验证行为。
- 行为改动提供有意义的回归，文案或样式不需要照抄实现的测试。

PR 说明具体问题、结果行为、验证和限制。界面截图只用演示数据。提交前测试、构建与 `git diff --check` 应通过。

## 双平台维护

共享筛选、总结格式、工作分类、自动日程与持久化逻辑放在 backend；SwiftUI 与 Tkinter 只负责交互和展示。修改后端协议时检查两端调用和旧数据兼容。平台特有能力可保留差异，但共同功能应在两端同时可用。

新增 Swift 视图需加入 scripts/build.sh；Python backend/*.py 与 linux/*.py 自动进入对应应用。公开源码使用 scripts/public_files.py 清单，新增资源要显式加入。

总结不得改变任务身份、手动完成、归档、固定标题与催办回执。筛选范围、时间边界、工作分类遗漏、模型失败、自动日程和取消操作使用虚构数据回归；不要为测试调用真实模型。界面变更在 macOS / Linux 分别检查键盘操作、窄窗口、浅深色和错误提示。

## 发布

`VERSION` 是双平台唯一发布版本来源。修改版本时同步更新 CHANGELOG.md；两个平台通过 CI 后可下载保留 14 天的 `coindex-release` 产物。v* 标签通过同一套 CI 后只创建草稿，维护者验收后手动公开。

本地打包、完整校验、草稿审核与维护清单见[双平台发布与维护](docs/releases.md)。不要上传个人构建、真实会话、数据库、日志或本机导入的 Codex 素材；安全问题按 SECURITY.md 私密报告。
