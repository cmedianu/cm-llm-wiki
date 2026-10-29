#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Land a session's vault changes as a few grouped Conventional Commits.

The agent decides the grouping and writes the messages; this script owns the
mechanics that used to go wrong: staging by name (never `git add -A`), keeping the
journal and manifest whole in one commit instead of splitting their hunks, running
the gate on each commit, and surfacing files that belong to no group (another
session's leftovers) instead of sweeping them in.

The plan is plain text on stdin (or --plan FILE): a commit message line, then the
paths for that commit indented below it. Blank lines and `#` comments are ignored.

  docs(sysadmin): record the x2 freeze investigation
    sysadmin/x2/freeze-log.md
    sysadmin/x2/aspm.md
  docs(home): add the furnace filter schedule
    home/furnace.md

Sidecars (.manifest.json, log.md, hot.md) that are modified but not listed ride
whole in the LAST group. --journal 'LINE' first runs `wiki-journal.py --log LINE`
(it also feeds hot.md), so the journal entry lands in that same commit and never
needs a separate chore(journal) commit.

Usage:
  uv run .claude/wiki-scripts/wiki-commit.py [--journal 'CAPTURE page=[[x]] gist'] \\
      [--dry-run] [--plan FILE] <<'PLAN'
  ...
  PLAN

Refuses to start when something is already staged (it would be swept into the first
commit). Stops at the first commit the gate rejects; earlier commits stay. Exit 0
when every group committed, 1 when it stopped, 2 on a bad plan.
"""
import argparse
import pathlib
import subprocess
import sys

SIDECARS = (".manifest.json", "log.md", "hot.md")
FORBIDDEN = {".", "*", ":/", "-A", "--all", "-u"}


def git(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], text=True, encoding="utf-8", errors="replace",
                          capture_output=capture, check=check)


def parse_plan(text: str) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if not groups:
                raise ValueError(f"path before any commit message: {line.strip()}")
            groups[-1][1].append(line.strip())
        else:
            groups.append((line.strip(), []))
    for msg, paths in groups:
        if not paths:
            raise ValueError(f"no paths under: {msg}")
        bad = [p for p in paths if p in FORBIDDEN or p.startswith("-")]
        if bad:
            raise ValueError(f"stage paths by name, not {', '.join(bad)}")
    return groups


def dirty_paths() -> list[str]:
    """Modified, deleted and untracked paths relative to the work tree root."""
    out = git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    paths, tokens, i = [], out.split("\0"), 0
    while i < len(tokens) and tokens[i]:
        entry = tokens[i]
        paths.append(entry[3:])
        i += 2 if entry[0] in "RC" else 1  # a rename carries its old path next
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Land vault changes as grouped commits.")
    ap.add_argument("--plan", help="plan file (default: stdin)")
    ap.add_argument("--journal", metavar="LINE", help="run wiki-journal.py --log LINE first")
    ap.add_argument("--dry-run", action="store_true", help="show what would be committed")
    args = ap.parse_args()

    try:
        top = pathlib.Path(git("rev-parse", "--show-toplevel").stdout.strip())
    except subprocess.CalledProcessError:
        print("wiki-commit: not inside a git work tree", file=sys.stderr)
        return 2
    try:
        groups = parse_plan(pathlib.Path(args.plan).read_text(encoding="utf-8")
                            if args.plan else sys.stdin.read())
    except (OSError, ValueError) as e:
        print(f"wiki-commit: bad plan: {e}", file=sys.stderr)
        return 2
    if not groups:
        print("wiki-commit: empty plan", file=sys.stderr)
        return 2

    import os
    os.chdir(top)
    if git("diff", "--cached", "--quiet", check=False).returncode != 0:
        staged = git("diff", "--cached", "--name-only").stdout.split()
        print("wiki-commit: something is already staged; commit or unstage it first:\n  "
              + "\n  ".join(staged), file=sys.stderr)
        return 2

    if args.journal and not args.dry_run:
        journal = top / ".claude" / "wiki-scripts" / "wiki-journal.py"
        r = subprocess.run(["uv", "run", "--script", str(journal), "--vault", str(top),
                            "--log", args.journal])
        if r.returncode != 0:
            print("wiki-commit: wiki-journal refused the entry; nothing committed", file=sys.stderr)
            return 1

    dirty = set(dirty_paths())
    listed = {p.rstrip("/") for _, paths in groups for p in paths}
    riders = [s for s in SIDECARS if s in dirty and s not in listed]
    if riders:
        groups[-1][1].extend(riders)

    missing = [p for _, paths in groups for p in paths
               if not (top / p).exists() and p not in dirty]
    if missing:
        print("wiki-commit: not found and not a tracked deletion: " + ", ".join(missing), file=sys.stderr)
        return 2

    covered = lambda d: any(d == p or d.startswith(p.rstrip("/") + "/") for p in listed | set(riders))
    leftovers = sorted(d for d in dirty if not covered(d))

    for msg, paths in groups:
        if args.dry_run:
            print(f"{msg}\n    " + "\n    ".join(paths))
            continue
        git("add", "--", *paths)
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            print(f"skipped (no changes): {msg}")
            continue
        r = git("commit", "-q", "-m", msg, check=False, capture=False)
        if r.returncode != 0:
            git("reset", "-q", check=False)
            again = " (without --journal: the entry is already written)" if args.journal else ""
            print(f"wiki-commit: the gate rejected '{msg}'; fix the findings above and rerun "
                  f"the remaining groups{again}", file=sys.stderr)
            return 1
        print(git("log", "--oneline", "-1").stdout.strip())

    if leftovers:
        print("\nNot in any group (left alone; another session's work, or yours to add):")
        for d in leftovers:
            print(f"  {d}")
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
