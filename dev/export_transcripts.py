"""Copy this project's Claude Code session logs into ai_transcripts/, redacted.

Removes: the account e-mail address, the personal memory index that Claude Code
injects into every session, and inline screenshot image data. Writes the raw
(redacted) JSONL files plus a readable Markdown rendering of the main session.

usage: python3 dev/export_transcripts.py <session.jsonl> [<subagent.jsonl> ...]
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "ai_transcripts"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@gmail\.com|kashishsharma06", re.I)
MEMORY_ENTRY = re.compile(r"(?:\[[^\]\n]*)?\]?\((?:feedback|project|user|reference)_[a-z0-9_]+\.md\)[^\n\\]*")
MEMORY = re.compile(r"(Contents of /Users/[^\n]*/memory/MEMORY\.md|# Memory Index).*?(?=</system-reminder>|\Z)", re.S)
USER_CTX = re.compile(r"# userEmail\n.*?(?=\n# |\Z)", re.S)


def scrub(value):
    if isinstance(value, str):
        value = MEMORY.sub("[personal memory index removed]\n", value)
        value = USER_CTX.sub("# userEmail\n[removed]\n", value)
        value = MEMORY_ENTRY.sub("[memory entry removed]", value)
        return EMAIL.sub("[email removed]", value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        if value.get("type") == "image":
            return {"type": "text", "text": "[screenshot removed]"}
        return {k: scrub(v) for k, v in value.items()}
    return value


def text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            parts.append(block["text"])
        elif kind == "tool_use":
            args = block.get("input", {})
            shown = args.get("command") or args.get("description") or json.dumps(args)[:600]
            parts.append(f"**[tool: {block.get('name')}]**\n```\n{str(shown)[:1500]}\n```")
        elif kind == "tool_result":
            body = block.get("content")
            body = text_of(body) if isinstance(body, list) else str(body)
            parts.append(f"<details><summary>tool result</summary>\n\n```\n{body[:1500]}\n```\n</details>")
    return "\n\n".join(p for p in parts if p.strip())


def main(paths):
    OUT.mkdir(exist_ok=True)
    for i, path in enumerate(map(Path, paths)):
        records = [scrub(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
        name = "claude_session_main.jsonl" if i == 0 else f"claude_subagent_{path.stem}.jsonl"
        (OUT / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        if i == 0:
            lines = ["# Claude Code session (redacted, readable)\n"]
            for r in records:
                msg = r.get("message") or {}
                role = msg.get("role") or r.get("type")
                body = text_of(msg.get("content"))
                if role in ("user", "assistant") and body.strip():
                    lines.append(f"## {role}\n\n{body}\n")
            (OUT / "claude_session_readable.md").write_text("\n".join(lines))
        print(f"wrote {name} ({len(records)} records)")


if __name__ == "__main__":
    main(sys.argv[1:])
