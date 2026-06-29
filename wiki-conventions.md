# LLM Wiki — Operating Conventions (shared)

Conventions shared by every Obsidian vault managed by the **wiki-\* skill family**
(`wiki`, `wiki-ingest`, `wiki-capture`, `wiki-query`, `wiki-link`, `wiki-lint`, …).

This file lives in the **`cm-llm-wiki` master repo** and is symlinked into each vault at
`.claude/wiki-conventions.md`, then imported from that vault's `CLAUDE.md` with
`@.claude/wiki-conventions.md`. **Edit it here to update every wiki at once.** Anything
true of only one vault (its folder taxonomy, special namespaces, private areas) belongs in
that vault's own `CLAUDE.md`, not here.

**Route work through the skills — do not hand-edit pages ad hoc.** Adding knowledge →
`wiki-ingest` / `wiki-capture`. Answering questions → `wiki-query`. Cross-linking →
`wiki-link`. Health/cleanup → `wiki-lint`. The skills enforce the conventions below.

## Conventions

- **Filenames:** kebab-case-lowercase. Spaces, emoji, and special chars stripped; brand
  names kept as one word (e.g. `vscode`, `libgen`).
- **Frontmatter:** every page has it. Don't create pages without it.
- **Frontmatter values with a colon-space (`: `) must be quoted or rewritten.** In YAML
  `: ` is the key/value separator, so an unquoted value like `title: Speculor: A Platform`
  or `summary: site: operators ...` is a parse error and Obsidian silently fails to render
  the whole Properties block. **Prefer rewriting** to remove the colon (e.g. `Title — Subtitle`
  with an em dash, or reword the prose). If the colon is intrinsic — a real proper-name title
  like `"ConchShell: A Wearable ASL Translator"` — **double-quote the value** instead. Same
  applies to other YAML metacharacters at the start of a value (`#`, `&`, `*`, `[`, `{`, `>`, `|`, `@`, `` ` ``).
  Check the whole vault with `uv run .claude/wiki-scripts/validate-frontmatter.py` (exit 0 = clean);
  run it after any bulk frontmatter edit or ingest.
- **Wikilinks:** use full **vault-relative paths** (e.g. `[[folder/subfolder/page-name]]`),
  not bare basenames — some basenames are not globally unique.
- **Categories mirror the vault's existing top-level folders**, not the llm-wiki default
  taxonomy (concepts/entities/skills). Match the folder a topic already lives in.
- **Underscore-prefixed paths (`_*`) are not wiki content.** Any top-level (or nested) dir
  whose name starts with `_` — e.g. `_raw` (ingest staging), `_bin` (tooling), `_strata-emails`
  (a source archive) — is infrastructure/staging, not council content. The wiki scripts skip
  both dotdirs (`.`) and `_`-dirs when walking the vault (`validate-frontmatter.py`,
  `regen-manifest.py`, `wiki-graph.py`), so files there need no frontmatter and never appear
  in indexes or the graph. Put scratch, source archives, and runnable tools under a `_`-dir.
- **Keep `index.md` and `log.md` in sync** when adding, renaming, or removing pages.
- **No hardcoded inventory counts.** Don't write fixed tallies of pages, skills, scripts,
  sources, etc. into prose ("Catalog of all 65 pages", "the 12 skills", "28 abstracts") —
  they go stale the moment anything is added or removed, and nothing keeps them honest.
  Describe the collection ("Catalog of the vault's pages") instead of counting it. If a
  count is genuinely needed, compute it at read time rather than freezing it in text. This
  applies to any quantity that drifts, not just page counts.
- **Provenance is qualitative, not numeric.** Trustworthiness lives in the inline markers
  `^[inferred]` / `^[ambiguous]` (default = extracted) and in the human-set `lifecycle`
  state — not in confidence decimals, affinity integers, or cohesion ratios. Anything
  graph- or count-shaped (orphans, hubs, cohesion, link/synthesis ranking) is computed on
  demand by the scripts (`wiki-lint.py`, `wiki-graph.py`), never hand-rolled into a stored
  score. Don't reintroduce numeric scoring into pages.
- **Indexes respect privacy scope — no upward leak.** A page's title/summary may only appear in
  an `index.md` within its *own* privacy scope. If a vault designates **private areas** (declared
  as `private_paths` in `.manifest.json` — path prefixes like `me` or `context/me`), then each
  private area keeps its **own second-level `index.md`** cataloguing its pages, and any more-public
  index (the shareable root, or an index in another area) references that area only by a **single
  link to its section `index.md`** with a generic label — never by listing the private pages or
  their summaries. Rule of thumb: *a summary travels only as far up as its own privacy scope.*
  `wiki-lint.py` enforces this (`index_privacy_leak`); the key is preserved across
  `regen-manifest.py` runs. Vaults with no `private_paths` are unaffected (the check is a no-op).
