#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""PostToolUse hook: stamp `updated: <yyyy-MM-dd>` on edited wiki pages.

Lives in the cm-llm-wiki master repo; symlinked into a vault at `.claude/hooks/`
(like `wiki-scripts` and `wiki-conventions.md`). One script serves the three
supported agents; their PostToolUse stdin payloads are near-identical by design:

- **Claude Code**: registered in the VAULT's `.claude/settings.json` (NOT the
  global `~/.claude/settings.json`; keeping it in the vault is what scopes it to
  that vault), matcher `Edit|Write|MultiEdit`. `wire-vault.sh` seeds this file.
  Edited path arrives as `tool_input.file_path`.
- **Copilot CLI**: registered via the vault's `.github/hooks` (symlinked to this
  repo's `hooks/copilot/`). Uses the PascalCase/Claude-compatible event format, so
  the payload matches Claude's shape.
- **Codex CLI**: registered via the vault's generated `.codex/hooks.json`
  (written by `wire-vault.sh`; run `/hooks` in Codex once per vault to trust it).
  Codex edits files through `apply_patch`, whose input is a patch envelope, so
  the edited paths are parsed out of `*** Update|Add File:` lines.

Design:
- Complements the Obsidian "Update time on edit" plugin, which stamps edits made
  *in the app*. This covers edits made by an agent on disk. Both write the same
  `updated: yyyy-MM-dd` field in the same format, so same-day writes are
  byte-identical (idempotent) and the mechanisms never fight.
- Deliberately does NOT touch the plugin's `fileHashMap` cache: that file is
  owned by Obsidian and lives in the (often cloud-synced) `.obsidian/`, so a
  second writer would risk sync-conflict corruption. Same-day idempotency makes
  it unnecessary.
- Never blocks the tool: any error exits 0 silently.
- Scoping: only files inside the vault are touched. The vault root comes from
  `$CLAUDE_PROJECT_DIR` (Claude) or the payload's `cwd` (Codex/Copilot both
  include it), which also anchors the relative paths in Codex patches.
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
SKIP_DIR_PARTS = {"_sources", ".obsidian", ".claude", ".codex", ".github",
                  ".git", ".trash"}

# Codex `apply_patch` envelope: one line per touched file.
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add) File: (.+?)\s*$", re.MULTILINE)


def candidate_paths(data: dict) -> list[str]:
    """Edited file paths from a Claude-, Copilot-, or Codex-shaped payload."""
    tool_input = data.get("tool_input") or data.get("toolArgs") or {}
    if not isinstance(tool_input, dict):
        return []
    for key in ("file_path", "filePath", "path"):
        fp = tool_input.get(key)
        if isinstance(fp, str) and fp:
            return [fp]
    # Codex apply_patch: scan string values for the patch envelope.
    found = []
    for v in tool_input.values():
        if isinstance(v, str) and "*** " in v:
            found.extend(PATCH_FILE_RE.findall(v))
    return found


def stamp(fp: str, root: pathlib.Path | None):
    path = pathlib.Path(fp)
    if path.suffix != ".md":
        return
    if not path.is_absolute() and root is not None:
        path = root / path  # Codex patch paths are relative to the session cwd
    try:
        abspath = path.resolve()
    except Exception:
        return

    # Scope to the vault that registered the hook.
    if root is not None:
        try:
            abspath.relative_to(root.resolve())
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


def run():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    root = pathlib.Path(proj) if proj else None
    for fp in candidate_paths(data):
        try:
            stamp(fp, root)
        except Exception:
            pass  # one bad path must not stop the others


if __name__ == "__main__":
    try:
        run()
    except Exception:
        pass  # never block the editing tool
    sys.exit(0)
