"""Portable connection settings and read-only checks; no credentials are stored here."""
import glob
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}\Z")
CLI_SUFFIXES = ("Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                "Contents/Resources/codex", "Contents/MacOS/codex")
LINUX_CLI_SUFFIXES = ("resources/codex", "resources/codex-cli/codex",
                      "resources/app/node_modules/@openai/codex/bin/codex")


def text(value, label, limit=4096):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(label + "格式无效")
    return value.strip()


def normalize_remote(value):
    if not isinstance(value, dict):
        raise ValueError("SSH 连接格式无效")
    alias = text(value.get("id", ""), "连接名称", 253)
    if not ALIAS.fullmatch(alias) or alias in ("mac", "manual", "all"):
        raise ValueError("连接名称需以字母或数字开头，只能包含字母、数字、点、短横线和下划线")
    result = {"id": alias, "name": text(value.get("name", alias), "显示名称", 100) or alias}
    for key, label in (("hostname", "地址"), ("user", "用户名"), ("identity_file", "密钥路径"),
                       ("codex_home", "远程 Codex 数据目录"), ("claude_home", "远程 Claude 数据目录"),
                       ("python", "远程 Python"), ("codex_cli", "远程 Codex CLI"), ("host_id", "Codex 主机 ID")):
        result[key] = text(value.get(key, ""), label)
    if result["hostname"] and (result["hostname"].startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", result["hostname"])):
        raise ValueError("请填写主机名或 IP 地址；跳板机可通过 SSH 别名配置")
    if result["user"] and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", result["user"]):
        raise ValueError("SSH 用户名无效")
    port = value.get("port", 0)
    if isinstance(port, bool):
        raise ValueError("SSH 端口无效")
    if port not in (None, "") and (not isinstance(port, (int, str)) or not re.fullmatch(r"\d+", str(port))):
        raise ValueError("SSH 端口无效")
    result["port"] = int(port or 0)
    if not 0 <= result["port"] <= 65535:
        raise ValueError("SSH 端口需在 1–65535 之间，留空则使用 SSH 配置")
    return result


def normalize_settings(settings):
    for key in ("codex_home", "codex_cli", "codex_app", "claude_home"):
        settings[key] = text(settings.get(key, ""), "连接路径")
    settings["claude_enabled"] = bool(settings.get("claude_enabled", False))
    remotes = settings.get("remote_hosts", [])
    if not isinstance(remotes, list) or len(remotes) > 64:
        raise ValueError("最多添加 64 个 SSH 连接")
    settings["remote_hosts"] = [normalize_remote(item) for item in remotes]
    ids = [item["id"] for item in settings["remote_hosts"]]
    if len(ids) != len(set(ids)):
        raise ValueError("SSH 连接名称重复")
    enabled = settings.get("enabled_hosts", [])
    if not isinstance(enabled, list) or any(h not in ["mac"] + ids for h in enabled):
        raise ValueError("请先添加对应的 SSH 连接，再启用该来源")
    settings["enabled_hosts"] = list(dict.fromkeys(enabled))
    model = text(settings.get("analysis_model", "gpt-6-luna"), "模型名称", 100)
    if not model or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model):
        raise ValueError("模型名称无效")
    settings["analysis_model"] = model
    if settings.get("analysis_effort", "max") not in ("minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
        raise ValueError("推理强度无效")
    return settings


def codex_home(settings=None):
    return pathlib.Path((settings or {}).get("codex_home") or os.environ.get("CODEX_HOME") or pathlib.Path.home()/".codex").expanduser().resolve()


def codex_path(settings=None):
    settings = settings or {}
    override = settings.get("codex_cli") or os.environ.get("CODEX_TODO_CODEX")
    if override:
        candidate = pathlib.Path(override).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        raise RuntimeError("设置的 Codex CLI 无法执行，请重新选择或清空路径以自动发现")
    app = settings.get("codex_app")
    if app and (sys.platform == "darwin" or pathlib.Path(app).suffix == ".app"):
        for suffix in CLI_SUFFIXES:
            candidate = pathlib.Path(app).expanduser()/suffix
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        raise RuntimeError("所选应用中找不到 Codex CLI，请选择 CLI 文件或重新选择应用")
    if app and sys.platform.startswith("linux"):
        executable = pathlib.Path(app).expanduser()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError("设置的 Codex 桌面程序无法执行")
        for suffix in LINUX_CLI_SUFFIXES:
            candidate = executable.parent/suffix
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
    found = shutil.which("codex")
    if found:
        return found
    roots = [pathlib.Path.home()/"Applications", pathlib.Path("/Applications")]
    candidates = [pathlib.Path.home()/p for p in (".local/bin/codex", ".codex/bin/codex", ".npm-global/bin/codex")]
    candidates += sorted((pathlib.Path.home()/".nvm/versions/node").glob("*/bin/codex"), reverse=True)
    if sys.platform.startswith("linux"):
        linux_roots = [pathlib.Path("/opt/Codex"), pathlib.Path("/opt/codex"), pathlib.Path("/opt/ChatGPT"), pathlib.Path("/opt/chatgpt")]
        if app:
            linux_roots.insert(0, pathlib.Path(app).expanduser().parent)
        candidates += [root/suffix for root in linux_roots for suffix in LINUX_CLI_SUFFIXES]
    candidates += [root/(name+".app")/suffix for root in roots for name in ("Codex", "ChatGPT") for suffix in CLI_SUFFIXES]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise RuntimeError("找不到 Codex CLI，请安装并登录 Codex，或在连接设置中选择应用 / CLI")


def profile(settings, host):
    if host == "mac":
        return {"id": "mac", "codex_home": str(codex_home(settings)), "host_id": "local"}
    for item in settings.get("remote_hosts", []):
        if item["id"] == host:
            return normalize_remote(item)
    raise ValueError("SSH 来源已移除，请重新添加连接")


def desktop_host_id(settings, host):
    entry = profile(settings, host)
    return entry.get("host_id") or "remote-ssh-discovered:" + host


def ssh_command(entry, interactive=False):
    entry = normalize_remote(entry)
    args = ["/usr/bin/ssh"]
    if not interactive:
        args += ["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10",
                 "-o", "ServerAliveCountMax=2", "-o", "StrictHostKeyChecking=yes"]
    else:
        args += ["-o", "StrictHostKeyChecking=ask"]
    if entry["hostname"]:
        args += ["-o", "HostName=" + entry["hostname"]]
    if entry["user"]:
        args += ["-l", entry["user"]]
    if entry["port"]:
        args += ["-p", str(entry["port"])]
    if entry["identity_file"]:
        args += ["-i", str(pathlib.Path(entry["identity_file"]).expanduser())]
    return args + [entry["id"]]


def ssh_aliases(config=None):
    """Discover concrete aliases, including Include files; ssh resolves their actual options."""
    aliases, visited = set(), set()
    base = pathlib.Path.home()/".ssh"
    def read(filename, depth=0):
        filename = pathlib.Path(filename).expanduser()
        if depth > 8 or str(filename) in visited:
            return
        visited.add(str(filename))
        try:
            lines = filename.read_text().splitlines()
        except (OSError, UnicodeError):
            return
        for line in lines:
            try:
                parts = shlex.split(line, comments=True)
            except ValueError:
                continue
            if not parts:
                continue
            key, _, initial = parts[0].partition("=")
            values = ([initial] if initial else []) + parts[1:]
            if key.lower() == "host":
                aliases.update(v for v in values if ALIAS.fullmatch(v) and v not in ("mac", "manual", "all"))
            elif key.lower() == "include":
                for value in values:
                    p = pathlib.Path(value).expanduser()
                    for match in glob.glob(str(p if p.is_absolute() else base/p))[:128]:
                        read(match, depth+1)
    read(config or base/"config")
    return sorted(aliases)


def local_check(settings):
    """Check collection, executable, sign-in and optional desktop broker independently."""
    from collector import redact
    root = codex_home(settings)
    sessions = root/"sessions"
    readable = sessions.is_dir() and os.access(sessions, os.R_OK | os.X_OK)
    result = {"root": str(root), "sessions_ready": readable, "cli": "", "version": "",
              "login_ready": False, "desktop_ready": False, "detail": ""}
    notes = []
    try:
        cli = codex_path(settings)
        result["cli"] = cli
        env = dict(os.environ, CODEX_HOME=str(root))
        version = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=8, env=env)
        result["version"] = redact(version.stdout.strip())[:200]
        help_result = subprocess.run([cli, "exec", "--help"], capture_output=True, text=True, timeout=8, env=env)
        required = ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--output-schema")
        compatible = help_result.returncode == 0 and all(flag in help_result.stdout for flag in required)
        result["cli_compatible"] = compatible
        login = subprocess.run([cli, "login", "status"], capture_output=True, text=True, timeout=8, env=env)
        result["login_ready"] = login.returncode == 0
        notes.append("Codex CLI 已找到" if version.returncode == 0 else "Codex CLI 无法运行")
        if not compatible:
            notes.append("当前 CLI 不支持所需的隔离分析选项，请更新 Codex CLI 或选择较新的应用")
        notes.append("已登录" if result["login_ready"] else "请先在 Codex 中登录")
    except Exception as error:
        notes.append(redact(str(error))[:300])
    try:
        sample = next(sessions.rglob("*.jsonl"), None) if readable else None
        if sample:
            with sample.open("rb") as source:
                source.read(1)
    except OSError:
        result["sessions_ready"] = False
    notes.append("会话目录可读取" if result["sessions_ready"] else "无法读取 sessions 目录，请检查目录位置、权限或先创建一个会话")
    if settings.get("claude_enabled"):
        from claude_collector import claude_root
        projects = claude_root(settings)/"projects"
        claude_ready = projects.is_dir() and os.access(projects, os.R_OK | os.X_OK)
        try:
            sample = next(projects.rglob("*.jsonl"), None) if claude_ready else None
            if sample:
                with sample.open("rb") as source:
                    source.read(1)
        except OSError:
            claude_ready = False
        result["claude_ready"] = claude_ready
        notes.append("Claude 会话目录可读取" if claude_ready else "无法读取 Claude projects 目录，请检查目录位置、权限或先创建一个 Claude 会话")
    try:
        from nudge import DesktopIPC
        ipc = DesktopIPC(root/"ipc/ipc.sock")
        try:
            ipc.connect()
            result["desktop_ready"] = True
        finally:
            ipc.close()
    except Exception:
        pass
    notes.append("桌面连接可用" if result["desktop_ready"] else "桌面催办连接未就绪；可打开 Codex 后重试")
    result["detail"] = "；".join(notes)
    result["ok"] = result["sessions_ready"] and result["login_ready"] and bool(result["version"]) and result.get("cli_compatible", False)
    return result


REMOTE_CHECK = """import json,os,pathlib,sys
request=json.loads(sys.stdin.read())
root=pathlib.Path(request.get('root') or os.environ.get('CODEX_HOME') or str(pathlib.Path.home()/'.codex')).expanduser().resolve()
sessions=root/'sessions'
ready=sessions.is_dir() and os.access(sessions,os.R_OK|os.X_OK) and sys.version_info>=(3,8)
try:
 sample=next(sessions.rglob('*.jsonl'),None) if ready else None
 if sample:
  with sample.open('rb') as source: source.read(1)
except OSError: ready=False
result={'ok':ready,'root':str(root),'sessions_ready':ready,'detail':'SSH 已连接，Python 可用，会话目录可读取' if ready else 'SSH 已连接，但会话目录无法读取或 Python 版本过旧；请检查 Codex 数据目录、读取权限及 Python 3.8+'}
if request.get('claude_enabled'):
 projects=pathlib.Path(request.get('claude_root') or os.environ.get('CLAUDE_CONFIG_DIR') or str(pathlib.Path.home()/'.claude')).expanduser().resolve()/'projects'
 claude_ready=projects.is_dir() and os.access(projects,os.R_OK|os.X_OK)
 try:
  sample=next(projects.rglob('*.jsonl'),None) if claude_ready else None
  if sample:
   with sample.open('rb') as source: source.read(1)
 except OSError: claude_ready=False
 result['claude_ready']=claude_ready
 result['detail']+='；Claude 会话目录可读取' if claude_ready else '；无法读取 Claude projects 目录，请检查远程 Claude 数据目录'
print(json.dumps(result))
"""


def remote_check(entry, claude_enabled=False):
    from collector import redact
    entry = normalize_remote(entry)
    args = ssh_command(entry) + [shlex.quote(entry["python"] or "python3") + " -c " + shlex.quote(REMOTE_CHECK)]
    try:
        run = subprocess.run(args, input=json.dumps({"root": entry["codex_home"], "claude_enabled": bool(claude_enabled),
                                                   "claude_root": entry["claude_home"]}), capture_output=True, text=True, timeout=20)
        if run.returncode:
            detail = redact(run.stderr.strip())[:600] or "SSH 连接失败"
            detail += "；请先在终端连接，核对主机指纹并完成密钥登录，然后重新测试。远程需要 Python 3。"
            return {"ok": False, "detail": detail}
        return json.loads(run.stdout)
    except Exception as error:
        return {"ok": False, "detail": redact(str(error))[:600]}
