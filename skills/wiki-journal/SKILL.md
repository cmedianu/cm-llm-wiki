---
name: wiki-journal
description: >
  Record a one-line entry in the Obsidian wiki's journal (log.md, and hot.md's Recent Activity). Use for
  "/wiki-journal", "journal this", "log this", "add a log entry", "note in the log that ...".
---

# Wiki Journal

Never hand-edit `log.md` or `hot.md`'s Recent Activity; the script owns the timestamp, placement,
trimming and `updated:` bump. Run from inside the vault:

```bash
uv run .claude/wiki-scripts/wiki-journal.py --hot-trim 3 --log 'OP k=v: gist [[full/path/page]]'
```

- One line, at most 240 chars: an upper-case op-code (`CAPTURE`, `INGEST`, `DECISION`, `NOTE`, ...),
  optional `key=value` counts, then the conceptual gist with full vault-relative wikilinks. Detail goes
  on the page, not in the log.
- Add `--no-hot` for read-only runs (a lint, a query) so `hot.md` stays about changes.
- Committing? Pass the line to `wiki-commit.py --journal 'LINE'` instead; it writes the entry into the
  last commit.
