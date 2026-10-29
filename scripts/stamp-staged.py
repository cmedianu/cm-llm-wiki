#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Stamp `updated: <today>` on staged wiki pages whose content changed.

The PostToolUse hook stamps pages edited through an agent's Edit/Write tools, but
pages edited through a shell (heredocs, sed -i, scripts, another editor) never pass
through it. This runs from the git pre-commit hook and closes that gap for every
agent and every edit path:

  for each staged, added-or-modified content page (same rule as wiki-lint: not in a
  dot/_ dir, not templates/, not a root daily note, not index/log/hot/README/...)
  whose `updated:` is not already today, rewrite that one frontmatter line in the
  working file (CRLF and BOM preserved) and re-stage it.

A partially staged file (working tree differs from the index) is left alone, since
re-adding it would stage hunks the author chose not to commit; a note is printed.
A page without frontmatter or without an `updated:` key is left for wiki-lint to
report. Exit 0 always: stamping is a convenience, the lint gate decides.

Usage (from inside the vault's git work tree):
  uv run --script .claude/wiki-scripts/stamp-staged.py [--dry-run]
"""
import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys

SCAFFOLDING = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md", "AGENTS.md"}
DAILY_NOTE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
UPDATED_RE = re.compile(r"^(updated:[ \t]*)(.*?)([ \t]*)$")


def is_content_page(rel: str) -> bool:
    parts = pathlib.PurePosixPath(rel).parts
    if not parts or any(p.startswith((".", "_")) for p in parts):
        return False
    if parts[-1] in SCAFFOLDING or parts[0].lower() == "templates":
        return False
    return not (len(parts) == 1 and DAILY_NOTE_RE.fullmatch(parts[0]))


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def stamp(path: pathlib.Path, today: str) -> bool:
    """Rewrite the `updated:` line in place. True if the file changed."""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    lines = text.split("\n")  # keeps a trailing \r on CRLF lines
    if not lines or lines[0].rstrip("\r").strip() != "---":
        return False
    for i in range(1, len(lines)):
        body = lines[i].rstrip("\r")
        cr = lines[i][len(body):]
        if body.strip() == "---":
            return False  # no updated: key in the block
        m = UPDATED_RE.match(body)
        if m:
            current = m.group(2).strip().strip("'\"")
            if current == today:
                return False
            lines[i] = f"{m.group(1)}{today}{m.group(3)}{cr}"
            out = "\n".join(lines).encode("utf-8")
            path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + out)
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = ap.parse_args()
    try:
        top = pathlib.Path(git("rev-parse", "--show-toplevel").stdout.strip())
        names = git("diff", "--cached", "--name-only", "--diff-filter=AMR", "-z").stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"stamp-staged: git failed, skipping ({e})", file=sys.stderr)
        return 0
    today = datetime.date.today().isoformat()
    for rel in filter(None, names.split("\0")):
        if not rel.endswith(".md") or not is_content_page(rel):
            continue
        path = top / rel
        if git("diff", "--quiet", "--", rel, check=False).returncode != 0:
            print(f"stamp-staged: {rel} is partially staged; not stamping it", file=sys.stderr)
            continue
        try:
            if args.dry_run:
                print(f"would stamp {rel}")
                continue
            if stamp(path, today):
                git("add", "--", rel)
                print(f"stamped updated: {today}  {rel}")
        except (OSError, UnicodeDecodeError) as e:
            print(f"stamp-staged: {rel}: {e}; skipped", file=sys.stderr)
    return 0


# --- run log (copied verbatim into every script, like resolve_vault) ---------
# One TSV line per run in ~/.obsidian-wiki/runs.tsv: when, script, cwd, seconds,
# exit code, args, and any RUN_STATS the script filled in. Machine-local, never
# inside a vault; `claude-history.py runs` summarizes it. WIKI_RUNLOG=0 disables.
# Never raises: logging must not break the tool.
RUN_STATS: dict = {}


def log_run(t0: float, rc) -> None:
    import os as _os, sys as _sys, time as _time
    from datetime import datetime as _dt
    if _os.environ.get("WIKI_RUNLOG") == "0":
        return
    try:
        d = __import__("pathlib").Path.home() / ".obsidian-wiki"
        d.mkdir(exist_ok=True)
        fields = [_dt.now().isoformat(timespec="seconds"),
                  __import__("pathlib").Path(_sys.argv[0]).name, _os.getcwd(),
                  f"{_time.monotonic() - t0:.2f}", str(rc), " ".join(_sys.argv[1:])[:300],
                  " ".join(f"{k}={v}" for k, v in RUN_STATS.items())]
        with open(d / "runs.tsv", "a", encoding="utf-8") as fh:
            fh.write("\t".join(f.replace("\t", " ").replace("\n", " ") for f in fields) + "\n")
    except Exception:
        pass
# --- end run log -------------------------------------------------------------


if __name__ == "__main__":
    import time as _time
    _t0, _rc = _time.monotonic(), 1
    try:
        _rc = main()
        _rc = 0 if _rc is None else _rc
    except SystemExit as _e:
        _rc = _e.code if isinstance(_e.code, int) else (0 if _e.code is None else 1)
        raise
    finally:
        log_run(_t0, _rc)
    sys.exit(_rc)
