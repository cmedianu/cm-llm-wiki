# LLM Wiki — Operating Conventions (shared)

Conventions shared by every Obsidian vault managed by the **wiki-\* skill family**
(`wiki`, `wiki-ingest`, `wiki-capture`, `wiki-query`, `wiki-link`, `wiki-lint`, …).

This file lives in the **`cm-llm-wiki` master repo** and is symlinked into each vault at
`.claude/wiki-conventions.md`, then imported from that vault's `CLAUDE.md` with
`@.claude/wiki-conventions.md`. **Edit it here to update every wiki at once.** Anything
true of only one vault (its folder taxonomy, special namespaces, private areas) belongs in
that vault's own `CLAUDE.md`, not here.

The tooling serves **Claude Code, Codex CLI, and Copilot CLI** from this one copy.
Claude Code (and Copilot) resolve the `@`-import live; Codex has no import mechanism,
so each vault also carries a **generated `AGENTS.md`**: `CLAUDE.md` with these
conventions inlined by `sync-agents.py`. Two consequences, whichever agent you are:

- **Never edit `AGENTS.md`.** It is a build artifact. Change `CLAUDE.md` (vault
  specifics) or this file (shared rules), then re-run `wire-vault` / `sync-agents.py`.
- **Stamp `updated: <yyyy-MM-dd>` in the frontmatter of every page you edit.** All
  three agents have a PostToolUse hook wired to do this automatically
  (`hooks/update-timestamp.py`; same-day re-stamps are no-ops), but if your hook
  isn't active (Codex needs a one-time `/hooks` trust per vault), set it yourself.

**Route work through the skills — do not hand-edit pages ad hoc.** Adding knowledge →
`wiki-ingest` / `wiki-capture`. Answering questions → `wiki-query`. Cross-linking →
`wiki-link`. Health/cleanup → `wiki-lint`. The skills enforce the conventions below.

## Conventions

- **Filenames:** kebab-case-lowercase. Spaces, emoji, and special chars stripped; brand
  names kept as one word (e.g. `vscode`, `libgen`).
- **Frontmatter:** every page has it. Don't create pages without it.
- **Frontmatter values with a colon-space (`: `) must be quoted or rewritten.** In YAML
  `: ` is the key/value separator, so an unquoted value like `title: Acme: A Platform`
  or `summary: site: operators ...` is a parse error and Obsidian silently fails to render
  the whole Properties block. **Prefer rewriting** to remove the colon (e.g. `Title — Subtitle`
  with an em dash, or reword the prose). If the colon is intrinsic — a real proper-name title
  like `"Helios: A Wearable Translator"` — **double-quote the value** instead. Same
  applies to other YAML metacharacters at the start of a value (`#`, `&`, `*`, `[`, `{`, `>`, `|`, `@`, `` ` ``).
  Check the whole vault with `uv run .claude/wiki-scripts/validate-frontmatter.py` (exit 0 = clean);
  run it after any bulk frontmatter edit or ingest.
- **Wikilinks:** use full **vault-relative paths** (e.g. `[[folder/subfolder/page-name]]`),
  not bare basenames — some basenames are not globally unique.
- **Categories mirror the vault's existing top-level folders**, not the llm-wiki default
  taxonomy (concepts/entities/skills). Match the folder a topic already lives in. The
  **folders are authoritative**: don't hand-maintain a category roster (in `CLAUDE.md` or
  anywhere), enumerate categories by listing the folders. A page's `category` must equal its
  folder path (or an ancestor of it). `wiki-lint.py` enforces this (`category_folder_mismatch`),
  because a category that does not mirror the folder silently hides the page from that
  folder's base-backed index.
- **Underscore-prefixed paths (`_*`) are not wiki content.** Any top-level (or nested) dir
  whose name starts with `_` — e.g. `_raw` (ingest staging), `_bin` (tooling), `_strata-emails`
  (a source archive) — is infrastructure/staging, not council content. The wiki scripts skip
  both dotdirs (`.`) and `_`-dirs when walking the vault (`validate-frontmatter.py`,
  `regen-manifest.py`, `wiki-graph.py`), so files there need no frontmatter and never appear
  in indexes or the graph. Put scratch, source archives, and runnable tools under a `_`-dir.
- **Keep `index.md` and `log.md` in sync** when adding, renaming, or removing pages. **Don't hand-append to `log.md` or `hot.md`** — the `wiki-journal.py` script owns the timestamped `log.md` line, the `hot.md` Recent-Activity prepend/trim, and the `updated:` bump; a skill passes it only the distilled one-line entry. `hot.md` is the vault-root ~500-word recent-activity cache (a `## Recent Activity` list plus hand-curated `## Active Threads` / `## Key Takeaways` / `## Flagged Contradictions`): read it for fast context, and edit its semantic sections by hand.
- **Folder indexes can be base-backed** (Obsidian Bases). A folder's `index.md` can describe the
  category (a one-line `summary:` in its frontmatter) and list its pages with a live **base**
  block instead of a hand-maintained bullet list, so adding or renaming a page needs no index
  edit. Scope the base to the folder's category (`category == "<folder>"` **or**
  `category.startsWith("<folder>/")`), show `file.name` + `summary` + `updated`, sort
  `file.mtime` `DESC` (newest first), and exclude the index page itself with
  `file.name != "index"`. Curated indexes can be **hybrid**: keep the hand-written intro and
  put the base below it. `wiki-lint.py` counts base-covered pages as indexed, so they are not
  flagged as orphans or missing-from-index. Note bases render only inside Obsidian; an agent
  reading the raw `.md` sees the base source, not the rows (it should `ls`/read files instead).
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
