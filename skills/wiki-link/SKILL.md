---
name: wiki-link
description: >
  Scan the Obsidian wiki and automatically discover missing cross-references between pages.
  Use this skill when the user says "link my pages", "find missing links", "cross-reference",
  "connect my wiki", "add wikilinks", "what pages should be linked", or after any large ingestion
  to ensure new pages are woven into the existing knowledge graph. Also trigger when the user
  mentions "orphan pages" in the context of wanting to connect them, or says things like
  "my wiki feels disconnected" or "pages aren't linked well". This is a write-heavy skill —
  it actually modifies pages to add links, unlike wiki-lint which just reports issues.
  Also handles synthesis mode: discovering pairs or clusters of concepts that co-occur across many
  pages but have no page connecting them, and writing new synthesis pages that draw the cross-cutting
  conclusion. Triggers on "synthesize my wiki", "find connections", "what concepts keep coming up
  together", "/wiki-synthesize", or after a large ingest when the vault has grown significantly.
---

# Cross-Linker — Automated Wiki Cross-Referencing

You are weaving the wiki's knowledge graph tighter by finding and inserting missing `[[wikilinks]]` between pages that should reference each other but currently don't.

**Follow the Retrieval Primitives table in `wiki/SKILL.md`.** Build the registry in Step 1 by grepping frontmatter only (not full pages). Reserve full `Read` for the unlinked-mention detection pass, and even there, only read pages whose summaries/titles make them plausible link targets. Blind full-vault reads are what this framework exists to avoid.

## Two Modes

- **Cross-link (default):** find and insert missing `[[wikilinks]]` between pages that already exist. This is Steps 1 to 6 below.
- **Synthesis:** go one level up. Find concepts that co-occur across many pages but have no page *connecting* them, and write new synthesis pages that state the cross-cutting conclusion. Triggers: "synthesize my wiki", "find connections", "/wiki-synthesize". See **Synthesis Mode** at the end. Cross-linking rewires what exists; synthesis creates the missing connective page. Run synthesis after a large ingest, then cross-link to weave the new pages in.

## Before You Start

1. **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`: manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz the registered vaults (persisting the choice). All paths derive from the vault root.
2. Don't treat `index.md` as the page inventory — it may be a base-backed query that reads as source, not rows. The authoritative registry is the glob + frontmatter grep you build in Step 1; `index.md` is at most a curated hint about which pages the vault considers central.
3. Skim the tail of `log.md` (last ~20 lines), or `hot.md`, to see what was recently ingested (focus linking effort on new pages) — don't read the whole append-only log

When inserting links in Step 4, write them as vault-relative wikilinks (see Link Format in `wiki/SKILL.md`).

## Step 1: Build the Page Registry

Glob all `.md` files in the vault (excluding `_archives/`, `.obsidian/`). For each page, extract:

- **Filename** (without `.md`) — this is the wikilink target
- **Title** from frontmatter
- **Aliases** from frontmatter (if any)
- **Tags** from frontmatter
- **Category** from frontmatter or directory inference
- **One-line summary** — first sentence or `title` field

Build a lookup table:

```
page_name → { path, title, aliases, tags, summary }
```

This is your "vocabulary" — every entry in this table is a valid wikilink target.

## Step 2: Scan for Missing Links

Never read every page whole — that blind full-vault sweep is exactly what the Retrieval Primitives table exists to avoid. Instead, prefilter to candidates, then fan out per directory.

**Prefilter (cheap).** For each target in the registry, grep the vault for its distinctive names — filename, title, aliases — plus a tag/summary overlap pass, to find the handful of pages that *plausibly* mention or relate to it. Only those candidates earn a full `Read`; the rest of the vault is never opened.

**Per-directory fan-out.** Spawn one subagent per top-level category (discover the folders from disk), handing it its slice of the registry and the candidate lists that fell in its directory. Each subagent, for the candidate pages it was handed:

1. **Reads full content** — only for those plausible candidates, not the whole slice
2. **Extracts existing wikilinks** — all `[[...]]` references already present
3. **Searches for unlinked mentions** — text that contains any of these without being wrapped in `[[...]]`:
   - Page filenames (e.g., the word "MyProject" appears but `[[projects/my-project/my-project]]` is missing)
   - Page titles from frontmatter
   - Aliases from frontmatter
   - Entity names, project names, concept names from the registry
4. **Checks for semantic connections** — pages that share multiple tags or sit in the same project directory but don't link to each other

Collect each subagent's proposed links back at the top level for Step 3's judgement.

### Matching Rules

- **Case-insensitive matching** for names (e.g., "my-project" matches page `MyProject`)
- **Diacritic-insensitive matching** — normalize both the page name and the body text with Unicode NFKD (decompose accented characters to base + combining marks, strip combining marks) before comparing. This ensures body text "Muller" matches page `[[entities/müller]]` and vice versa.
- **Skip self-references** — a page shouldn't link to itself
- **Skip common words** — don't link "the", "and", generic terms. Only match on distinctive names
- **Always use full vault-relative paths** — `[[full/path/to/page-name]]`, never a bare `[[page-name]]`, per Link Format in `wiki/SKILL.md` (basenames aren't globally unique)
- **Don't link inside code blocks** or frontmatter
- **Don't double-link** — if `[[foo]]` already appears on the page, don't add another

## Step 3: Judge Which Links Are Worth Adding

Not every possible link is worth adding. Judge each candidate qualitatively and sort it into one of three buckets — reusing the wiki's provenance vocabulary. No arithmetic; a short judgement is enough:

- **strong (EXTRACTED)** — the page names the target outright (exact filename / title / alias mention) or it's an obvious topical fit. Apply inline.
- **plausible (INFERRED)** — no direct mention, but the pages clearly belong together: they share a clear topic, sit in the same project, span two knowledge layers (e.g. `concepts/` ↔ `entities/`), or a loose page would benefit from reaching a hub. Apply inline or in a `## Related` section, and carry the label so the user can review.
- **skip (AMBIGUOUS)** — only a generic-word overlap or a partial name match. Don't add it unless the user explicitly asks to connect loose pages.

Act on **strong** and **plausible** candidates; skip the rest. Favour precision over recall — a wrong link is worse than a missing one. Include the label in the Cross-Link Report so INFERRED links are reviewable.

## Step 4: Apply Links

For each page with missing links:

### 4a: Inline linking (preferred)

Find the first natural mention of the term in the body text and wrap it in wikilinks:

**Before:**
```markdown
This project uses knowledge graphs to connect entities.
```

**After:**
```markdown
This project uses [[concepts/knowledge-graphs|knowledge graphs]] to connect entities.
```

Use the `[[path|display text]]` format when the wikilink path differs from the display text.

### 4b: Related section (fallback)

If the term isn't mentioned naturally in the body but the pages are semantically related (shared tags, same project), add a `## Related` section at the bottom of the page:

```markdown
## Related

- [[projects/my-project/my-project]] — Also uses AI agents for research automation
- [[concepts/knowledge-graphs]] — Core technique used in this project
```

If a `## Related` section already exists, append to it. Don't duplicate existing entries.

### Privacy guard

Don't leak a private-area page onto a more-public surface. Before adding a cross-link, check the target against `private_paths` (see `## Privacy & Visibility` in `wiki/SKILL.md`): never surface a private page's title or summary on a page — or index — outside its own privacy scope, e.g. don't add a `me/` page into a public page's `## Related` section. Linking *within* a private area, or from public → less-private only via the area's own section index, is fine.

## Step 5: Report

Present a summary:

```markdown
## Cross-Link Report

### Links Added: 23 across 12 pages

| Page | Links Added | Confidence | Type |
|---|---|---|---|
| `projects/my-project/my-project.md` | 3 | EXTRACTED | 2 inline, 1 related |
| `entities/jane-doe.md` | 5 | INFERRED | 3 inline, 2 related |
| ... | | | |

### Orphan Pages Remaining: 2
- `references/foo.md` — no incoming or outgoing links found
- `concepts/bar.md` — could not find related pages

(Misc-page promotion candidates are reported separately by `wiki-lint.py`, which counts each misc page's links into projects on demand — no affinity score is stored on pages.)

### Pages Skipped: 3
- `index.md`, `log.md` — special files
- `_archives/*` — archived content
```

Don't re-derive "Orphan Pages Remaining" by hand. Run `wiki-lint.py` (or `wiki-graph.py`) and consume its orphan list — those scripts compute orphans deterministically per the `## Orphans` definition in `wiki/SKILL.md` and are the source of truth.

## Step 6: Update Log and Hot Cache

Drive `log.md` and `hot.md` with `wiki-journal.py` — don't hand-edit. You compose the distilled Recent-Activity line (e.g. "Cross-linked 23 mentions across 12 pages; 2 orphans remain"); the script owns the timestamped log append, `hot.md` prepend/trim to the newest 3, and `updated:` bump:

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-journal.py" --vault "$OBSIDIAN_VAULT_PATH" \
  --log 'CROSS_LINK pages_scanned=N links_added=M pages_modified=P orphans_remaining=Q' \
  --hot-entry '**One-line summary of what was cross-linked.**' \
  --hot-trim 3
```

## Tips

- **Run after every ingest.** New pages are almost always poorly connected. This is the fix.
- **Be conservative with inline links.** Only link the first natural mention, not every occurrence.
- **Don't touch pages in `_archives/`.** Those are frozen snapshots.
- **Respect existing structure.** If a page carefully curates its links in a `## Key Concepts` section, add to that section rather than creating a separate `## Related`.
- **Entity pages are link magnets.** An entity like `jane-doe` should be linked from almost every project page. Prioritize these.

---

## Synthesis Mode

*(Merged from the former `wiki-synthesize` skill.)* Here you are not adding links between existing
pages; you are discovering concepts that co-occur across the wiki but have **no dedicated synthesis
page** connecting them, and writing the few most valuable ones. The vault resolution and Page-Writing
Protocol are shared; the steps below replace Steps 1 to 6. Before starting, read `hot.md` (active
threads may already point at synthesis gaps) and `_meta/taxonomy.md` (tag vocabulary), and check
`_insights.md`, where `wiki-status` may have already flagged synthesis candidates.

### SY1: Build the co-occurrence map

Scan every non-special page (skip `index.md`, `log.md`, `hot.md`, `_insights.md`, `_meta/*`,
`_archives/*`, `_raw/*`), collecting each page's outgoing `[[wikilinks]]`, `tags`, and `category`. Build
a co-occurrence matrix: for every pair of concept/entity pages (A, B), count how many *other* pages link
to **both**. Aim for the top 20 to 30 pairs by co-occurrence, not exhaustive. Grep backlinks efficiently
and intersect the result sets:

```bash
grep -rl "\[\[concepts/concept-a\]\]" "$OBSIDIAN_VAULT_PATH" --include="*.md"
```

### SY2: Filter out already-synthesized pairs

Read the vault's synthesis category. For each existing synthesis page, read its `sources` frontmatter or
body `[[wikilinks]]` and mark those pairs covered; remove covered pairs from the candidate list.

### SY3: Score and rank

Judge how much a dedicated synthesis page would add (qualitative, no arithmetic). Prioritize pairs that
co-occur across many pages, **cross domains** (different categories/tag clusters, so less obvious and
more valuable), would **resolve a flagged contradiction**, or **join hubs** (per `wiki-graph.py` /
`_insights.md`). Write the ~5 strongest. If the user named a topic ("synthesize everything about
observability"), filter to that domain first.

### SY4: Draft synthesis pages

Create each page in the vault's **synthesis category** per the Page-Writing Protocol. Synthesis-specific:

- **Title is `<Concept A> × <Concept B>`**, where the `×` signals a synthesis page. Set `sources:` to
  every page that links to both concepts.
- **Body**, in order: `## The Connection` (the non-obvious relationship the individual pages don't
  capture), `## Where They Co-occur`, `## Cross-cutting Insight` (the point of the page, visible only
  looking at both together), `## Tensions and Trade-offs`, `## Open Questions`, `## Related` (full-path
  wikilinks to both concepts and other related pages).
- **Mostly `^[inferred]`**, since you are drawing connections across sources by definition;
  `^[ambiguous]` where sources disagree.
- **Privacy:** if any source page lives under a `private_paths` prefix, the synthesis is itself
  private-scoped, so file it inside that private area or exclude those sources. Never surface a private
  page's title/summary in a public synthesis page or index.

### SY5: Back-link from source pages

For each synthesis page, add a link to it from the concept pages it synthesizes, in their `## Related`
section (create one at the bottom if absent): `- [[synthesis/concept-a-x-concept-b]] (synthesis)`.

### SY6: Report opportunities not taken

After writing the top ~5, list the next ~10 well-scoring candidates you skipped, so the user sees what
the wiki thinks is worth exploring without forcing every synthesis in one run:

```
Skipped (consider next time):
- [[concepts/caching]] × [[concepts/consistency]] : co-occurs in 4 pages, cross-domain
```

### SY7: Update special files

Update a hand-curated `index.md` only (base-backed needs none) and drive `log.md` / `hot.md` with
`wiki-journal.py`. Use a `WIKI_SYNTHESIZE` op-code, e.g.
`--log 'WIKI_SYNTHESIZE pages_scanned=N synthesis_created=M candidates_skipped=K'`. Edit the semantic
**Active Threads** by hand to record open questions the synthesis surfaced.

**Synthesis quality:** a page that only summarizes its sources is useless; the value is the connection
neither source states. Don't synthesize for its own sake; skip concepts that merely co-occur without a
real conceptual link. Three-way syntheses are powerful but rare, warranted only when three concepts form
a genuine triangle of mutual influence.
