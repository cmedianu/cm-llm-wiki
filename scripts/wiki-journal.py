#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""wiki-journal.py — mechanical updater for a vault's log.md and hot.md.

The *distillation* (what to say) stays with the LLM; this script owns the
*plumbing* (where it goes, timestamps, trimming) so a skill doesn't burn
Read+Edit round-trips on boilerplate.

Usage
-----
    # append one log line (verb + body; timestamp is added automatically)
    wiki-journal.py --log 'INGEST source="~/Downloads/x.md" pages_updated=1 pages_created=0 mode=append'

    # prepend a Recent-Activity entry to hot.md, bump `updated:`, keep newest 10
    wiki-journal.py --hot-entry '**Did a thing.** Detail with [[wikilinks]].' --hot-trim 10

    # both at once (the common ingest/capture case)
    wiki-journal.py \
        --log 'INGEST source="..." pages_updated=1 pages_created=0 mode=append' \
        --hot-entry '**Merged the C: cleanup audit...** ...' --hot-trim 10

    # --log alone also prepends the same line to hot.md (pass --no-hot to skip)
    wiki-journal.py --log 'CAPTURE page=[[some-page]] one-line gist' --hot-trim 10

Notes
-----
* `--vault` defaults to the auto-detected vault (walk up from CWD for .manifest.json,
  then ~/.obsidian-wiki/projects.json); log.md / hot.md must sit at its root.
* The log timestamp is real wall-clock local time (ISO-8601 with numeric
  offset, e.g. `2026-07-21T23:48:30-07:00`), or date-only with `--date-only`.
  Older log lines may end in `Z` (pre-local-time UTC stamps); trimming accepts
  both. hot.md's `updated:` is always set to today's date (local), matching
  the update-timestamp hook.
* hot.md is created from a minimal template if missing. log.md is created empty.
* `--hot-entry` text is the bullet body WITHOUT the leading "- "; a leading
  "- " is stripped if present. Multi-line entries: embed "\n" and the script
  keeps them as one entry. When omitted, `--log` text is used (unless --no-hot).
* A `--log` body is one distilled line: over 240 characters is rejected (put
  the detail on the page and link it). When log.md grows past 50 KB it is
  rotated automatically: older entries roll into _archives/log-<year>.md (as
  with --log-trim) and the newest ~25 KB stay.
* A warning goes to stderr when hot.md (body, excluding frontmatter) exceeds
  600 words; hot.md is read by every wiki skill, so keep it short.
* Exit 0 on success; nonzero with a message on malformed input.
"""

import argparse
import datetime as _dt
import json
import os
import pathlib
import re
import sys
from pathlib import Path
from typing import Optional

RECENT_HEADING = "## Recent Activity"
LOG_ENTRY_MAX_CHARS = 240           # --log bodies longer than this are rejected
LOG_ROTATE_BYTES = 50 * 1024        # auto-rotate log.md past this size...
LOG_ROTATE_KEEP_BYTES = 25 * 1024   # ...keeping roughly this much of the newest entries
HOT_WARN_WORDS = 600                # warn when hot.md's body exceeds this


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

HOT_TEMPLATE = """---
title: Hot Cache
updated: {date}
---
## Recent Activity
## Active Threads
## Key Takeaways
## Flagged Contradictions
"""


Fmt = tuple[str, str]  # (eol, bom) of a file on disk
_LF: Fmt = ("\n", "")


def _read_doc(path: Path) -> tuple[str, Fmt]:
    """Read a sidecar as (text with LF line ends and no BOM, (eol, bom)).

    Opened with newline="" so a CRLF file (Windows / OneDrive vaults) is
    detected and written back as CRLF instead of becoming a whole-file diff; a
    UTF-8 BOM (Notepad, PowerShell Set-Content) is stripped so the frontmatter
    and headings still match, and restored on write."""
    try:
        with path.open(encoding="utf-8", newline="") as f:
            raw = f.read()
    except UnicodeDecodeError as e:
        # Never rewrite a file we cannot round-trip; leave it untouched.
        raise SystemExit(f"error: {path} is not valid UTF-8 ({e.reason} at byte "
                         f"{e.start}); re-save it as UTF-8 and re-run. Nothing written.")
    bom = "\ufeff" if raw.startswith("\ufeff") else ""
    raw = raw[len(bom):]
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), (eol, bom)


def _write_doc(path: Path, text: str, fmt: Fmt = _LF) -> None:
    """Write LF-normalised `text` back with the file's original EOL and BOM."""
    eol, bom = fmt
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(bom + (text.replace("\n", eol) if eol != "\n" else text))


def _tail_eol(path: Path) -> str:
    """EOL style of an existing file, sniffed from its last 4 KB (O(1))."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read()
    except OSError:
        return "\n"
    return "\r\n" if b"\r\n" in tail else "\n"


def _now_local() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _today(date_override: str | None) -> str:
    if date_override:
        return date_override
    return _now_local().strftime("%Y-%m-%d")


def _log_timestamp(ts_override: str | None, date_only: bool) -> str:
    if ts_override:
        return ts_override
    now = _now_local()
    if date_only:
        return now.strftime("%Y-%m-%d")
    return now.isoformat(timespec="seconds")


def append_log(vault: Path, body: str, timestamp: str) -> str:
    """O(1) append — never reads or rewrites the existing log."""
    log_path = vault / "log.md"
    line = f"- [{timestamp}] {body.strip()}"
    prefix = ""
    eol = "\n"
    if log_path.exists() and log_path.stat().st_size > 0:
        eol = _tail_eol(log_path)
        with log_path.open("rb") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                prefix = eol
    with log_path.open("a", encoding="utf-8", newline="") as f:
        f.write(prefix + line.replace("\n", eol) + eol)
    return line


_ENTRY_RE = re.compile(r"^- \[(\d{4})-\d{2}-\d{2}")


def trim_log(vault: Path, keep: int | None = None, keep_bytes: int | None = None) -> dict:
    """Roll all but the newest `keep` entries into _archives/log-<year>.md.

    With `keep_bytes` instead of `keep`, keep as many of the newest entries as
    fit in that many bytes (at least one) — the auto-rotation path.

    Assumes the canonical log shape: optional frontmatter, then chronological
    (oldest-first) `- [timestamp] ...` entries, each possibly multi-line.
    """
    log_path = vault / "log.md"
    if not log_path.exists():
        return {"rolled": 0, "kept": 0}
    text, fmt = _read_doc(log_path)
    lines = text.split("\n")

    head: list[str] = []
    i = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                break
        head = lines[: i + 1]
        i += 1

    entries: list[list[str]] = []
    cur: list[str] | None = None
    for ln in lines[i:]:
        if ln.startswith("- ["):
            if cur is not None:
                entries.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
        elif ln.strip():
            head.append(ln)  # pre-entry prose/heading stays in place
    if cur is not None:
        entries.append(cur)

    if keep is None:
        budget = keep_bytes or 0
        keep, used = 0, 0
        for e in reversed(entries):
            size = len("\n".join(e).encode("utf-8")) + 1
            if keep and used + size > budget:
                break
            used += size
            keep += 1

    if len(entries) <= keep:
        return {"rolled": 0, "kept": len(entries)}

    if keep:
        roll, kept = entries[:-keep], entries[-keep:]
    else:
        roll, kept = entries, []
    archive_dir = vault / "_archives"
    archive_dir.mkdir(exist_ok=True)
    by_year: dict[str, list[str]] = {}
    for e in roll:
        m = _ENTRY_RE.match(e[0])
        year = m.group(1) if m else "undated"
        by_year.setdefault(year, []).extend(e)
    for year, body_lines in by_year.items():
        dest = archive_dir / f"log-{year}.md"
        if dest.exists():
            prev, dest_fmt = _read_doc(dest)
        else:
            prev, dest_fmt = f"# Wiki log archive — {year}\n", (fmt[0], "")
        if not prev.endswith("\n"):
            prev += "\n"
        _write_doc(dest, prev + "\n".join(body_lines).rstrip("\n") + "\n", dest_fmt)
    out = head + [""] if head else []
    out += [ln for e in kept for ln in e]
    _write_doc(log_path, "\n".join(out).rstrip("\n") + "\n", fmt)
    return {"rolled": len(roll), "kept": len(kept), "years": sorted(by_year)}


def _bump_updated(lines: list[str], date: str) -> bool:
    """Set `updated:` inside the first front-matter block. Returns True if changed."""
    if not lines or lines[0].strip() != "---":
        return False
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        if lines[i].startswith("updated:"):
            new = f"updated: {date}"
            if lines[i] != new:
                lines[i] = new
                return True
            return False
    return False


def _split_recent_entries(block: list[str]) -> tuple[list[str], list[list[str]]]:
    """Split a Recent Activity block into (preamble, [entry, ...]).

    An entry starts at a top-level "- " line and runs until the next one.
    Preamble is anything before the first entry (usually empty / blank lines).
    """
    preamble: list[str] = []
    entries: list[list[str]] = []
    cur: list[str] | None = None
    for ln in block:
        if ln.startswith("- "):
            if cur is not None:
                entries.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
        else:
            preamble.append(ln)
    if cur is not None:
        entries.append(cur)
    return preamble, entries


def hot_word_count(vault: Path) -> int:
    """Words in hot.md's body (frontmatter excluded); 0 if missing/unreadable."""
    try:
        text, _ = _read_doc(vault / "hot.md")
    except (OSError, SystemExit):
        return 0
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4:]
    return len(text.split())


def update_hot(vault: Path, entry: str | None, date: str, trim: int | None) -> dict:
    hot_path = vault / "hot.md"
    if not hot_path.exists():
        hot_path.write_text(HOT_TEMPLATE.format(date=date), encoding="utf-8")
    text, fmt = _read_doc(hot_path)
    lines = text.split("\n")

    # locate Recent Activity block
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == RECENT_HEADING)
    except StopIteration:
        print(f"error: '{RECENT_HEADING}' heading not found in {hot_path}", file=sys.stderr)
        sys.exit(2)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break

    block = lines[start + 1 : end]
    preamble, entries = _split_recent_entries(block)

    added = False
    if entry is not None:
        text = entry.strip()
        if text.startswith("- "):
            text = text[2:]
        new_entry = text.split("\n")  # allow multi-line entries
        new_entry[0] = "- " + new_entry[0]
        entries.insert(0, new_entry)
        added = True

    trimmed = 0
    if trim is not None and len(entries) > trim:
        trimmed = len(entries) - trim
        entries = entries[:trim]

    new_block: list[str] = list(preamble)
    for e in entries:
        new_block.extend(e)

    lines = lines[: start + 1] + new_block + lines[end:]
    bumped = _bump_updated(lines, date)

    _write_doc(hot_path, "\n".join(lines), fmt)
    return {"added": added, "trimmed": trimmed, "bumped": bumped, "count": len(entries)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mechanical log.md / hot.md updater.")
    ap.add_argument("--vault", default=None, help="vault root (default: auto-detected via .manifest.json walk-up / projects.json)")
    ap.add_argument("--log", metavar="BODY", help='log line body after the timestamp, e.g. \'INGEST source="..." ...\'')
    ap.add_argument("--hot-entry", metavar="TEXT", help="Recent Activity bullet body (no leading '- '); defaults to the --log text")
    ap.add_argument("--no-hot", action="store_true", help="with --log, do not also prepend it to hot.md")
    ap.add_argument("--hot-trim", type=int, metavar="N", help="keep only the newest N Recent Activity entries")
    ap.add_argument("--log-trim", type=int, metavar="N", help="keep only the newest N log entries; roll older ones into _archives/log-<year>.md")
    ap.add_argument("--date", help="override today's date (YYYY-MM-DD) for hot.md updated:")
    ap.add_argument("--ts", help="override the log timestamp verbatim")
    ap.add_argument("--date-only", action="store_true", help="use a date-only log timestamp")
    args = ap.parse_args()

    if not args.log and not args.hot_entry and args.hot_trim is None and args.log_trim is None:
        ap.error("nothing to do: pass --log, --hot-entry, --log-trim, and/or --hot-trim")
    if args.log_trim is not None and args.log_trim < 0:
        ap.error("--log-trim must be >= 0")
    if args.log:
        n = len(args.log.strip())
        if n > LOG_ENTRY_MAX_CHARS:
            print(
                f"error: --log entry is {n} chars; the limit is {LOG_ENTRY_MAX_CHARS}. "
                "log.md takes ONE distilled line (verb + key facts), not a paragraph. "
                "Put the detail on the wiki page itself and reference it, e.g. "
                "--log 'CAPTURE page=[[some-page]] one-line gist'. Nothing written.",
                file=sys.stderr,
            )
            return 2
    hot_entry = args.hot_entry
    if hot_entry is None and args.log and not args.no_hot:
        hot_entry = args.log

    vault = resolve_vault(args.vault)

    out: list[str] = []
    if args.log:
        line = append_log(vault, args.log, _log_timestamp(args.ts, args.date_only))
        out.append(f"log.md += {line}")

    if args.log_trim is not None:
        res = trim_log(vault, args.log_trim)
        if res["rolled"]:
            out.append(f"log.md — rolled {res['rolled']} entries into _archives/log-{{{','.join(res['years'])}}}.md, kept {res['kept']}")
        else:
            out.append(f"log.md — nothing to roll ({res['kept']} entries <= {args.log_trim})")
    elif args.log and (vault / "log.md").stat().st_size > LOG_ROTATE_BYTES:
        res = trim_log(vault, keep_bytes=LOG_ROTATE_KEEP_BYTES)
        if res["rolled"]:
            out.append(f"log.md — over {LOG_ROTATE_BYTES // 1024} KB: auto-rotated {res['rolled']} entries into _archives/log-{{{','.join(res['years'])}}}.md, kept {res['kept']}")

    if hot_entry is not None or args.hot_trim is not None:
        res = update_hot(vault, hot_entry, _today(args.date), args.hot_trim)
        bits = []
        if res["added"]:
            bits.append("entry prepended")
        if res["trimmed"]:
            bits.append(f"trimmed {res['trimmed']} old")
        bits.append(f"{res['count']} entries")
        bits.append("updated: bumped" if res["bumped"] else "updated: already current")
        out.append("hot.md — " + ", ".join(bits))
        words = hot_word_count(vault)
        if words > HOT_WARN_WORDS:
            print(
                f"warning: hot.md is {words} words (> {HOT_WARN_WORDS}); every wiki skill "
                "reads it. Trim it: pass --hot-trim N, drop session-scoped sections and "
                "stale threads, keep only what the next session needs.",
                file=sys.stderr,
            )

    print("\n".join(out))
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
