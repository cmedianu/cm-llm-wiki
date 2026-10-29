---
name: wiki-compact
description: >
  Shrink and consolidate the Obsidian wiki: merge duplicate pages, archive stale content, retire dead
  pages or whole sub-areas out of the wiki to _archives/, distil raw dumps, rotate the log. The fixer
  for wiki-lint findings, and handles full archive-and-rebuild or restore. Counterpart to wiki-ingest —
  removes and consolidates. Also consolidates upward with synthesis pages: "synthesize my wiki", "find
  connections", "what concepts keep coming up together".
---

# Wiki Compact — Prune, Merge, Archive

You are reducing the wiki's weight without losing knowledge. Growth skills (ingest, capture) only ever add; this skill is the counterweight: it merges what drifted apart, retires what stopped being true, and keeps the always-growing files bounded. Every byte a future agent doesn't have to read is the win.

**This skill deletes and rewrites. Confirm the plan with the user before executing it** (Step 2 to Step 3 gate). Steps 1 to 5 are the **scalpel**: targeted merges, archives, and log rolls. For the **nuclear** cases (archive the whole wiki, rebuild from scratch, restore a previous archive) use **Rebuild Mode** at the end; it is the heavy hammer, always gated on explicit user confirmation. To consolidate *upward* (a synthesis page joining concepts that keep co-occurring), follow `references/synthesis.md`.

## Before You Start

1. **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`.
2. Run the lint script — its findings are the work queue:
   ```bash
   uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-lint.py" --format json
   ```
3. Run `ingest-prep.py` once for the categories, `private_paths` and `index_status` per folder (`--source` needs no real file; ignore `source_status`). Don't re-derive them by hand:
   ```bash
   uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/ingest-prep.py" --vault "$OBSIDIAN_VAULT_PATH" \
     --source none
   ```
4. Read `hot.md` if it exists — don't compact something the user is actively working in.

## Step 1: Build the Compaction Queue

Collect candidates from four detectors. Mechanical ones come from the lint output — don't recompute them by hand.

| Source | Candidate |
|---|---|
| lint `oversized_page` | page to split, distil, or mark `lifecycle: living` |
| lint `stale_snapshot` | dated page with a newer sibling — wire `superseded_by` or archive |
| lint `stale_age` | page untouched > 90 days — confirm, refresh, or archive |
| lint `log_size` | log.md needs a roll (Step 4) |

Then the two judgments a script can't make:

- **Near-duplicates.** Group content pages by shared distinctive title words and overlapping tags (frontmatter grep — don't open bodies yet). Read only the groups' summaries; open bodies only for groups whose summaries plainly cover the same topic. Two pages are merge candidates when a reader would not know which to open.
- **Raw dumps posing as pages.** Pages that are verbatim pastes (transcripts, article copies, tool output) rather than distilled knowledge. The tell: no structure, no wikilinks, prose addressed to nobody.

## Step 2: Plan — and Get Approval

Produce a table: candidate → action → what happens to the content. Actions:

- **merge A into B** — fold A's unique facts into B, then archive A with `superseded_by: <B's path>`.
- **archive** — set `lifecycle: archived` (+ `lifecycle_changed`), leave the page in place. Archived pages stay resolvable (links keep working) but drop out of active-page queries. For **superseded-but-still-knowledge** content.
- **retire to `_archives/`** — move the page, or a whole dead sub-area, *out of the wiki* into `_archives/<topic>/`. Underscore dirs are invisible to every wiki script — no query hits, no index rows, no graph, lint, or manifest presence — but stay greppable and in git history. For **dead weight with no ongoing value** (a declined program, an abandoned plan, a finished one-off); if a future reader might still follow links into it, prefer **archive** in place instead. Before retiring a sub-area, judge each page: anything holding durable knowledge is **kept behind** — promoted up to the parent folder (rename it if the old basename only made sense inside the sub-area; update `category:` to the new folder; bump `lifecycle: draft` to `reviewed` if the content is settled) or merged into a survivor. Non-page assets (PDFs, images) retire along with their pages. Afterwards remove the emptied directory (`rmdir` — it must be empty; a leftover file means something wasn't judged).
- **distil** — replace a raw dump in place with a distilled page; move the verbatim original to `_sources/` (which needs no frontmatter).
- **split** — break an oversized page into atomic pages plus a short hub page at the original path so inbound links survive.
- **skip** — with one line of why (e.g. `living` dossier, event record, user says it's active).

Rules of the road:

- **Never delete knowledge.** Deletion is only for genuinely empty/junk files; everything else merges, archives, or moves to `_sources/`. When merging, every fact that exists only in the losing page must land in the surviving page.
- **Keep event records.** Dated pages that record events (a scan report, a meeting, a completed trip) are history, not staleness — archive only if the user agrees they're done being referenced.
- **Respect privacy scope** per the Privacy digest in `wiki/references/page-protocol.md` — a merge must never move private-area content to a more public path.
- **Don't touch `_`-dirs** (`_sources/`, `_archives/`, `_raw/`) except to move things *into* them.

**Show the plan and wait for the user's go-ahead.** They may pull items; execute only what survives.

## Step 3: Execute

For each approved action, in this order (merges first, so splits/archives see the merged state):

1. Apply the content change per the Page-Writing Protocol in `wiki/references/page-protocol.md` (full-path wikilinks, summary under 200 chars on any page you rewrite).
2. Rewire inbound links: for a **moved or renamed** page run `uv run .claude/wiki-scripts/wiki-mv.py OLD NEW` (preview), then again with `--apply`; it repoints every link and updates `category:`. For a page **merged** into an existing one, grep for its wikilinks and repoint them at the survivor (skip `log.md` — historical entries stay verbatim). Links to **retired** pages become plain-text archive pointers (`` `_archives/<topic>/page.md` ``), not wikilinks — a live page must never wikilink into a `_`-dir. Links *inside* retired pages are left as-is: the archive is a frozen snapshot outside wiki scope, and stale interlinks there are expected.
3. Curated `index.md` files: remove or repoint lines for archived/merged pages (indexes whose `index_status` is `base_backed` or `hybrid` need no edit).

## Step 4: Roll the Log

If lint flagged `log_size` (or the user asked), roll old entries into `_archives/log-<year>.md`, keeping a recent tail:

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-journal.py" --vault "$OBSIDIAN_VAULT_PATH" --log-trim 40
```

The script owns the mechanics (year-split archive files, frontmatter preserved). Don't hand-edit the log to "clean it up" — entries are the historical record.

## Step 5: Verify and Record

1. Lint — expect the queue findings you fixed to be gone and **zero new errors**:
   ```bash
   uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-lint.py" --summary
   ```
2. Record the operation:
   ```bash
   uv run .claude/wiki-scripts/wiki-journal.py --hot-trim 3 \
     --log 'COMPACT merged=N archived=M retired=R distilled=K: merged <what>, archived <what>'
   ```
3. Report to the user: what shrank, what moved where, and any candidate you recommend revisiting next time.

## Quality Checklist

- [ ] Every merge preserved the losing page's unique facts and set its `superseded_by`
- [ ] No inbound wikilink left pointing at a merged-away or retired path (grep to confirm)
- [ ] Retired sub-area's durable pages kept behind (promoted, `category:` matching the new folder); emptied directory removed
- [ ] Raw originals parked in `_sources/`, not deleted
- [ ] Lint shows no new errors
- [ ] Operation journaled via `wiki-journal.py`

---

## Rebuild Mode

*(Merged from the former `wiki-rebuild` skill.)* This is the destructive heavy hammer: snapshot the
whole wiki, optionally clear and rebuild it from sources, or restore a past snapshot. **Always archive
first, always confirm with the user before clearing the live wiki.** Steps 1 to 5 above are the scalpel;
reach for this only when the wiki has drifted too far for targeted merges. Confirm which of three
sub-modes the user wants: **archive only**, **archive + rebuild**, or **restore**.

### The archive system

Archives live at `$OBSIDIAN_VAULT_PATH/_archives/<YYYY-MM-DDTHH-MM-SSZ>/`. Each is a full copy of the
wiki state: every top-level **content** folder (all top-level dirs except `_*` and `.*`, discovered from
disk), plus `index.md`, `log.md`, `hot.md`, `.manifest.json`, and an `archive-meta.json`:

`{ "archived_at": "2026-04-06T10:30:00Z", "reason": "rebuild|snapshot|pre-restore", "total_pages": 87 }`

**Not a rebuild case:** a missing or corrupt `.manifest.json` (scripts say "No vault found") is fixed by
`regen-manifest.py --vault <root>`, which recreates the marker and keeps `private_paths`; links broken by
renames outside the tooling are a `wiki-lint` fix.

### Sub-mode 1: Archive only

Snapshot without rebuilding. Create `_archives/<timestamp>/`, copy every top-level content folder plus
`index.md`, `log.md`, `hot.md`, `.manifest.json` into it, write `archive-meta.json` with reason
`"snapshot"`, then journal:
`--log '<ARCHIVE reason="snapshot" pages=N destination="_archives/<timestamp>">'`. Report: "Archived N
pages. Current wiki is untouched."

### Sub-mode 2: Archive + rebuild

1. **Archive** current state exactly as sub-mode 1, but reason `"rebuild"`.
2. **Clear the live wiki:** remove every top-level content folder (discovered from disk). **Keep**
   `_archives/`, `.obsidian/` (Obsidian config), and `.claude/` (skills/scripts/conventions symlinks).
   Reset `index.md` to the empty template and `log.md`/`hot.md` to just the rebuild entry. **Keep**
   `.manifest.json` (the vault marker) and `_sources/`.
3. **Hand back to the user:** the vault is ready for a re-ingest with `wiki-ingest` in **Full Mode**
   (every `_sources/` snapshot still reads `unchanged`).
   **Don't auto-run the ingest;** the user chooses what to re-ingest and in what order, and some sources
   may no longer be relevant.
4. **Journal:** `--log 'REBUILD archived_to="_archives/<timestamp>" previous_pages=N' --hot-trim 3`.

### Sub-mode 3: Restore from archive

1. **List archives:** read each `_archives/*/archive-meta.json` and present a Date / Reason / Pages
   table.
2. **Confirm** which archive; warn that restoring overwrites the current live wiki.
3. **Archive the current state first** (reason `"pre-restore"`) so nothing is lost.
4. **Restore:** clear the live wiki (as sub-mode 2 step 2), copy the chosen archive's content back into
   the live directories, restore `index.md`/`log.md`/`hot.md`/`.manifest.json` from it, then journal:
   `--log '<RESTORE from="_archives/<timestamp>" pages_restored=N>'`.
5. **Report** what was restored and suggest running `wiki-lint` to check the restored state.

### Safety rules

1. **Always archive before destructive operations.** No exceptions.
2. **Always confirm with the user** before clearing the live wiki.
3. **Never delete archives** unless the user explicitly asks; they are cheap insurance.
4. **`.obsidian/` is sacred:** never touch it during archive/rebuild/restore.
5. If something goes wrong mid-rebuild, the archive is there, so tell the user they can restore.
