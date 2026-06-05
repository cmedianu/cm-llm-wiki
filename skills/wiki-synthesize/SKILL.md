---
name: wiki-synthesize
description: >
  Systematically discover synthesis opportunities across the Obsidian wiki — pairs or clusters of
  concepts that co-occur frequently across pages but have no synthesis page connecting them. Creates
  new synthesis/ pages that draw explicit cross-cutting conclusions. Use when the user says "synthesize
  my wiki", "find connections", "what concepts keep coming up together", "/wiki-synthesize", or after
  a large ingest when the vault has grown significantly.
---

# Wiki Synthesize — First-Class Synthesis Discovery

You are scanning the wiki for concepts that co-occur across many pages but have no dedicated synthesis page connecting them. Your job is to surface these gaps and fill the most valuable ones with cross-cutting synthesis pages.

## Before You Start

1. **Resolve vault** — walk up from CWD for `.manifest.json` (per the Config Resolution Protocol in `wiki/SKILL.md`). All paths derive from the vault root.
2. Read `index.md` to get the full page inventory.
3. Read `hot.md` if it exists — it surfaces recent activity and active threads that may already point to synthesis opportunities.
4. Read `_meta/taxonomy.md` to understand the tag vocabulary.

When writing internal links in synthesis pages, apply the link format from `wiki/SKILL.md` (Link Format section) using vault-relative wikilinks.

## Step 1: Build the Co-occurrence Map

Scan every non-special page in the vault (skip `index.md`, `log.md`, `hot.md`, `_insights.md`, `_meta/*`, `_archives/*`, `_raw/*`).

For each page, collect:
- All `[[wikilinks]]` it contains (outgoing links)
- Its `tags` frontmatter
- Its `category` frontmatter

Build a co-occurrence matrix: for every pair of concept/entity pages (A, B), count how many other pages link to **both** A and B. This is their co-occurrence score.

You don't need to be exhaustive — aim for the top 20-30 pairs by co-occurrence score. Use Grep to find backlinks efficiently:

```bash
grep -rl "\[\[ConceptA\]\]" "$OBSIDIAN_VAULT_PATH" --include="*.md"
```

Run this for your top candidate concepts and intersect the result sets.

## Step 2: Filter Out Already-Synthesized Pairs

Check the `synthesis/` directory for existing pages. For each existing synthesis page:
- Read its `sources` frontmatter or its body for `[[wikilinks]]`
- Mark those concept pairs as already covered

Remove covered pairs from your candidate list.

## Step 3: Score and Rank Candidates

For each remaining candidate pair (or cluster of 3+), judge how much a dedicated synthesis page would add. Prioritize pairs that:

- **co-occur across many pages** — the more pages link to both, the more load-bearing the connection
- **cross domains** — two concepts from different categories (or different tag clusters) yield a less obvious, more valuable synthesis than two neighbours
- **would resolve a flagged contradiction** — reconciling a tension the wiki already noted beats restating agreement
- **join hubs** — if `wiki-graph.py` (or `_insights.md`) marks one or both as a hub, the synthesis reaches more of the wiki

Write the few strongest — aim for ~5. If the user asked for a specific topic ("synthesize everything about observability"), filter candidates to that domain first.

## Step 4: Draft Synthesis Pages

For each top candidate, create a page in `synthesis/` using this template:

```markdown
---
title: <Concept A> × <Concept B>
category: synthesis
tags: [<shared tags>, <domain tags>]
sources: [<all pages that link to both>]
created: TIMESTAMP
updated: TIMESTAMP
summary: "Cross-cutting synthesis of how <A> and <B> interact, with implications for <domain>."
lifecycle: draft
lifecycle_changed: TIMESTAMP_DATE
---

# <Concept A> × <Concept B>

## The Connection

*What makes these two concepts worth synthesizing together — the non-obvious relationship that pages about each individually don't capture.*

## Where They Co-occur

*The pages and contexts where both appear. What situations bring them together.*

## Cross-cutting Insight

*The conclusion that only becomes visible when you look at both together. This is the point of the page — the thing you couldn't see from either concept page alone.*

## Tensions and Trade-offs

*Where the two concepts pull in opposite directions. Unresolved contradictions. Cases where applying one undermines the other.*

## Open Questions

*What this synthesis surfaces that the wiki doesn't yet have an answer for. Good candidates for future research.*

## Related

- [[<Concept A>]]
- [[<Concept B>]]
- [[<other related pages>]]
```

**Synthesis pages are mostly `^[inferred]`.** You are drawing connections across sources — that's synthesis by definition. Apply `^[inferred]` to cross-cutting conclusions and `^[ambiguous]` where sources disagree.

**The title format is `A × B`** — this signals to readers that it's a synthesis page, not a page about either concept alone.

## Step 5: Back-link from Source Pages

For each synthesis page you created, add a link to it from the two (or more) concept pages it synthesizes. In the concept page, add to its `## Related` section:

```markdown
- [[Concept A × Concept B]] — synthesis
```

If the concept page has no `## Related` section, add one at the bottom.

## Step 6: Report Synthesis Opportunities Not Taken

After creating pages for the top 5, list the next 10 candidates in your output — pairs that scored well but you didn't write pages for. This gives the user visibility into what the wiki thinks is worth exploring without forcing every synthesis in one run.

Format:
```
Skipped (consider next time):
- [[Caching]] × [[Consistency]] — co-occurs in 4 pages, cross-domain
- [[Testing]] × [[Observability]] — co-occurs in 3 pages, shares tags
...
```

## Step 7: Update Special Files

**`index.md`** — Add entries for all new synthesis pages.

**`log.md`** — Append:
```
- [TIMESTAMP] WIKI_SYNTHESIZE pages_scanned=N synthesis_created=M candidates_skipped=K
```

**`hot.md`** — Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Update **Recent Activity** with what was synthesized — e.g. "Synthesized 5 cross-cutting pages: Caching × Consistency, Testing × Observability, …". Update **Active Threads** with any open questions the synthesis surfaced. Update `updated` timestamp.

## Quality Checklist

- [ ] Every synthesis page has a `summary:` field (≤200 chars)
- [ ] Every synthesis page links back to its source concepts
- [ ] Source concept pages link forward to the synthesis page
- [ ] No synthesis page just restates what's already on the source pages — it must add a cross-cutting insight
- [ ] `index.md` and `log.md` updated
- [ ] `hot.md` updated

## Tips

- **A synthesis page that only summarizes its sources is useless.** The value is the connection — the thing neither source page says explicitly.
- **Don't synthesize for synthesis's sake.** If two concepts just happen to appear together a lot without a real conceptual link, skip them.
- **Three-way syntheses are powerful but rare.** Only create them when three concepts form a genuine triangle of mutual influence — not just because all three appear in the same project page.
- **Check `_insights.md` first.** The wiki-status skill may have already flagged synthesis candidates there — start with those before running the co-occurrence scan from scratch.
