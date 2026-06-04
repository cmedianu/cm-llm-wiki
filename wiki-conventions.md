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
- **Keep `index.md` and `log.md` in sync** when adding, renaming, or removing pages.
