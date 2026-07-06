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

Notes
-----
* `--vault` defaults to the current directory; log.md / hot.md must sit at its root.
* The log timestamp is real wall-clock UTC (ISO-8601 `...Z`), or date-only with
  `--date-only`. hot.md's `updated:` is always set to today's date (UTC).
* hot.md is created from a minimal template if missing. log.md is created empty.
* `--hot-entry` text is the bullet body WITHOUT the leading "- "; a leading
  "- " is stripped if present. Multi-line entries: embed "\n" and the script
  keeps them as one entry.
* Exit 0 on success; nonzero with a message on malformed input.
"""

import argparse
import datetime as _dt
import sys
from pathlib import Path

RECENT_HEADING = "## Recent Activity"

HOT_TEMPLATE = """---
title: Hot Cache
updated: {date}
---
## Recent Activity
## Active Threads
## Key Takeaways
## Flagged Contradictions
"""


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _today(date_override: str | None) -> str:
    if date_override:
        return date_override
    return _now_utc().strftime("%Y-%m-%d")


def _log_timestamp(ts_override: str | None, date_only: bool) -> str:
    if ts_override:
        return ts_override
    now = _now_utc()
    if date_only:
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def append_log(vault: Path, body: str, timestamp: str) -> str:
    log_path = vault / "log.md"
    line = f"- [{timestamp}] {body.strip()}"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    log_path.write_text(existing + line + "\n", encoding="utf-8")
    return line


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


def update_hot(vault: Path, entry: str | None, date: str, trim: int | None) -> dict:
    hot_path = vault / "hot.md"
    if not hot_path.exists():
        hot_path.write_text(HOT_TEMPLATE.format(date=date), encoding="utf-8")
    lines = hot_path.read_text(encoding="utf-8").split("\n")

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

    hot_path.write_text("\n".join(lines), encoding="utf-8")
    return {"added": added, "trimmed": trimmed, "bumped": bumped, "count": len(entries)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mechanical log.md / hot.md updater.")
    ap.add_argument("--vault", default=".", help="vault root (default: cwd)")
    ap.add_argument("--log", metavar="BODY", help='log line body after the timestamp, e.g. \'INGEST source="..." ...\'')
    ap.add_argument("--hot-entry", metavar="TEXT", help="Recent Activity bullet body (no leading '- ')")
    ap.add_argument("--hot-trim", type=int, metavar="N", help="keep only the newest N Recent Activity entries")
    ap.add_argument("--date", help="override today's date (YYYY-MM-DD) for hot.md updated:")
    ap.add_argument("--ts", help="override the log timestamp verbatim")
    ap.add_argument("--date-only", action="store_true", help="use a date-only log timestamp")
    args = ap.parse_args()

    if not args.log and not args.hot_entry and args.hot_trim is None:
        ap.error("nothing to do: pass --log and/or --hot-entry (and optionally --hot-trim)")

    vault = Path(args.vault).resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2

    out: list[str] = []
    if args.log:
        line = append_log(vault, args.log, _log_timestamp(args.ts, args.date_only))
        out.append(f"log.md += {line}")

    if args.hot_entry is not None or args.hot_trim is not None:
        res = update_hot(vault, args.hot_entry, _today(args.date), args.hot_trim)
        bits = []
        if res["added"]:
            bits.append("entry prepended")
        if res["trimmed"]:
            bits.append(f"trimmed {res['trimmed']} old")
        bits.append(f"{res['count']} entries")
        bits.append("updated: bumped" if res["bumped"] else "updated: already current")
        out.append("hot.md — " + ", ".join(bits))

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
