# Insights Mode

The shape of the wiki rather than its problems: what is central, what holds it together, where clusters
are loose. Skip it for vaults under ~20 pages, or right after a rebuild.

## Run the graph tool

```bash
uv run .claude/wiki-scripts/wiki-graph.py --format json
```

It computes deterministically (no LLM arithmetic):

- **Hubs** — top pages by incoming links; connector hubs (high in and out) vs sink hubs (high in, zero out).
- **Bridges** — articulation points: removing one partitions the graph.
- **Tag cohesion** — for each tag on 5+ pages, how tightly its pages interlink; `fragmented` (< 0.15) clusters need links.
- **Orphans / orphan-adjacent** — isolated pages, and dead-ends linked from a hub.
- **Cross-category edges** — the non-obvious cross-domain links.
- **Graph delta** — pages and links added or removed since the last run (snapshot kept at `~/.obsidian-wiki/state/<vault-id>/graph-snapshot.json`, never in the vault).

## Report

Render `_insights.md` at the vault root (regenerable, overwrite freely): anchor pages, bridges, most and
least cohesive tags, cross-category connections, orphan-adjacent pages, graph delta. Add a one-line
plain-language reason to each highlighted item. End with **Questions Worth Asking**: grep the flagged
pages for `^[ambiguous]` claims first, then bridges, then isolates.

Follow-ups: a fragmented tag or sink hub → back-link pass (`ingest-prep.py --backlinks-for`); recurring
concept pairs with no connecting page → `wiki-compact/references/synthesis.md`.

Journal it:

```bash
uv run .claude/wiki-scripts/wiki-journal.py --no-hot --log 'INSIGHTS hubs=H bridges=B fragmented=F: one-line gist'
```
