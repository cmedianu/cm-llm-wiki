# Page-Writing Protocol

Everything a write-side skill (`wiki-ingest`, `wiki-capture`, `wiki-compact` rewrites and synthesis) needs to produce a valid page. Read this instead of the full `wiki/SKILL.md` theory skill. Category, `index.md` membership, and page inventory are always **discovered from disk**, never assumed.

## Page Template

**Create a new page with the scaffold, not by hand:** `uv run .claude/wiki-scripts/wiki-new.py <category>/<slug> --title "..." --summary "..." --tags a,b [--supersedes <old-snapshot>] --body-file - <<'MD' ... MD`. It checks the name and folder, writes valid date-only frontmatter, and wires supersession. Edit existing pages normally. The template below is what it produces.

```markdown
---
title: Page Title
category: ai
tags: [ml, architecture]
summary: One or two sentences, ≤200 chars — what is this page about?
sources: [papers/attention.pdf]
created: 2024-03-15
updated: 2024-03-15
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

**Required frontmatter:** `title`, `category`, `tags`, `summary`, `created`, `updated` (dates are `yyyy-MM-dd`, never ISO datetimes). `sources` is optional — set it whenever the page distils a source; self-authored pages may omit it. `category` **equals the page's folder, discovered from disk** — never an assumed taxonomy.

**Optional frontmatter** (ingest skills may populate; hand-authored pages can omit):

- `aliases:` — alternate names this page should also resolve as.
- `lifecycle:` — `draft` / `reviewed` / `living` / `archived`. **Ingest-class skills set `lifecycle: draft` + `lifecycle_changed: <today>`.** Only a human promotes lifecycle, and it is left unchanged on update. `living` = intentionally never-finished pages; `archived` = retired/superseded (pairs with `superseded_by`).

## Summary

`summary:` is 1–2 short sentences, under 200 characters — don't count by hand; `wiki-lint` flags a longer one and you shorten it then. It powers `wiki-query`'s cheap retrieval, so rewrite it whenever a page's meaning shifts.

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

**Link each new page to at least two existing pages.** Then run the back-link pass (`ingest-prep.py --backlinks-for <pages>`, judged as in `wiki-ingest` Step 6).

## Privacy digest

Apply before surfacing a page anywhere more public than itself. Both mechanisms are honoured by every read and write skill.

- **`private_paths`** — a top-level key in `.manifest.json` listing private-area path prefixes (e.g. `["me", "context/me"]`). A page's title/summary may appear only in an `index.md` *within its own privacy scope*; a more-public index references a private area only via that area's own section `index.md`. A **synthesis/cross-cutting page drawing on private sources is itself private-scoped** — file it inside the private area or exclude those sources. Vaults with no `private_paths` are unaffected.
- **`visibility/` tags** — `visibility/internal` and `visibility/pii` mark page-level sensitivity. `wiki-query`'s visibility filter drops these for a public/user-facing view. System tags — they do **not** count toward the 5-tag limit. When in doubt, omit — untagged pages are treated as public.

Rule of thumb: *a title or summary travels only as far up as its own privacy scope.*

## Check and journal — never hand-edit

Check only what you wrote, if a check is warranted: `uv run .claude/wiki-scripts/wiki-lint.py --pages <pages you wrote> --summary`. Otherwise rely on the pre-commit gate (lints staged pages, stamps `updated:`); never pass `--no-verify`.

Never hand-write `log.md`, `hot.md` or `.manifest.json`, and don't run `regen-manifest.py` after writing (it only creates or repairs the vault marker).

**Journal** — one `--log` line (≤240 chars) naming the *conceptual* change, not a file list; `wiki-journal.py` timestamps it in `log.md` and prepends it to `hot.md`:

```bash
uv run .claude/wiki-scripts/wiki-journal.py --hot-trim 3 \
  --log 'INGEST source="path/to/source" created=M updated=N: one-line change, [[full/path/wikilinks]]'
```

`hot.md`'s **Key Takeaways / Active Threads / Flagged Contradictions** are semantic — the script never touches them. Edit those by hand with Edit if a write materially shifted one.
