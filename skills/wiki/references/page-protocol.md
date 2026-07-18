# Page-Writing Protocol

Everything a write-side skill (`wiki-ingest`, `wiki-capture`, `wiki-research`, `wiki-link` synthesis, `wiki-compact` rewrites) needs to produce a valid page. Read this instead of the full `wiki/SKILL.md` theory skill. Category, `index.md` membership, and page inventory are always **discovered from disk / the manifest**, never assumed.

## Page Template

```markdown
---
title: Page Title
category: ai
tags: [ml, architecture]
summary: One or two sentences, ≤200 chars — what is this page about?
sources: [papers/attention.pdf]
created: 2024-03-15T10:30:00Z
updated: 2024-03-15T10:30:00Z
---

# Page Title

One-paragraph summary.

## Key Ideas

- A central claim, paraphrased from a source.
- A connection the source implies but doesn't state outright. ^[inferred]
- A figure two sources disagree on. ^[ambiguous]

Use [[wikilinks]] to connect to related pages.

## Sources

- [[references/attention-is-all-you-need]] — Original paper
```

**Required frontmatter:** `title`, `category`, `tags`, `summary`, `sources`, `created`, `updated`. `category` **equals the page's folder, discovered from disk** — never an assumed taxonomy.

**Optional frontmatter** (ingest skills may populate; hand-authored pages can omit):

- `aliases:` — alternate names this page should also resolve as.
- `lifecycle:` — `draft` / `reviewed` / `living` / `archived`. **Ingest-class skills set `lifecycle: draft` + `lifecycle_changed: <today>`.** Only a human promotes lifecycle, and it is left unchanged on update. `living` = intentionally never-finished pages; `archived` = retired/superseded (pairs with `superseded_by`).

## Summary — the <200-char hard rule

`summary:` is 1–2 sentences, **hard limit under 200 characters** — count before writing; `wiki-lint` fails a page at 200+. It powers `wiki-query`'s cheap retrieval, so rewrite it whenever a page's meaning shifts.

## Provenance markers

Every claim carries one of three states. Mark them inline so a reader (or another skill) can tell signal from synthesis; unmarked = extracted.

| State | Marker | Meaning |
|---|---|---|
| **Extracted** | *(no marker — default)* | Paraphrase of what a source says. |
| **Inferred** | `^[inferred]` suffix | LLM-synthesized claim — a connection or generalization. |
| **Ambiguous** | `^[ambiguous]` suffix | Sources disagree, or the source is unclear. |

```markdown
- Transformers parallelize across positions, unlike RNNs.
- This is why they scale better on modern hardware. ^[inferred]
- GPT-4 was trained on roughly 13T tokens. ^[ambiguous]
```

`^[...]` is footnote-adjacent in Obsidian — renders cleanly, never collides with `[[wikilinks]]`. The inline markers are the whole signal — no numeric score.

## Link format

Obsidian **wikilinks** with full vault-relative paths: `[[path/to/page]]` or `[[path/to/page|display]]`. Always use vault-relative paths, not bare basenames — some basenames aren't globally unique.

**Link each new page to at least two existing pages.** Run `wiki-link` / `wiki-lint` to find and fix broken or missing links.

## Privacy digest

Apply before surfacing a page anywhere more public than itself. Both mechanisms are honoured by every read and write skill.

- **`private_paths`** — a top-level key in `.manifest.json` listing private-area path prefixes (e.g. `["me", "context/me"]`). A page's title/summary may appear only in an `index.md` *within its own privacy scope*; a more-public index references a private area only via that area's own section `index.md`. A **synthesis/cross-cutting page drawing on private sources is itself private-scoped** — file it inside the private area or exclude those sources. Vaults with no `private_paths` are unaffected.
- **`visibility/` tags** — `visibility/internal` and `visibility/pii` mark page-level sensitivity. `wiki-query`'s visibility filter drops these for a public/user-facing view. System tags — they do **not** count toward the 5-tag limit. When in doubt, omit — untagged pages are treated as public.

Rule of thumb: *a title or summary travels only as far up as its own privacy scope.*

## Journal + manifest — never hand-edit

After writing pages, resync the manifest and record the change with the scripts — never hand-write `.manifest.json`, `log.md`, or `hot.md`.

**Manifest** — `regen-manifest.py` resyncs from disk (preserves `ingested_at` and `private_paths`):

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/regen-manifest.py" --vault "$OBSIDIAN_VAULT_PATH"
```

**Journal** — `wiki-journal.py` owns the timestamped `log.md` append, the `hot.md` Recent-Activity prepend/trim, and the `updated:` bump. You compose only the distilled one-line entries:

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-journal.py" --vault "$OBSIDIAN_VAULT_PATH" \
  --log 'INGEST source="path/to/source" pages_updated=N pages_created=M mode=append' \
  --hot-entry '**One-line conceptual change.** Detail with [[full/path/wikilinks]].' \
  --hot-trim 3
```

`hot.md`'s **Key Takeaways / Active Threads / Flagged Contradictions** are semantic — the script never touches them. Edit those by hand with Edit if a write materially shifted one.
