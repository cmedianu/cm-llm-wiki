---
name: wiki-research
description: >
  Autonomously research a topic via multi-round web search, synthesize findings, and file structured
  results into the Obsidian wiki. Use this skill when the user says "/wiki-research [topic]",
  "research X", "find everything about Y", "do a deep dive on Z", "autonomous research on X",
  or wants comprehensive, web-sourced knowledge on a topic filed directly into their wiki.
---

# Wiki Research — Autonomous Multi-Round Research

You are running an autonomous research loop on a topic, synthesizing what you find, and filing the results into the Obsidian wiki as permanent knowledge.

## Before You Start

1. **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`: manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz the registered vaults (persisting the choice). All paths derive from the vault root.
2. Survey what the wiki already covers so you don't re-research it — derive the page inventory from `.manifest.json` (or a `glob` + frontmatter scan), never by parsing `index.md` (it may be a base-backed query, not a page list)
3. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists — it surfaces recent context
4. Check `$OBSIDIAN_VAULT_PATH/references/research-config.md` if it exists — it may define source preferences or domains to skip for this vault

When writing internal links in generated pages, apply the link format from `wiki/SKILL.md` (Link Format section) using vault-relative wikilinks.

Confirm the research topic with the user if it's ambiguous. Then proceed.

## Research Configuration (optional)

If `references/research-config.md` exists in the vault, read it and apply any rules it defines:
- Source preferences (e.g., prefer academic sources, avoid certain domains)
- Domains to skip
- Topic-specific constraints

If the file doesn't exist, proceed with defaults.

## Round 1 — Broad Survey

**Goal:** Get a wide map of the topic.

1. Decompose the topic into **3-5 distinct angles** (e.g., for "vector databases": what they are, when to use them, leading implementations, trade-offs, production gotchas)
2. For each angle, run **2-3 `WebSearch` queries** using varied phrasing
3. For the top 2-3 results per angle, use `WebFetch` (or `defuddle <url>` if available — cleaner extraction) to get content
4. From each fetched page, extract:
   - **Key claims** — what the source explicitly states
   - **Concepts** — ideas, terms, frameworks introduced
   - **Entities** — tools, people, organizations mentioned
   - **Contradictions** — places where sources disagree with each other

Track what's covered and what's missing as you go.

## Round 2 — Gap Fill

**Goal:** Close the holes left by Round 1.

Review what Round 1 produced:
- What questions did sources raise but not answer?
- Where do sources contradict each other?
- Which angles got thin coverage?

Run **up to 5 targeted searches** specifically addressing these gaps. Prefer primary sources, official documentation, and authoritative analyses over link aggregators.

Add findings to your working set. Update the contradiction list.

## Round 3 — Synthesis Check

**Goal:** Resolve contradictions; confirm depth is sufficient.

If major contradictions remain unresolved:
- Run one final targeted pass (2-3 searches) to find authoritative resolution
- If resolution is impossible, flag the contradiction explicitly in the synthesis page

If contradictions are minor or the topic feels well-covered after Round 2, skip additional searching and proceed to filing.

**Halt condition:** Stop when depth is achieved or 3 rounds are complete — do not loop indefinitely.

## Filing — Write Wiki Pages

Every page follows the **Page-Writing Protocol** in `wiki/SKILL.md` (frontmatter, `summary` < 200 chars, `lifecycle: draft`, provenance markers, ≥2 wikilinks). Only the research-specific extras are called out below.

**Route to existing categories, discovered from disk.** List the vault's top-level folders (skip `_*` and `.*`) and file each page in the best-fitting **existing** folder — never scaffold a fixed `concepts/ entities/ references/` taxonomy the vault doesn't already have. Set each page's `category:` to the folder it lands in.

### Source-summary pages — one per major reference

For each significant source (typically 4-8), route to the vault's reference-like category if it has one, else the best-fitting folder. Add the research-specific field `source_url: "<URL>"` alongside the URL in `sources:`. Body: title, URL, what it covers, key claims (with provenance markers), limitations.

### Concept pages — one per substantive concept

For each significant concept surfaced across sources, route to the best-fitting existing folder. Link concepts to each other and to the source-summary pages.

### Entity pages — tools, organizations, people

For each significant entity encountered (tools, libraries, companies, key authors), route to the best-fitting existing folder. Link back to the concepts that use the entity and the sources where it appears.

### Master synthesis page

The primary output: a structured synthesis of everything found, filed as `research-<topic-slug>.md` (kebab-case) in the vault's synthesis-like category if one exists, else the best-fitting folder. Set `title:` without a leading colon-space (e.g. `<Topic> research synthesis`) and `category:` to the folder it lands in. Add `research` to its tags. Body structure:

```markdown
# <Topic> research synthesis

## Overview
<2-4 sentence executive summary of what the research found>

## Key Findings
<Bulleted list of the most important claims, each with a [[source page]] citation>

## Core Concepts
<Links to concept pages created, with one-line descriptions>

## Entities & Tools
<Links to entity pages, with one-line descriptions>

## Contradictions & Open Questions
<Where sources disagree or where the research hit limits>

## Sources Consulted
<Linked list of all source pages>
```

## Cross-linking

After filing all pages:
- Every concept page should link to at least 2 source pages
- Every source page should link to the concept pages it informed
- The synthesis page should link to all concept, entity, and source pages produced

Check the page inventory (`.manifest.json`, or a `glob` + frontmatter scan) for existing pages on the same topics — merge into those rather than creating duplicates.

## Update Tracking Files

**`.manifest.json`** — never hand-write it. After writing all pages, run `regen-manifest.py` to resync the manifest from disk (it preserves `ingested_at` and `private_paths`).

**`index.md`** — a base-backed index needs no edit; only a hand-curated one gets the new lines under their respective sections.

**`log.md` and `hot.md` — drive with `wiki-journal.py`, don't hand-edit.** You compose the distilled Recent-Activity line (the research topic and its core finding); the script owns the timestamped log append, `hot.md` prepend/trim to the newest 3, and `updated:` bump:

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-journal.py" --vault "$OBSIDIAN_VAULT_PATH" \
  --log 'WIKI_RESEARCH topic="<topic>" rounds=N sources_fetched=N pages_created=M' \
  --hot-entry '**Researched <topic> — core finding in one line.**' \
  --hot-trim 3
```

**Active Threads** is semantic — the script won't touch it; edit it by hand with Edit if this research is an ongoing thread.

## Quality Checklist

- [ ] 3 rounds completed (or halted at sufficient depth)
- [ ] Master synthesis page exists as `research-<topic-slug>.md` in the vault's synthesis-like category
- [ ] Source pages written for major references
- [ ] Concept and entity pages written for significant items
- [ ] Contradictions flagged in synthesis page
- [ ] All pages cross-linked
- [ ] `log.md` / `hot.md` journaled via `wiki-journal.py`; `.manifest.json` resynced via `regen-manifest.py`; curated `index.md` updated (base-backed needs none)
