#!/usr/bin/env python3
"""Stop hook: nudge Claude to update CLAUDE.md when a session changed source
code but did not update the docs afterward.

Claude Code passes the Stop-hook payload on stdin as JSON, including:
  - transcript_path: path to this session's JSONL transcript
  - stop_hook_active: true when we're already inside a stop-hook continuation

We scan the transcript for Edit/Write/MultiEdit tool calls. If any *source*
file was edited AFTER the last time CLAUDE.md was edited (or CLAUDE.md was
never edited), we return decision="block" with a reason so Claude reconsiders
documenting the change. The judgement of "is this feature doc-worthy?" stays
with Claude; this hook only enforces the habit.
"""
import json
import os
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SOURCE_EXT = (".py", ".html", ".js", ".jsx", ".ts", ".tsx", ".css", ".svg")
DOC_NAME = "CLAUDE.md"


def find_edit_paths(obj, out):
    """Recursively collect file_paths from edit-tool tool_use blocks."""
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use" and obj.get("name") in EDIT_TOOLS:
            fp = (obj.get("input") or {}).get("file_path", "")
            if fp:
                out.append(fp)
        for v in obj.values():
            find_edit_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_edit_paths(v, out)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Already continuing because of a previous stop-hook block -> let it stop.
    if data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = data.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    last_doc_idx = -1
    source_edits = []  # (order_index, path)
    order = 0

    with open(transcript_path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            paths = []
            find_edit_paths(entry, paths)
            for fp in paths:
                if os.path.basename(fp) == DOC_NAME:
                    last_doc_idx = order
                elif fp.endswith(SOURCE_EXT):
                    source_edits.append((order, fp))
                order += 1

    pending = [fp for (i, fp) in source_edits if i > last_doc_idx]
    if not pending:
        sys.exit(0)

    files = ", ".join(sorted({os.path.basename(p) for p in pending})[:8])
    reason = (
        "This session edited source files (" + files + ") but did not update "
        + DOC_NAME + " afterward. If this work added or changed something "
        + DOC_NAME + " documents (a feature, route, blueprint, model/field, "
        "config or branding var, convention, or command), update " + DOC_NAME
        + " now so it stays accurate — and the auto-memory if relevant. "
        "If the change is trivial (a bugfix or refactor with no documented "
        "behavior change), no update is needed: briefly say so, then stop."
    )

    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
