---
name: wiki-archive
description: >
  Retire wiki pages or a whole dead sub-area out of the Obsidian wiki into _archives/. Use for
  "/wiki-archive", "archive this page", "archive this folder", "retire this", "move it to the archives".
  A shortcut into wiki-compact's retire action.
---

# Wiki Archive

This is `wiki-compact`'s **retire to `_archives/`** action; that skill (Step 2 actions, Step 3 execute)
has the full rules. Minimum steps:

1. Per page in scope: **retire** (dead weight), **keep behind** (durable knowledge: promote to the
   parent folder or merge), or **archive in place** (`lifecycle: archived`) if still linked. Show the
   plan; wait for the go-ahead.
2. Move retired pages and their assets to `_archives/<topic>/`; `rmdir` the emptied folder.
3. Repoint inbound links: live pages get a plain-text pointer (`` `_archives/<topic>/page.md` ``), never
   a wikilink into a `_`-dir. Fix any curated `index.md`.
4. `uv run .claude/wiki-scripts/wiki-lint.py --summary` shows no new errors, then journal:
   `wiki-journal.py --hot-trim 3 --log 'COMPACT retired=R: <what> to _archives/<topic>'`.
