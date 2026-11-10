# SSH 配置指南

coindex 使用 Mac 自带 OpenSSH，只读采集你选择的远程 Codex 会话，不安装远程服务。以下地址、账号与路径都是占位示例。

## 已有别名

先确认 `ssh dev-server` 可以登录，再在「设置 → 添加 SSH 机器…」选择该别名。点击「在终端连接」完成指纹确认和密钥解锁，之后「测试 SSH 与会话读取」，通过后保存并启用。应用发现 `~/.ssh/config` 与 `Include` 中的具体别名，OpenSSH 负责实际配置。

## 首次配置密钥

先检查已有密钥，不必覆盖或重复创建。没有合适密钥时可创建专用密钥：

```sh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_coindex -C "coindex"
```

按提示选择口令。将 `.pub` 文件里的**公钥**追加到远程用户 `~/.ssh/authorized_keys`，可通过管理员或远程控制台完成。不覆盖现有列表、不上传私钥。远程目录权限通常为 `700`，授权文件为 `600`。

Mac 配置示例：

```sshconfig
Host dev-server
    HostName server.example.com
    User developer
    IdentityFile ~/.ssh/id_ed25519_coindex
    IdentitiesOnly yes
```

从可信渠道取得主机指纹，再运行 `ssh dev-server` 核对。`ssh-keyscan` 不能独立证明服务器身份。指纹变化时先核实，不关闭校验。

带口令的密钥可先加载到 ssh-agent：

```sh
ssh-add ~/.ssh/id_ed25519_coindex
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes dev-server true
```

最后一条命令无需输入并成功后，再进行应用测试。coindex 不保存密码与私钥口令。

## 应用里的新机器

连接名称是稳定来源标识，例如 `dev-server`；显示名称可自由修改。地址与用户填写目标机器信息，端口留空沿用配置。密钥字段只保存路径，不复制私钥。

高级字段包含远程 Codex 数据目录、Python、Codex CLI 与桌面主机 ID。Python 默认 `python3`，目录默认远程 `CODEX_HOME` 或 `~/.codex`。新机器仅保存在 coindex，不改写 SSH 配置；未就绪时可保存为停用状态。

## 跳板机

复杂配置建议使用系统 SSH 别名：

```sshconfig
Host gateway
    HostName gateway.example.com
    User developer

Host dev-server
    HostName internal.example.com
    User developer
    ProxyJump gateway
    IdentityFile ~/.ssh/id_ed25519_coindex
```

先在终端核对并连接跳板机与目标机器，再在应用选择 `dev-server`。会话采集无需启用 SSH agent 转发。

## 远程环境

远程 Python 需 3.8+，对应用户已经创建 Codex 会话，并有目录读取权限。非交互 SSH 未必加载 shell 初始化文件；虚拟环境和自定义目录请在应用中填写完整路径。

```sh
python3 --version
test -d ~/.codex/sessions && echo "sessions directory exists"
```

开启 Claude Code 来源后，同一连接还会只读采集远程 Claude 会话；默认目录 `~/.claude/projects`，自定义目录在连接高级设置的「远程 Claude 数据目录」填写。Claude 目录不可读时连接检查会单独提示，不影响 Codex 采集。

## 读取、跳转与催办

读取只需 SSH、Python 与会话目录。跳转需要 Mac 的 Codex 桌面认识该主机，默认 ID 是 `remote-ssh-discovered:dev-server`。催办还需要远程已有共享 Codex 服务和支持 `app-server proxy` 的 CLI。

不要随意启动新的独立 app-server 并把它当成原会话服务。coindex 沿用原会话权限；待授权和回答时应回到 Codex 处理。

停用或删除连接保留历史；显示名称可改。重新添加原连接名称可继续跟踪原来源。
