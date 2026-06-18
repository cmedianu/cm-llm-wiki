#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""PostToolUse hook: stamp `updated: <yyyy-MM-dd>` on edited wiki pages.

Lives in the cm-llm-wiki master repo; symlinked into a vault at `.claude/hooks/`
(like `skills` and `wiki-scripts`). It is opt-in *per vault* — only vaults that
register it in their own `.claude/settings.json` (PostToolUse, matcher
`Edit|Write|MultiEdit`) run it, so it can be scoped to a single vault.

Design:
- Complements the Obsidian "Update time on edit" plugin, which stamps edits made
  *in the app*. This covers edits made by the agent on disk. Both write the same
  `updated: yyyy-MM-dd` field in the same format, so same-day writes are
  byte-identical (idempotent) and the two mechanisms never fight.
- Deliberately does NOT touch the plugin's `fileHashMap` cache: that file is
  owned by Obsidian and lives in the (often cloud-synced) `.obsidian/`, so a
  second writer would risk sync-conflict corruption. Same-day idempotency makes
  it unnecessary.
- Never blocks the tool: any error exits 0 silently.

Wiring (per vault — this is what makes it opt-in / single-vault):
  1. Symlink this dir into the vault, alongside skills + wiki-scripts:
        ln -s /path/to/cm-llm-wiki/hooks  <vault>/.claude/hooks
  2. Register it in the VAULT's own .claude/settings.json (NOT the global
     ~/.claude/settings.json — keeping it here is what scopes it to one vault):
        {
          "hooks": {
            "PostToolUse": [
              {
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [
                  {
                    "type": "command",
                    "command": "uv run --script \"$CLAUDE_PROJECT_DIR/.claude/hooks/update-timestamp.py\""
                  }
                ]
              }
            ]
          }
        }
  $CLAUDE_PROJECT_DIR is set by Claude Code to the vault root; the script also
  uses it to ignore any edited file that lives outside the vault.
"""
import sys
import os
import json
import re
import datetime
import pathlib

# Non-page files (kept in sync with the wiki skills' allow-list).
SKIP_NAMES = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md",
              "AGENTS.md", "_insights.md"}
SKIP_DIR_PARTS = {"_sources", ".obsidian", ".claude", ".git", ".trash"}


def run():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    tool_input = data.get("tool_input", {}) or {}
    fp = tool_input.get("file_path") or tool_input.get("path")
    if not fp:
        return

    path = pathlib.Path(fp)
    if path.suffix != ".md":
        return
    try:
        abspath = path.resolve()
    except Exception:
        return

    # Scope to the vault that registered the hook.
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    if proj:
        try:
            abspath.relative_to(pathlib.Path(proj).resolve())
        except ValueError:
            return  # edited file is outside this vault

    if path.name in SKIP_NAMES:
        return
    if SKIP_DIR_PARTS & set(abspath.parts):
        return
    if not abspath.exists():
        return

    text = abspath.read_text(encoding="utf-8")
    # Only touch pages that already have YAML frontmatter; never add it.
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.DOTALL)
    if not m:
        return

    today = datetime.date.today().isoformat()  # yyyy-MM-dd, local tz
    fm_lines = m.group(1).split("\n")
    out = []
    found = False
    for ln in fm_lines:
        key = re.match(r"^(updated:\s*)(.*)$", ln)
        if key:
            found = True
            current = key.group(2).strip().strip('"').strip("'").rstrip("\r")
            if current == today:
                return  # already stamped today -> no write, no churn
            out.append(f"{key.group(1)}{today}")
        else:
            out.append(ln)

    if not found:
        # Insert after `created:` if present, else at the end of the block.
        rebuilt, placed = [], False
        for ln in out:
            rebuilt.append(ln)
            if not placed and re.match(r"^created:\s*", ln):
                rebuilt.append(f"updated: {today}")
                placed = True
        if not placed:
            rebuilt.append(f"updated: {today}")
        out = rebuilt

    new_text = text[:m.start(1)] + "\n".join(out) + text[m.end(1):]
    if new_text != text:
        abspath.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        pass  # never block the editing tool
    sys.exit(0)
