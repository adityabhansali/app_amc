#!/usr/bin/env python3
"""PostToolUse hook: remind to run /compact whenever CLAUDE.md is updated.

Claude Code fires PostToolUse after a tool finishes and passes the payload on
stdin as JSON, including:
  - tool_name:  the tool that just ran (Edit / Write / MultiEdit / ...)
  - tool_input: the tool's arguments (for edit tools this carries file_path)

When the edited file is CLAUDE.md we emit a `systemMessage` (shown to the user)
nudging a /compact run. NOTE: hooks cannot themselves invoke the /compact slash
command — there is no hook event or output field that starts a compaction. This
hook only surfaces the reminder; the actual /compact is run by the user (or by
auto-compaction). It is intentionally silent for every other file so it never
gets in the way.
"""
import json
import os
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_NAME = "CLAUDE.md"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") not in EDIT_TOOLS:
        sys.exit(0)

    fp = (data.get("tool_input") or {}).get("file_path", "")
    if not fp or os.path.basename(fp) != DOC_NAME:
        sys.exit(0)

    msg = (
        DOC_NAME + " was just updated — run /compact to fold the latest project "
        "state into a fresh, compacted context."
    )
    print(json.dumps({"systemMessage": msg}))
    sys.exit(0)


if __name__ == "__main__":
    main()
