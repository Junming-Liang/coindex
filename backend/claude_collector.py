"""Read-only Claude Code session collector. Also runs over SSH, without remote installation."""
import collections
import hashlib
import json
import os
import pathlib
import re
import sys
import time

from collector import HEAD_BYTES, TAIL_BYTES, redact, timestamp

VERSION = 1
UUID_NAME = re.compile(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$", re.I)


def claude_root(settings=None):
    return pathlib.Path((settings or {}).get("claude_home") or os.environ.get("CLAUDE_CONFIG_DIR")
                        or pathlib.Path.home() / ".claude").expanduser().resolve()


def clean_text(text):
    # Local command echoes and injected reminders are not the user's work goal.
    for tag in ("command-name", "command-message", "command-args", "local-command-stdout",
                "local-command-stderr", "system-reminder"):
        text = re.sub(r"<" + tag + r"(?:\s[^>]*)?>[\s\S]*?</" + tag + r">", "", text)
    text = re.sub(r"<(?:command-name|command-message|command-args)\s*/>", "", text)
    return text.strip()


def block_text(content):
    """Text blocks only; thinking and tool payloads never become message text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def tool_output(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def parse_session(path, host):
    stat = path.stat()
    with path.open("rb") as f:
        head = f.read(HEAD_BYTES)
        if HEAD_BYTES < stat.st_size <= HEAD_BYTES + TAIL_BYTES:
            f.seek(0)
            raw = f.read()
        elif stat.st_size > HEAD_BYTES + TAIL_BYTES:
            f.seek(stat.st_size - TAIL_BYTES)
            tail = f.read().split(b"\n", 1)[-1]
            raw = head.rsplit(b"\n", 1)[0] + b"\n" + tail
        else:
            raw = head
    session_id = None
    match = UUID_NAME.search(path.name)
    if match:
        session_id = match.group(1)
    cwd = ""
    title = ""
    custom_title = ""
    messages = []
    tools = collections.deque(maxlen=8)
    seen = set()
    active = False
    last_event = 0
    malformed = 0
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            malformed += 1
            continue
        if not isinstance(item, dict):
            continue
        typ = item.get("type")
        if typ == "summary":
            if isinstance(item.get("summary"), str) and item["summary"].strip():
                title = item["summary"].strip()
            continue
        if typ == "custom-title":
            if isinstance(item.get("customTitle"), str) and item["customTitle"].strip():
                custom_title = item["customTitle"].strip()
            continue
        if typ not in ("user", "assistant") or item.get("isSidechain") or item.get("isMeta"):
            continue
        if isinstance(item.get("sessionId"), str) and item["sessionId"]:
            session_id = item["sessionId"]
        if not cwd and isinstance(item.get("cwd"), str):
            cwd = item["cwd"]
        stamp = timestamp(item.get("timestamp"), stat.st_mtime)
        message = item.get("message") or {}
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        # Claude has no turn-complete events: the latest stop reason decides.
        # end_turn closes a turn; tool_use/null means work was still in flight.
        last_event = stamp
        if typ == "assistant":
            active = message.get("stop_reason") != "end_turn"
            text = block_text(content)
            if text.strip():
                messages.append({"role": "assistant", "text": redact(text)[:9000], "at": stamp})
        else:
            active = True
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        output = tool_output(block.get("content"))
                        if output.strip():
                            tools.append({"role": "tool", "text": redact(output)[-1800:], "at": stamp})
            text = clean_text(block_text(content))
            if text.strip() and not text.startswith("Caveat:"):
                messages.append({"role": "user", "text": redact(text)[:9000], "at": stamp})
    unique = []
    for message in messages:
        key = (message["role"], message["text"], message["at"])
        if key not in seen:
            seen.add(key)
            unique.append(message)
    users = [m for m in unique if m["role"] == "user"]
    if not users or not session_id:
        return None
    recent = unique[-18:]
    if users[0] not in recent:
        recent.insert(0, users[0])
    while len(json.dumps(recent, ensure_ascii=False)) > 32000 and len(recent) > 3:
        recent.pop(1)
    recent += list(tools)[-4:]
    recent.sort(key=lambda m: m["at"])
    digest = hashlib.sha256(json.dumps([unique[-18:], list(tools), active], sort_keys=True).encode()).hexdigest()
    return {
        "id": host + ":" + str(session_id), "thread_id": str(session_id), "host": host, "agent": "claude",
        "title": redact(custom_title or title or users[0]["text"].splitlines()[0])[:180],
        "cwd": cwd, "path": str(path), "messages": recent,
        "fingerprint": digest, "updated_at": max([m["at"] for m in unique] + [m["at"] for m in tools] + [last_event]),
        "active": active, "last_event_at": last_event,
        "truncated": stat.st_size > HEAD_BYTES + TAIL_BYTES or len(unique) > len(recent),
        "malformed_lines": malformed,
    }


def collect(request):
    host = request.get("host", "mac")
    root = pathlib.Path(request.get("root") or os.environ.get("CLAUDE_CONFIG_DIR")
                        or str(pathlib.Path.home() / ".claude")).expanduser().resolve()
    projects = root / "projects"
    if not projects.is_dir():
        raise RuntimeError("Claude projects 目录不存在: " + str(projects))
    known = request.get("known", {})
    limit = min(max(int(request.get("limit", 40)), 1), 300)
    days = int(request.get("days", 0))
    cutoff = time.time() - days * 86400 if days else 0
    candidates = {}
    for path in projects.rglob("*.jsonl"):
        try:
            s = path.stat()
            if s.st_mtime >= cutoff:
                candidates[str(path)] = (s.st_mtime_ns, s.st_size)
        except OSError:
            continue
    # Signatures carry the agent and parser version, so a version bump re-reads
    # Claude files without touching Codex cursors in the same table.
    changed = [(p, s) for p, s in candidates.items() if known.get(p) != ["claude", VERSION, s[0], s[1]]]
    changed.sort(key=lambda x: x[1][0], reverse=True)
    conversations, files, errors = [], {}, []
    for name, stat in changed[:limit]:
        try:
            conversation = parse_session(pathlib.Path(name), host)
            if conversation:
                conversations.append(conversation)
            files[name] = ["claude", VERSION, stat[0], stat[1]]
        except (OSError, ValueError) as e:
            errors.append({"path": name, "error": type(e).__name__})
    return {"host": host, "root": str(root), "conversations": conversations, "files": files,
            "archive_states": {}, "total_files": len(candidates), "remaining_files": max(0, len(changed) - limit),
            "read_errors": errors, "collected_at": time.time(), "collector_version": VERSION}


def merge(primary, secondary):
    """Combine the Codex and Claude legs of one host into a single ingest result."""
    primary["conversations"] = primary.get("conversations", []) + secondary.get("conversations", [])
    files = dict(primary.get("files", {}))
    files.update(secondary.get("files", {}))
    primary["files"] = files
    for key in ("total_files", "remaining_files"):
        primary[key] = primary.get(key, 0) + secondary.get(key, 0)
    primary["read_errors"] = primary.get("read_errors", []) + secondary.get("read_errors", [])
    return primary


if __name__ == "__main__":
    try:
        print(json.dumps(collect(json.load(sys.stdin)), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"error": redact(str(error))[:500]}))
        sys.exit(1)