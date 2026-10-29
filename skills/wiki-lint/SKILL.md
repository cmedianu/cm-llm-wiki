---
name: wiki-lint
description: >
  Audit and maintain the health of the Obsidian wiki, and report its state. Use this skill when the user
  wants to check their wiki for issues, find orphaned pages, detect contradictions, identify stale content,
  fix broken wikilinks, or perform general maintenance: "clean up the wiki", "what needs fixing", "audit
  my notes", "wiki health check". Status mode: "wiki status", "what's pending", "what changed", "what's
  left to ingest", "dashboard". Insights mode: "wiki insights", "show me the hubs", "what's central",
  "bridges", "wiki structure".
---

# Wiki Lint — Health, Status, Insights

The **mechanical** checks are done by a deterministic script — run it, don't redo them by hand. Your job is what a script can't do (contradictions, judging provenance and visibility) and proposing fixes. Don't burn tokens reading every page to compute things a script computes exactly and for free.

Three modes:

- **Audit (default):** Steps 1-3 below.
- **Status:** "what's pending / what changed / dashboard". See **Status Mode**; read-only.
- **Insights:** hubs, bridges, tag cohesion. Read `references/insights.md`.

## Before You Start

**Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md` (manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz). The scripts resolve the vault themselves, so run them from anywhere inside it.

## Step 1: Run the deterministic linter

```bash
uv run .claude/wiki-scripts/wiki-lint.py --summary
```

One pass covers orphans, broken wikilinks, missing frontmatter, summaries over 200 chars, index drift and bare-basename links, stale `reviewed` pages and superseded dated snapshots, lifecycle/supersession integrity, non-date-only date fields, provenance marker ratios, misc-promotion candidates, and index privacy leaks. **Exit code 1** means at least one error-level finding. `--format json` for post-processing. (Requires `uv`; never fall back to a bare `python3`.)

Useful flags: `--only key[,key]` (one check's full findings; drop `--summary`), `--staged` (the pre-commit gate runs `--staged --errors-only`), `--errors-only`. `--fix` completes a broken or bare-basename wikilink when exactly one file matches; `--fix-snapshots` wires `superseded_by` + `lifecycle: archived` onto a dated snapshot with a newer sibling (never on meeting/minutes/standup series). A page can opt out of a **warning** with `lint_ignore: [key]`; errors are never suppressible.

## Step 2: The checks a script can't do

Focus on pages the script flagged or that share tags / heavy cross-references.

- **Contradictions.** Claims that conflict across pages; watch "however", "in contrast", "despite". Fix: an "Open Questions" section citing both sources.
- **Provenance flags.** Speculation-heavy (AMBIGUOUS > 15%): re-ingest or split the speculative part into a synthesis page. Unsourced synthesis: add `sources:` or label it synthesis. Hub with high inferred: prioritize, errors on a hub propagate.
- **Visibility (PII safety).** Grep bodies for value-bearing `password`, `api_key`, `secret`, `token`, `ssn`, `email:`, `phone:`; flag pages lacking `visibility/pii` or `visibility/internal`. A `visibility/pii` page with no `sources:` can't be verified: escalate, don't auto-fill.

## Step 3: Fix

Apply the safe fixes; surface the rest.

| Finding | Fix |
|---|---|
| Broken wikilink | Update, create the target, or remove (`--fix` when the basename is unique) |
| **Many** links broke at once (folder rename) | `wiki-mv.py OLD NEW` per page, or `kebab-rename.py` for a convention sweep (`DRY_RUN=1` first) |
| Orphaned page | Back-link pass: `ingest-prep.py --backlinks-for <page>`, then add the links that help (see `wiki-ingest` Step 6) |
| Missing frontmatter / summary | Add the fields |
| Index drift | Sync `index.md` to disk; headings mirror folders |
| Stale / stale snapshot | Re-ingest, or `--fix-snapshots`, or `lint_ignore: [stale_snapshot]` if both stay live |
| Invalid lifecycle / broken supersession | Flag for the human — never auto-set `lifecycle` |
| Misc promotion candidate | Move with `wiki-mv.py` to `projects/<name>/references/` |
| oversized_page, duplicates, log_size | Hand off to `wiki-compact` |

Record the run (don't hand-edit `log.md`):

```bash
uv run .claude/wiki-scripts/wiki-journal.py --no-hot --log 'LINT errors=E warnings=W: one-line gist'
```

## Status Mode

A short dashboard: what changed, what is waiting to be ingested, and health. Read-only. **Never read `.manifest.json`** (it is only the vault marker plus `private_paths`). Take `<date>` from the newest `log.md` entry (`tail -n 3 log.md`), or from the user ("this week").

```bash
git -C <vault> status --short -- '*.md'                                   # uncommitted page edits
git -C <vault> log --since=<date> --name-status --format= -- '*.md'      # pages added/modified/deleted since
uv run .claude/wiki-scripts/ingest-prep.py --sources-dir _sources --since <date>   # external sources not yet ingested
uv run .claude/wiki-scripts/claude-history.py sessions --since <date>             # new Claude conversations
uv run .claude/wiki-scripts/wiki-lint.py --summary                                # health
```

Skip a line whose input does not exist (no git repo, no `_sources/`). Report in a few lines: pages changed (A/M/D counts, the notable ones by name), sources and conversations waiting, lint errors/warnings. Then recommend one next step: ingest the waiting sources (`wiki-ingest`), fix lint errors (Audit mode), or nothing. A drift so large the wiki no longer reflects its sources is a `wiki-compact` Rebuild Mode question.
