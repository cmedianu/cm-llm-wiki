#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
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
  include it), which also anchors the relative paths in Codex patches. With
  neither, the hook does nothing (it never stamps a .md outside a known vault).
- Only content pages are stamped (the shared rule below): never dot/_ dirs
  (`_raw/`, `_sources/`), `templates/`, root `yyyy-MM-dd.md` daily notes, or
  scaffolding such as index.md / log.md / hot.md.
"""
import sys
import os
import json
import re
import datetime
import pathlib

# --- content-page rule (pasted verbatim into every script; scripts never import
# each other). A vault-relative .md path is NOT a content page when any component
# starts with "." or "_" (.obsidian, _raw, _sources, _archives), its first
# component is "templates" (Obsidian templates folder), it is a root-level
# yyyy-MM-dd.md daily note, or its basename is scaffolding.
NON_PAGE_NAMES = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md", "AGENTS.md"}
_DAILY_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def is_content_page(rel) -> bool:
    """True iff the vault-relative path `rel` (str or path) is a content page."""
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
    if not parts:
        return False
    if any(p.startswith((".", "_")) for p in parts):
        return False
    if parts[0] == "templates":
        return False
    if len(parts) == 1 and _DAILY_NOTE_RE.match(parts[0]):
        return False
    return parts[-1] not in NON_PAGE_NAMES
# --- end content-page rule

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


def stamp(fp: str, root: pathlib.Path):
    path = pathlib.Path(fp)
    if path.suffix != ".md":
        return
    if not path.is_absolute():
        path = root / path  # Codex patch paths are relative to the session cwd
    try:
        abspath = path.resolve()
    except Exception:
        return

    # Scope to the vault that registered the hook.
    try:
        rel = abspath.relative_to(root.resolve())
    except ValueError:
        return  # edited file is outside this vault

    if not is_content_page(rel.as_posix()):
        return  # dot/_ dirs, templates/, daily notes, scaffolding
    if not abspath.exists():
        return

    # newline="" keeps CRLF intact: only the frontmatter lines we touch change,
    # so a Windows-authored page never becomes a whole-file line-ending diff.
    with open(abspath, encoding="utf-8", newline="") as f:
        text = f.read()
    # A UTF-8 BOM (Notepad, PowerShell Set-Content) would hide the frontmatter
    # fence; strip it for matching and put it back on write.
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    text = text[len(bom):]
    # Only touch pages that already have YAML frontmatter; never add it.
    m = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        return
    eol = "\r\n" if text.startswith("---\r\n") else "\n"

    today = datetime.date.today().isoformat()  # yyyy-MM-dd, local tz
    fm_lines = re.split(r"\r?\n", m.group(1))
    out = []
    found = False
    for ln in fm_lines:
        key = re.match(r"^(updated:\s*)(.*)$", ln)
        if key:
            found = True
            current = key.group(2).strip().strip('"').strip("'")
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

    new_text = text[:m.start(1)] + eol.join(out) + text[m.end(1):]
    if new_text != text:
        with open(abspath, "w", encoding="utf-8", newline="") as f:
            f.write(bom + new_text)
        hook_log("stamped", rel.as_posix())


def hook_log(status: str, detail: str) -> None:
    """One line in ~/.obsidian-wiki/runs.tsv when the hook stamps or fails (silence
    otherwise), so a missed stamp is visible after the fact. WIKI_RUNLOG=0 disables."""
    if os.environ.get("WIKI_RUNLOG") == "0":
        return
    try:
        d = pathlib.Path.home() / ".obsidian-wiki"
        d.mkdir(exist_ok=True)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        line = "\t".join([now, "update-timestamp.py", os.getcwd(), "0", status, detail, ""])
        with open(d / "runs.tsv", "a", encoding="utf-8") as fh:
            fh.write(line.replace("\n", " ") + "\n")
    except Exception:
        pass


def run():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    if not proj:
        return  # no vault root known: never stamp an arbitrary .md
    root = pathlib.Path(proj)
    for fp in candidate_paths(data):
        try:
            stamp(fp, root)
        except Exception as e:  # one bad path must not stop the others
            hook_log("failed", f"{fp}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:  # never block the editing tool
        hook_log("failed", f"{type(e).__name__}: {e}")
    sys.exit(0)
