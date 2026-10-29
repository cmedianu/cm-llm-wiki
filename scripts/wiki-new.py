#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Scaffold a new wiki page with valid frontmatter.

Writes `<category>/<slug>.md` with date-only created/updated, lifecycle: draft,
title, category (= the folder), tags and summary, then the body (from --body-file,
stdin with `--body-file -`, or a `# Title` stub). Refuses a name that is not
kebab-case-lowercase, a folder that does not exist (unless --mkdir), a page that
already exists, and a summary over 200 characters, so the page passes the
pre-commit gate the first time instead of failing at commit.

--supersedes <page> also wires the previous dated snapshot: superseded_by -> the
new page, lifecycle: archived, lifecycle_changed: today (one-line frontmatter
edits, formatting and line endings preserved).

Usage:
  uv run .claude/wiki-scripts/wiki-new.py finance/position-review-2026-10-27 \\
      --title "Position review 2026-10-27" --tags finance,review \\
      --summary "Quarterly position review." \\
      --supersedes finance/position-review-2026-09-21 --body-file -  <<'MD'
  ...body...
  MD

Prints the vault-relative path it wrote. Exit 2 on a refused name or argument.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import sys
from typing import Optional

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def resolve_vault(explicit: Optional[str] = None) -> pathlib.Path:
    """Resolve the active vault, in priority order:
      1. explicit --vault override (must be an existing directory);
      2. walk up from CWD to the first dir containing .manifest.json (stop at $HOME or /);
      3. map CWD (or nearest ancestor) via ~/.obsidian-wiki/projects.json to a vault
         name, then read OBSIDIAN_VAULT_PATH from ~/.obsidian-wiki/config.<name>;
      4. the OBSIDIAN_VAULT_PATH env var (back-compat).
    Exit with a clear message if none apply."""
    if explicit:
        v = pathlib.Path(explicit).expanduser().resolve()
        if not v.is_dir():
            raise SystemExit(f"--vault path does not exist or is not a directory: {v}")
        return v
    cwd = pathlib.Path.cwd()
    home = pathlib.Path.home()
    for d in [cwd] + list(cwd.parents):
        if (d / ".manifest.json").is_file():
            return d
        if d == home or d == pathlib.Path("/"):
            break
    v = _vault_from_projects(cwd)
    if v is not None:
        return v
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return pathlib.Path(env).expanduser()
    raise SystemExit(
        "No vault found. Looked for .manifest.json walking up from the current "
        "directory, then for a match in ~/.obsidian-wiki/projects.json. "
        "Pass --vault <path> to point at the vault explicitly."
    )


def _vault_from_projects(start: pathlib.Path) -> Optional[pathlib.Path]:
    """Map CWD (or nearest ancestor) → vault via ~/.obsidian-wiki/projects.json and
    the referenced config.<name>'s OBSIDIAN_VAULT_PATH. None if no mapping applies."""
    reg = pathlib.Path.home() / ".obsidian-wiki"
    try:
        projects = json.loads((reg / "projects.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(projects, dict):
        return None
    name = None
    for d in [start] + list(start.parents):
        if str(d) in projects:
            name = projects[str(d)]
            break
    if not name:
        return None
    try:
        text = (reg / f"config.{name}").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = re.match(r"^\s*OBSIDIAN_VAULT_PATH=(.+)$", line.strip())
        if m:
            return pathlib.Path(m.group(1).strip()).expanduser()
    return None


def yaml_scalar(value: str) -> str:
    """Quote a value only when YAML would misread it (colon-space, leading metachar)."""
    if not value or ": " in value or " #" in value or value[0] in "#&*[]{}>|@`!%'\"," \
            or value.strip() != value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def wire_superseded(page: pathlib.Path, target_rel: str, today: str) -> bool:
    raw = page.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = (raw[3:] if bom else raw).decode("utf-8").split("\n")
    if not lines or lines[0].rstrip("\r").strip() != "---":
        return False
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r").strip() == "---"), None)
    if end is None:
        return False
    updates = [("superseded_by", target_rel), ("lifecycle", "archived"), ("lifecycle_changed", today)]
    positions = {}
    for key, _ in updates:
        for i in range(1, end):
            m = re.match(rf"{key}:(.*)$", lines[i].rstrip("\r"))
            if m:
                if not m.group(1).strip() and i + 1 < end and lines[i + 1][:1] in (" ", "\t"):
                    return False  # block value: not a line we can swap safely
                positions[key] = i
                break
    eol = "\r" if lines[0].endswith("\r") else ""
    for key, value in updates:
        if key in positions:
            lines[positions[key]] = f"{key}: {value}{eol}"
        else:
            lines.insert(end, f"{key}: {value}{eol}")
            end += 1
    page.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "\n".join(lines).encode("utf-8"))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a new wiki page with valid frontmatter.")
    ap.add_argument("page", help="vault-relative path without .md, e.g. sysadmin/backup/nightly-plan")
    ap.add_argument("--title", required=True)
    ap.add_argument("--summary", required=True, help="one line, <= 200 characters")
    ap.add_argument("--tags", default="", help="comma-separated")
    ap.add_argument("--lifecycle", default="draft", choices=["draft", "reviewed", "living", "archived"])
    ap.add_argument("--sources", default="", help="comma-separated paths or URLs (optional)")
    ap.add_argument("--body-file", help="file with the page body; '-' reads stdin")
    ap.add_argument("--supersedes", help="vault-relative page this one replaces (dated snapshots)")
    ap.add_argument("--mkdir", action="store_true", help="create the folder if missing")
    ap.add_argument("--vault", default=None, help="vault root; auto-detected if omitted")
    args = ap.parse_args()

    vault = resolve_vault(args.vault)
    rel = args.page.strip().strip("/")
    if rel.endswith(".md"):
        rel = rel[:-3]
    parts = rel.split("/")
    if len(parts) < 2:
        ap.error("give category/slug: a page lives in a category folder")
    bad = [p for p in parts if not KEBAB_RE.fullmatch(p)]
    if bad:
        ap.error(f"not kebab-case-lowercase: {', '.join(bad)}")
    if any(p.startswith(("_", ".")) for p in parts) or parts[0] == "templates":
        ap.error("that folder is not wiki content")
    if len(args.summary) > 200:
        ap.error(f"summary is {len(args.summary)} characters (max 200)")
    folder = vault.joinpath(*parts[:-1])
    if not folder.is_dir():
        if not args.mkdir:
            ap.error(f"folder {'/'.join(parts[:-1])}/ does not exist (pass --mkdir to create it)")
        folder.mkdir(parents=True)
    path = folder / f"{parts[-1]}.md"
    if path.exists():
        ap.error(f"{rel}.md already exists")
    old: Optional[pathlib.Path] = None
    if args.supersedes:
        s = args.supersedes.strip().strip("/").removesuffix(".md").strip("[]")
        old = vault / f"{s}.md"
        if not old.is_file():
            ap.error(f"--supersedes: {s}.md not found")

    today = datetime.date.today().isoformat()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    fm = ["---", f"title: {yaml_scalar(args.title)}", f"category: {'/'.join(parts[:-1])}",
          f"tags: [{', '.join(yaml_scalar(t) for t in tags)}]",
          f"summary: {yaml_scalar(args.summary)}", f"lifecycle: {args.lifecycle}"]
    srcs = [x.strip() for x in args.sources.split(",") if x.strip()]
    if srcs:
        fm.append("sources:")
        fm += [f"  - {yaml_scalar(x)}" for x in srcs]
    fm += [f"created: {today}", f"updated: {today}", "---", ""]
    if args.body_file == "-":
        body = sys.stdin.read()
    elif args.body_file:
        body = pathlib.Path(args.body_file).read_text(encoding="utf-8")
    else:
        body = f"# {args.title}\n"
    path.write_text("\n".join(fm) + body.lstrip("\n").rstrip("\n") + "\n", encoding="utf-8")
    print(f"{rel}.md")
    if old is not None:
        if wire_superseded(old, rel, today):
            print(f"superseded {old.relative_to(vault).as_posix()} -> {rel}")
        else:
            print(f"could not wire {args.supersedes}: edit its frontmatter by hand", file=sys.stderr)
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
