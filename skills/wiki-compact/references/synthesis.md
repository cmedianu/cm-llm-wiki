# Synthesis Mode

Consolidate upward: find concepts that keep co-occurring across pages but have no page connecting them,
and write the few most valuable synthesis pages. Triggers: "synthesize my wiki", "find connections",
"what concepts keep coming up together". Not a confirmation-gated step like the rest of compact (it only
adds), but still show the shortlist before writing.

1. **Candidates.** Run `uv run .claude/wiki-scripts/wiki-graph.py --format json` for hubs, bridges and
   fragmented tags, then for the top concept/entity pages intersect their backlink sets
   (`grep -rl "\[\[cat/concept-a\]\]" --include="*.md"`) to find pairs that many *other* pages link to
   both. Aim for the top 20-30 pairs, not exhaustive. If the user named a topic, filter to it first.
2. **Drop covered pairs:** pairs an existing page in the synthesis folder already links together.
3. **Pick ~5**, judged qualitatively: many co-occurrences, cross-domain (different categories), resolves
   a flagged contradiction, or joins hubs. Skip pairs that merely co-occur without a real link.
4. **Write** each with `wiki-new.py` in the vault's synthesis folder, per the Page-Writing Protocol
   (`wiki/references/page-protocol.md`). Title `<Concept A> × <Concept B>`; `sources:` = the pages
   linking both. Body: `## The Connection`, `## Cross-cutting Insight` (the point neither page states),
   `## Tensions and Trade-offs`, `## Open Questions`, `## Related`. Mostly `^[inferred]`. If any source
   is under `private_paths`, the synthesis is private-scoped: file it inside that area or drop the source.
5. **Back-link** from both concept pages (`## Related`: `- [[synthesis/a-x-b]] (synthesis)`).
6. **Report** the next ~10 candidates you skipped, then journal:
   `wiki-journal.py --hot-trim 3 --log 'SYNTHESIZE created=M skipped=K: [[synthesis/a-x-b]], ...'`.

A page that only summarizes its sources is useless; the value is the connection neither source states.
