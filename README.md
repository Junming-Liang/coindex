<div align="center">
  <img src="Resources/Brand/AppIcon.png" width="104" alt="coindex icon" />
  <h1>coindex</h1>
  <p><strong>多台机器、多个 Codex 会话，帮你记住交代给 AI 的事。</strong></p>
  <p>An agent-driven follow-up list for the work you delegated across machines and Codex conversations.</p>
  <p>
    <a href="https://github.com/Junming-Liang/coindex/releases/latest"><img src="https://img.shields.io/github/v/release/Junming-Liang/coindex" alt="Latest release" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" /></a>
    <img src="https://img.shields.io/badge/macOS-14%2B-black.svg" alt="macOS 14 or later" />
    <img src="https://img.shields.io/badge/Linux-Python%203.9%2B-blue.svg" alt="Linux desktop with Python 3.9 or later" />
    <img src="https://img.shields.io/badge/architecture-arm64%20%7C%20x86__64-blue.svg" alt="Apple Silicon and Intel" />
  </p>
  <p><a href="https://github.com/Junming-Liang/coindex/releases/latest">下载最新版本</a> · <a href="#快速开始">快速开始</a> · <a href="docs/user-guide.md">使用指南</a> · <a href="https://github.com/Junming-Liang/coindex/issues">反馈问题</a></p>
</div>

**AI 干完活了，你却已经忘了当初让它干什么。**

你在 Mac 上让一个 Agent 修 bug，在 SSH 机器上让另一个跑评测，又开了几个会话做功能、准备发布。任务越开越多，等结果陆续出来，最初的要求已经埋在聊天记录里：哪些事交代过、在哪台机器上、做到哪一步、还有什么需要你验收或继续推进，都得重新翻一遍。

**coindex 用一个整理 Agent，帮你记住交给其他 Agent 的工作。** 它持续阅读本机和你添加的 SSH 机器上的 Codex 会话，找出每个对话里的用户目标，把**当初要做什么、现在做到哪里、接下来该做什么、原对话在哪**整理成统一的跟进清单（follow-up list）。打开应用，就能找回那些已经忘记、还在执行或等你处理的事；需要续办时，可以查看原文依据，再一键催办原 Codex Agent。

**多台机器上的 Codex 会话 → 整理 Agent 找回目标 → 目标 / 进度 / 下一步 → 跟进清单 → 回到原 Agent 继续工作**

![三台演示机器的 Codex 会话，经整理 Agent 变成目标、进度与下一步清单](docs/assets/workflow-poster.png)

*虚构演示数据：每个来源的会话分别整理成目标条目，保留机器与原对话。*

> 支持 macOS 通用应用和 Linux 桌面。macOS 需 14+；两端需 Python 3.9+ 和已登录的兼容 Codex CLI，Linux 另需 Tkinter。macOS 应用采用 ad hoc 签名，**尚未经过 Developer ID 签名与 Apple 公证**。

## 目录

- [解决什么问题](#解决什么问题)
- [功能：Agent 如何整理目标与跟进](#功能)
- [界面截图与使用演示](#界面截图与使用演示)
- [安装](#安装)
- [Linux 安装](#linux-安装)
- [快速开始](#快速开始)
- [配置 Codex](#配置-codex)
- [配置 SSH](#配置-ssh)
- [数据与隐私](#数据与隐私)
- [常见问题](#常见问题)
- [从源码构建](#从源码构建)
- [项目结构](#项目结构)
- [参与贡献](#参与贡献)
- [许可证与致谢](#许可证与致谢)

## 解决什么问题

把工作交给 AI 很快，记住交出去的所有工作却很难。尤其是任务分散在多台机器和多个会话里时，AI 的回复已经到了，你可能还不知道这件事该怎么收尾。

| 多会话工作中的困扰 | coindex 帮你找回的信息 |
| --- | --- |
| AI 已经干完，我忘了当初让它做什么 | 用整体目标命名跟进条目，保留最初要达成的事和原文依据 |
| 会话散在本机和几台 SSH 机器上，忘了去哪找 | 在一张清单里查看各来源的目标，并关联原机器与对话 |
| 看见“已完成”或“PR 已提交”，却忘了有没有验收 | 汇总已有进度，指出仍需校对、确认或决定的下一步 |
| 一部分还在跑，一部分停住了，不知道先跟哪件 | 按进行中、结果校对、继续推进、等待结果和需要决定分类 |
| 找回了任务，还得重新给 Agent 解释上下文 | 一键把目标、进度和下一步发回原对话，让原 Agent 接着推进 |

清单依据已读取的会话记录整理。它帮你找回工作和跟进线索；结果是否正确、产物是否可用，仍需要实际验收。

## 功能

### 1. 让整理 Agent 汇总多台机器的 Codex 会话

连接本机 Codex，并按需添加 SSH 机器。coindex 自动发现新增会话，定期读取发生变化的记录，再交给整理 Agent 分析用户目标、执行进度和未处理事项。你无需逐个打开对话、复制日志或手动维护一张任务表。

整理 Agent 通过你自己的 Codex CLI 和模型工作，默认 `gpt-6-luna` / `max`，可在设置中调整。它根据已有记录给出结构化判断，负责生成和更新跟进清单；原来的执行 Agent 继续留在各自 Codex 对话中。

### 2. 记住当初交代的目标，持续更新进度

每个对话可以包含多个独立目标，coindex 分别跟踪。同一对话中，同一目标经历开发、提交、排队、验收和续办时，更新原条目的进度与下一步，保留身份和提醒，避免把每个阶段堆成重复待办。

例如，整体目标“为文档搜索增加全文检索”在开发、提交 PR 和等待验收时保持可识别；“PR 已提交，尚未做集成验证”放在进度中，“在测试环境验证完整搜索流程”成为下一步。

| 对话里的最新进展（虚构示例） | 跟进清单中的整体目标 | 当前类型 | 下一步 |
| --- | --- | --- | --- |
| 正在整理第三组文档，前两组摘要已完成 | 让知识库文档自动生成摘要 | 进行中 | 摘要生成后核对内容与引用 |
| PR 已提交，但集成验证没有记录 | 为文档搜索增加全文检索 | 结果校对 | 在测试环境验证完整搜索流程 |
| 定位了版本比较错误，尚未修改代码 | 修复应用自动更新 | 继续推进 | 修改比较规则后验证升级流程 |
| 基准测试已排队，尚未产出报告 | 降低图片上传等待时间 | 等待结果 | 查询基准测试的运行状态 |
| 实现和测试完成，等待体验确认 | 改善表单问答体验 | 需要决定 | 体验完整问答流程并确认 |

这些都是演示用例。自动分析依据对话最后记录，不主动访问 CI、评测或发布平台核实实时结果；“结果校对”用来提醒你完成实际验收。

### 3. 在一张 follow-up list 里，看到该跟进什么

工作台将各来源目标统一展示，可按类型、来源和关键词筛选。每条关联对话的条目包含：

- **整体目标：** 让你一眼记起这件事要达成什么。
- **进度 / 停住位置：** 已完成什么，尚缺哪一步。
- **下一步：** 最先要做的一件具体事。
- **来源与依据：** 原 Codex 对话、机器标签、最后活动、引用依据与判断把握。

可以固定标题、完成、忽略、稍后处理，也可以新建独立的手动跟进事项。手动决定会持久保存：未出现新进展时，重复整理不会恢复已完成或忽略的条目。“所有对话”提供统一的跟踪视图，支持主动结束或恢复对话跟踪。

### 4. 一键催办：让原 Codex Agent 接着干

找回了“为文档搜索增加全文检索”这个目标，发现进度停在“PR 已提交，尚未集成验证”。点击**一键催办**，coindex 就把**整体目标、此前进度、建议下一步及对应产物**发回原 Codex 对话。原 Agent 核对最新情况后继续推进，沿用原模型、工作目录与权限。

![一键催办演示：点击原生按钮，携带目标、进度与下一步，回到原 Agent 继续工作](docs/assets/nudge-demo.gif)

*虚构任务与演示回执；原 Agent 回复为流程示意。演示未发送真实消息。*

正在运行的对话可以追加催办，已停止的对话可以接着推进。你无需重新找机器、翻出原要求，再手动拼一遍上下文。

**自动整理只维护清单；催办由你主动点击。** 发送成功不等于任务完成。回执不明时，先核对原对话，确认未送达后再重试；coindex 不自动重复提交，不代答或批准原任务权限。演示模式禁用真实分析和催办。

### 5. 把跟进记录整理成总结

左侧「总结」可选择正在进行中的全部待办、全部已保存任务（含完成与归档），或一天、近三天、近一周及自定义日期。按专项汇报**进展、结果与结论、下一步**，有必要时说明风险，并在对应成果下整理**文档、指标报告和配图**。可筛选工作任务、补充工作背景，并设置自动总结的频率与时间。

日期范围包含该时段新建、更新或完成的待办；内容来自生成时的已保存进度。保留关键指标、对照和负结果，未验证内容会明确标注；产物只引用原记录中的链接或路径。个人开源 / 自制应用可从工作总结排除，无法判断的事项保留核对。详见[总结指南](docs/summaries.md)。

### 6. 保持适合日常工作的节奏

| 能力 | 说明 |
| --- | --- |
| 增量与历史回填 | 自动发现新增对话，变化记录按批整理，未变化内容通常不重复调用模型 |
| 检测与下班 | 配置间隔、工作日、检测时段，支持中止与下班暂停 |
| 原生工作台 | 浅色 / 深色主题、菜单栏、快捷键与按钮悬停反馈 |
| 桌面小猫 | 可选伴随窗口，展示需要处理、进行中与结果校对等活动状态 |
| 自主配置 | 选择 Codex 应用、CLI、数据目录、分析模型及自己的 SSH 机器 |

完整的任务身份、手动操作、归档与调度规则见[使用指南](docs/user-guide.md)。

## 界面截图与使用演示

下列素材只使用**虚构会话、目标、服务器标签与占位路径**。产品演示结合实际 SwiftUI 界面、动态流程图和隔离的催办模拟；不会调用模型、连接服务器或发送真实消息。

### 46 秒：从“忘了交代什么”到“原 Agent 接着干”

![产品演示：多台机器的会话，经整理 Agent 找回目标，生成跟进清单，再一键催办原 Agent](docs/assets/workflow-demo.gif)

**[观看或下载 1080p / 30 fps 完整宣传片（含原创配乐）](https://github.com/Junming-Liang/coindex/releases/download/v1.9.0/coindex-1.9.0-product-film.mp4)**

| 时间 | 你看到的变化 |
| --- | --- |
| 00–10 秒 | 工作分散在 Mac 与 SSH 机器的多个会话，AI 已回复，你却忘了当初的要求 |
| 10–22 秒 | 整理 Agent 逐个读取会话，把各来源工作汇成目标、进度与下一步清单 |
| 22–30 秒 | 找回一个待验收目标，看到“PR 已提交”之后还缺集成验证 |
| 30–42 秒 | 点击一键催办，带着目标、进度和下一步回到原对话，让原 Agent 继续 |
| 42–46 秒 | 交代过的事，都有下一步 |

动图为无声预览；完整视频包含界面特写、节拍同步的动画与原创电子配乐。**催办送达与 Agent 回复均为标明的流程示意，不代表真实执行或验收完成。**

### 目标跟进清单，实际界面

![Agent 整理后的目标跟进清单：整体目标、当前进度和下一步](docs/assets/overview.png)

### 多个 Codex 对话，统一跟踪

![统一查看本机与虚构 SSH 来源的多个 Codex 对话](docs/assets/conversations.png)

### 一个目标，进度、下一步与依据一起看

![目标详情：整体目标、停住位置、下一步和原文依据](docs/assets/task-detail.png)

### 配置自己的 Codex 与 SSH 来源

<p align="center"><img src="docs/assets/connections.png" width="680" alt="Codex 连接引导与虚构 SSH 会话来源" /></p>

素材来源见 [docs/assets](docs/assets/README.md)，分镜与复现说明见[产品演示制作说明](docs/product-film.md)。也可以本机打开演示模式体验：

```sh
open -n /Applications/coindex.app --args --demo
```

应用安装在其他位置时，请替换路径。公开应用的普通演示模式禁用真实分析与催办；宣传片中的发送状态来自隔离的演示构建。

## 安装

### 系统要求

| 组件 | 要求 |
| --- | --- |
| Mac | macOS 14+；Apple Silicon 或 Intel |
| 本机 Python | Python 3.9+；后端只使用 Python 标准库 |
| 本机 Codex | 已登录；CLI 支持 `--ephemeral`、`--ignore-user-config`、`--ignore-rules`、`--output-schema` |
| 模型访问 | 账号可以访问设置中选择的模型与推理强度 |
| SSH 机器（可选） | Python 3.8+、可读的 Codex 会话目录、免交互 SSH 登录 |

### 下载应用

1. 打开 [Releases](https://github.com/Junming-Liang/coindex/releases/latest)，点击发布说明顶部的 **macOS 安装包**，下载 `coindex-版本-macos-universal.dmg`。
2. 双击打开 DMG，将 `coindex.app` 拖到旁边的 **Applications（应用程序）** 文件夹，再从应用程序中打开。安装完成后推出安装盘。升级前先退出旧版，拖入后选择替换。
3. 安装 Python。已有 Python 3.9+ 可以直接使用；如果使用 [Homebrew](https://brew.sh/)，运行：

   ```sh
   brew install python
   python3 --version
   ```

4. 打开 coindex，按首次连接引导配置 Codex。

应用会查找 `/opt/homebrew/bin/python3`、`/usr/local/bin/python3` 和 `/usr/bin/python3`；Finder 启动的应用通常不会继承终端环境变量。其他 Python 位置的启动方法见[故障排查](docs/troubleshooting.md#找不到-python)。

也保留 `coindex-版本-macos-universal.zip` 兼容下载，解压后拖入应用程序即可。GitHub 自动生成的 **Source code** 是源码，不是安装包。应用与数据分开保存，替换应用不会清除待办和设置。

此版本尚未公证，macOS 可能阻止首次打开。确认下载来自本项目 Release 后，先尝试打开应用，再到「系统设置 → 隐私与安全性」按系统提示选择「仍要打开」。详见 [Apple 的安全打开应用说明](https://support.apple.com/en-us/102445)。若系统提示恶意软件或应用损坏，请停止打开并核对文件。

### 校验下载

同时下载该版本的 `coindex-版本-SHA256SUMS.txt`，在只包含本次下载文件的目录运行：

```sh
shasum -a 256 -c coindex-*-SHA256SUMS.txt
```

所下载的文件应显示 OK；未下载的其他平台或源码包会报告缺少文件，可只核对已下载文件的同名条目。校验值用于检查下载完整性，不代替 Developer ID 签名或 Apple 公证。

### 更新与卸载

应用启动时检查最新公开版本；有更新时展示 GitHub 更新说明，可选择下载或跳过此版本，下个新版本再提醒。也可手动「检查更新」查看已跳过的版本。下载完成后，退出 coindex，用新应用替换旧应用，保留原数据目录。公开版使用 `org.coindex.desktop` 标识；从早期个人构建迁移后，需要重新检查「登录 Mac 时启动」。待办与宠物偏好仍使用相同数据目录。

卸载时退出并移除 `coindex.app`。个人数据不会随应用移除而删除；如需清除，请先备份下方的数据目录，再自行移除。

### Linux 安装

Linux 桌面版使用 Python 3.9+ 和 Tkinter，不需要安装 Python 第三方依赖或管理员权限。Ubuntu / Debian 安装 `python3-tk`；Fedora 安装 `python3-tkinter`。请先确保 `python3` 和 `python3-tk` 来自同一套 Python 环境。

从 [Releases](https://github.com/Junming-Liang/coindex/releases/latest) 下载对应版本的 `coindex-版本-linux.tar.gz` 和 SHA-256 清单，校验后解压并运行其中的安装器。若该发布版本未提供 Linux 包，可从源码构建：

```sh
bash scripts/build-linux.sh
bash dist/coindex-linux/scripts/install-linux.sh
```

如果你已经解压了包含 `coindex-linux/` 目录的发行包，在该目录的父目录运行：

```sh
bash coindex-linux/scripts/install-linux.sh
```

安装器将程序放入 `${XDG_DATA_HOME:-~/.local/share}/coindex-app`，命令行入口放入 `~/.local/bin/coindex`，并创建桌面菜单项。若 `~/.local/bin` 尚未加入 `PATH`，请将它加入当前桌面会话的用户 PATH，或用完整路径启动。可通过 `--prefix` 指定命令行入口前缀；`XDG_DATA_HOME` 按 XDG 规则指定数据根目录。安装器只复制程序，不启动界面、不安装依赖，也不使用 sudo。

待办数据库和设置保存在 `${XDG_DATA_HOME:-~/.local/share}/coindex/`。升级会替换程序文件并保留此目录。卸载时退出应用后，移除程序目录、`~/.local/bin/coindex`、`applications/org.coindex.desktop.desktop` 和图标；待办数据需单独备份并删除。

终端中可使用 `coindex --demo` 启动不连接真实 Codex 的虚构数据演示。Linux 提供原生桌面窗口，不包含 macOS 菜单栏宠物、系统托盘或登录启动。桌面打开和催办取决于当前桌面环境已配置的 `codex://` 协议处理器，以及已有的 Codex 桌面 IPC；读取会话并不保证这些集成功能可用。完整依赖、限制和源码启动方法见 [Linux 指南](docs/linux.md)。

## 快速开始

1. 安装并登录 Codex，在 Codex 中创建至少一个会话。
2. 打开 coindex，首次启动自动进入「设置」。
3. 点击「保存并检查连接」，分别确认 CLI、登录与会话目录状态。
4. 选择「立即更新」。首次扫描逐批整理历史会话，可以随时中止。
5. 需要远程会话时，使用「添加 SSH 机器…」。

首次本机连接检查通过后，自动整理才会启用。检查本身不调用模型、不发送催办；实际分析使用你的 Codex 配额或对应计费方式。默认分析设置是 `gpt-6-luna` / `max`，可改为账号可用的模型与推理强度。

默认每 30 分钟检查变化，启用中国大陆法定工作日规则，按北京时间计算。其他地区可关闭「只在法定工作日检测」。更多规则见[使用指南](docs/user-guide.md#自动检测与下班)。

## 配置 Codex

### 安装与登录

已有 Codex / ChatGPT 桌面应用可在 coindex 中直接选择该应用。也可按 [OpenAI 官方 CLI 安装指南](https://learn.chatgpt.com/docs/codex/cli)安装独立 CLI。当前官方 macOS 安装入口为：

```sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
codex login
codex login status
```

登录通过 Codex 官方流程完成。**不要向 coindex、Issue 或聊天粘贴 `auth.json`、访问令牌或账号密码。**

### 应用内连接

| 设置 | 默认行为 | 何时填写 |
| --- | --- | --- |
| Codex 应用 | 使用系统 `codex://` 关联打开对话 | 自定义位置、多个桌面应用或应用改名 |
| 会话与登录目录 | `CODEX_HOME`，否则 `~/.codex` | 使用独立数据目录 |
| Codex CLI | 自动发现 PATH、常见位置与所选应用内的 CLI | 自动发现失败或需要特定版本 |
| 模型 / 推理强度 | `gpt-6-luna` / `max` | 账号权限不同或调整分析开销 |

手动 CLI 路径优先于应用内部的 CLI。读取、分析登录和本机桌面连接使用同一 Codex 数据目录。自定义目录也要以相同的 `CODEX_HOME` 登录：

```sh
CODEX_HOME="$HOME/.codex-work" codex login
```

随后在设置填写 `~/.codex-work`。连接结果分别显示 CLI、登录、会话读取、桌面连接。桌面连接用于催办；暂未就绪时，会话整理仍可使用。登录成功不代表所有模型都可用。

coindex 使用临时、只读、结构化的 `codex exec` 分析，隔离用户配置并禁用分析工具。参数见 [Codex CLI 参考](https://learn.chatgpt.com/docs/cli/reference)。旧 CLI 不支持所需选项时，请升级或选择更新的应用内置 CLI。

## 配置 SSH

SSH 用于读取远程会话，模型分析仍在 Mac 上通过本机 Codex 登录运行。远程采集不要求安装 coindex，也不安装常驻服务。

### 已有 SSH 别名

若已经可以运行 `ssh dev-server`，点击「添加 SSH 机器…」并选择该别名。应用发现 `~/.ssh/config` 及 `Include` 文件中的具体别名，实际连接由系统 OpenSSH 处理，可沿用跳板机等配置。

以下为**占位示例**，请替换为自己的主机与用户名：

```sshconfig
Host dev-server
    HostName server.example.com
    User developer
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

### 在应用中添加新机器

1. 点击「添加 SSH 机器… → 新机器」，填写连接名称、显示名称、地址与用户。
2. 按需填写端口、密钥路径、远程 Codex 数据目录或 Python 路径。
3. 点击「在终端连接」，从可信渠道核对主机指纹，完成首次连接和密钥登录。
4. 点击「测试 SSH 与会话读取」，成功后保存并启用，下一次更新开始采集。

新机器设置只保存在 coindex，不改写 `~/.ssh/config`。首次终端连接会按 OpenSSH 正常行为保存你确认过的主机指纹。尚未就绪的连接可先保存为停用来源。

### 远程环境准备

- 远程 Python 3.8+，已通过 Codex 创建会话，默认目录 `~/.codex/sessions`。
- Mac 可使用密钥或 ssh-agent 免交互登录；带口令的密钥需先在终端解锁。
- 自定义 `CODEX_HOME` 或 Python 虚拟环境可填写确切路径，避免非交互环境找不到它们。

验证已有别名：

```sh
ssh dev-server
# 在远程终端检查：
python3 --version
test -d ~/.codex/sessions && echo "sessions directory exists"
exit

# 回到 Mac 后检查免交互连接：
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes dev-server true
```

没有配置密钥时，可复制应用里的「SSH 配置引导」给自己的 Agent。只把**公钥**添加到远程 `authorized_keys`，私钥保留在本机。完整步骤见 [SSH 指南](docs/ssh-guide.md)。

后台固定使用 `BatchMode=yes` 与 `StrictHostKeyChecking=yes`，不自动接受指纹、不弹出密码输入框。停用或移除来源保留历史待办；重新添加相同连接名称可继续跟踪。

### 远程跳转与催办

读取、打开对话与催办是独立能力。打开远程对话需要 Codex 桌面认识该 SSH 机器；默认主机 ID 是 `remote-ssh-discovered:<连接名称>`，可在高级设置修改。

远程催办还需要远程已有的共享 Codex 服务，以及支持 `codex app-server proxy` 的 CLI。本机私有 IPC 与共享接口可能随 Codex 版本变化；读取成功不保证催办可用。coindex 不为催办启动新的独立会话引擎。

## 数据与隐私

```text
本机 Codex 会话 ─────┐
                    ├→ 只读采集与凭据遮蔽 → 本机 Codex CLI → 所选模型
启用的 SSH 会话 ─────┘                                    │
                                                        ↓
                                          本机 SQLite → 待办界面
用户主动点击催办 ─────────────────────────→ 原 Codex 对话
```

- **本机保存：** `~/Library/Application Support/CodexTodo/` 保存待办、对话摘录、连接设置、发送回执和宠物偏好。目录权限 `700`，数据库权限 `600`，应按敏感数据保护。
- **模型处理：** 对话摘录经你的 Codex 登录发送到所选模型。coindex 无自建托管分析服务，不额外收集遥测；Codex 的数据处理规则由账号与提供方政策决定。
- **遮蔽边界：** 采集会遮蔽常见 token、密码字段、私钥和 JWT，不能识别所有自由文本敏感信息。敏感来源应停用，或暂停分析。
- **其他请求：** 启用工作日规则时，从公开的 [holiday-cn](https://github.com/NateScarlet/holiday-cn) 下载节假日数据，不携带会话内容。
- **操作边界：** 采集不改写原记录。自动检测不自动催办、不代答、不批准权限；主动点击催办才向原对话追加消息。
- **发布边界：** 公共源码与应用不携带登录文件、私钥、SSH 配置、数据库、真实会话、日志、备份或导入的原版 Codex 宠物。

不要直接把数据目录、真实截图或原始诊断日志上传到公共 Issue。安全报告见 [SECURITY.md](SECURITY.md)。

## 常见问题

| 现象 | 先检查 |
| --- | --- |
| 找不到 Python | Python 3.9+ 和应用可发现的路径 |
| 找不到 CLI / 版本过旧 | 实际 CLI 路径与四个必需参数 |
| 已登录但看不到会话 | 数据目录、至少一个会话、启用与归档状态 |
| 连接成功但分析失败 | 模型、推理强度、账号配额与网络 |
| 终端 SSH 正常，后台失败 | 主机指纹、ssh-agent、免交互登录 |
| 远程目录不存在 | 远程用户、`CODEX_HOME`、读取权限 |
| 可以采集但无法催办 | 原 Codex 服务、桌面 IPC / 远程 proxy 与主机 ID |
| 结果待确认 | 先核对原对话，确认未送达后重试 |

完整步骤见[故障排查](docs/troubleshooting.md)。

## 从源码构建

macOS 构建需要 macOS 14+、Xcode 或 Command Line Tools。Linux 桌面构建需要 Python 3.9+ 和 Tkinter。常规构建与后端测试不需要第三方 Python 库。

```sh
git clone https://github.com/Junming-Liang/coindex.git
cd coindex
xcode-select --install  # 已安装编译工具时跳过
python3 -m unittest discover -s tests -v
bash scripts/build.sh
open dist/coindex.app
```

Linux 桌面构建与源码启动：

```sh
python3 -m unittest discover -s tests -v
bash scripts/build-linux.sh
python3 linux/app.py --demo
```

默认构建当前 Mac 架构；通用构建使用：

```sh
COINDEX_ARCHS="arm64 x86_64" bash scripts/build.sh
```

输出 `dist/coindex.app`，采用 ad hoc 签名。演示模式使用虚构任务，不连接 SSH、不调用模型：

```sh
open -n dist/coindex.app --args --demo
```

开发变量：`CODEX_TODO_DATA_DIR`、`CODEX_TODO_PYTHON`、`CODEX_TODO_CODEX`。使用独立数据目录。无 Codex 的测试方式、Swift 动画验证与发布检查见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 项目结构

```text
Sources/             SwiftUI 界面、连接引导、设计系统与桌面宠物
backend/
  collector.py       只读解析与凭据遮蔽
  connections.py     本机发现、SSH 设置与连接检查
  analyzer.py        隔离的结构化模型分析
  store.py           SQLite、手动决定与待办身份
  service.py         stdin / stdout 服务与调度
  summaries.py       总结范围、工作筛选、模型格式与自动日程
  updates.py         最新稳定版本检查与跳过偏好
  nudge.py           本机催办与持久回执
  remote_rpc.py      SSH 共享服务连接
linux/               Tkinter 桌面与总结界面
scripts/             构建、演示、打包与发布检查
VERSION              双平台统一发布版本
tests/              状态、采集、调度、连接与回执回归测试
docs/               使用、SSH 与故障排查指南
Resources/           品牌与默认小猫插画
```

界面通过进程 stdin / stdout 与后端通信，不开放 HTTP 监听端口。会话格式、桌面私有 IPC 与远程 proxy 依赖 Codex 实际版本，可能需要随上游更新适配。

## 参与贡献

欢迎提交可复现问题、文档改进与 Pull Request。请先读 [CONTRIBUTING.md](CONTRIBUTING.md)，用虚构会话与独立数据目录验证。连接问题提供版本与脱敏错误，不提供私钥、登录文件或真实会话。

- [问题与功能建议](https://github.com/Junming-Liang/coindex/issues/new/choose)
- [更新记录](CHANGELOG.md)
- [安全政策](SECURITY.md)
- [设计规范](DESIGN.md)
- [双平台发布与维护](docs/releases.md)

coindex 是独立社区项目，与 OpenAI 没有官方隶属关系。

## 许可证与致谢

原创代码与随项目发布的原创素材采用 [MIT License](LICENSE)。第三方参考与数据保留各自许可证：

- [OpenAI Codex 文档](https://learn.chatgpt.com/docs/codex/cli)：CLI 与官方使用说明。
- [awesome-design-md](https://github.com/VoltAgent/awesome-design-md)：设计参考，来源与 MIT 许可证见 [design/reference](design/reference/SOURCE.md)。
- [holiday-cn](https://github.com/NateScarlet/holiday-cn)：节假日数据，测试夹具保留[上游许可证](tests/fixtures/holiday-cn.LICENSE)。

从本机 Codex 导入的原版宠物仅用于个人构建，默认构建与公开 Release 不含这些素材。
