---
name: wiki-lint
description: >
  Audit and maintain the health of the Obsidian wiki. Use this skill when the user wants to check their
  wiki for issues, find orphaned pages, detect contradictions, identify stale content, fix broken wikilinks,
  or perform general maintenance on their knowledge base. Also triggers on "clean up the wiki",
  "what needs fixing", "audit my notes", or "wiki health check".
---

# Wiki Lint — Health Audit

You are performing a health check on an Obsidian wiki. The **mechanical** checks are done by a deterministic script — run it, don't redo them by hand. Your job is the two things a script can't do (contradictions, judging provenance and visibility) and proposing fixes.

This is the whole point of the framework: don't burn tokens reading every page to compute things a script computes exactly and for free.

## Before You Start

**Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md` (manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz). The scripts do their own vault resolution, so you can run them from anywhere inside the vault.

## Step 1: Run the deterministic linter

```bash
uv run .claude/wiki-scripts/wiki-lint.py --format md
```

One pass performs every mechanical check, reproducibly:

- **Orphaned pages** — zero incoming wikilinks
- **Broken wikilinks** — targets that don't resolve
- **Missing required frontmatter** — title, category, tags, sources, created, updated
- **Summary** — missing, or over 200 chars
- **Index consistency** — pages on disk vs `index.md`; `##` headings vs real folders; bare-basename links that should be full vault-relative paths
- **Hardcoded inventory counts** — brittle "N pages/skills/sources/…" tallies (per the shared "no hardcoded counts" convention)
- **Stale content** — a source modified after the page's `updated`, or a page older than 90 days
- **Lifecycle + supersession** — invalid `lifecycle` enum values; `superseded_by` targets that are missing, archived, or cyclic
- **Provenance marker ratios** — `^[inferred]` / `^[ambiguous]` density per page, with flags (speculation-heavy, unsourced-synthesis, hub-with-high-inferred)
- **Misc promotion candidates** — `misc/` pages whose links lean heavily into one project (computed on demand — no score is stored on pages)

Read its report. **Exit code 1** means at least one error-level finding (broken links, missing frontmatter, bad lifecycle/supersession). Use `--format json` if you want to post-process the findings. (No `uv` available? The script also runs as `python3 .claude/wiki-scripts/wiki-lint.py` once `pyyaml` is installed — `pip install pyyaml`.)

For graph-shaped questions the linter doesn't cover — **tag-cluster cohesion**, hubs, bridges — run `uv run .claude/wiki-scripts/wiki-graph.py` (see `wiki-status` insights mode). For **synthesis gaps**, run `/wiki-synthesize`.

## Step 2: The checks a script can't do

These need reading and judgement — do them after the script, focusing on pages the script flagged or that share tags / heavy cross-references.

### Contradictions

Claims that conflict across pages.

- Focus on pages that share tags or are heavily cross-referenced (the script's hub flags and `wiki-graph.py` point you at the dense areas).
- Watch for "however", "in contrast", "despite" — they distinguish acknowledged tensions from silent ones.
- **Fix:** add an "Open Questions" section noting the contradiction, referencing both sources and their claims.

### Interpret the provenance flags

The script counts the markers and flags pages; you decide what to do.

- **Speculation-heavy** (AMBIGUOUS > 15%): re-ingest from sources to resolve the uncertain claims, or split the speculative part into a `synthesis/` page.
- **Unsourced synthesis** (INFERRED-heavy, no `sources:`): add `sources:` or clearly label the page as synthesis.
- **Hub page with high inferred** (>20% on a top-incoming-link page): prioritize re-ingestion — errors on a hub propagate to everything that links to it.

### Visibility tags (PII safety)

The script does not judge sensitivity — you do.

- Grep page bodies for value-bearing `password`, `api_key`, `secret`, `token`, `ssn`, `email:`, `phone:` patterns. If a page has them but lacks `visibility/pii` or `visibility/internal`, flag it.
- A `visibility/pii` page with no `sources:` can't be verified — flag it (don't auto-fill; escalate to the user).
- `visibility/` tags are system tags — they must not appear in `_meta/taxonomy.md`.

## Step 3: Fix

Propose fixes for the script's findings and your semantic findings. Apply the safe ones; surface the rest for the user.

| Finding | Fix |
|---|---|
| Broken wikilink | Update the link, create the target, or remove it |
| **Many** links broke at once (folder/convention rename) | Don't fix one-by-one — use `../wiki-scripts/kebab-rename.py` (rename + wikilink rewrite + manifest re-key in lockstep; `DRY_RUN=1` to preview) |
| Orphaned page | Add incoming links from the right pages, or run `wiki-link` |
| Missing frontmatter / summary | Add the fields with reasonable defaults |
| Index drift | Sync `index.md` to match disk; fix headings to mirror folders |
| Hardcoded count | Rewrite to describe the collection, or compute at read time |
| Stale | Re-ingest the source; staleness clears when `updated` bumps |
| Invalid lifecycle / broken supersession | Flag for the human — never auto-set `lifecycle` |
| Misc promotion candidate | Move to `projects/<name>/references/`, update `category`, and grep for backlinks to update |
| Fragmented tag cluster (from `wiki-graph.py`) | Run `wiki-link` targeted at that tag |

## After Linting

Append to `log.md`:
```
- [TIMESTAMP] LINT errors=E warnings=W (orphans=O broken=B stale=S …)
```

Offer to fix issues automatically or let the user decide which to address.
