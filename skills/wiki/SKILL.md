---
name: wiki
description: >
  The foundational knowledge distillation pattern for building and maintaining an AI-powered Obsidian wiki.
  Based on Andrej Karpathy's LLM Wiki architecture. Use this skill whenever the user wants to understand the
  wiki pattern, set up a new knowledge base, or needs guidance on the three-layer architecture (raw sources →
  wiki → schema). Also use when discussing knowledge management strategy, wiki structure decisions, or how
  to organize distilled knowledge. This is the "theory" skill — other skills handle specific operations
  (ingesting, querying, linting).
---

# LLM Wiki — Knowledge Distillation Pattern

The wiki is a **compiled artifact**: knowledge distilled once and kept current, not re-derived on every query.

Based on Andrej Karpathy's LLM Wiki pattern — <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>

## Three-Layer Architecture

### Layer 1: Raw Sources (immutable)

The user's original documents — articles, papers, notes, PDFs, conversation logs, bookmarks, **and images** (screenshots, whiteboard photos, diagrams). Never modified by the system. Live at `<vault>/_sources/` by default. Images are first-class sources for vision-capable models; non-vision models skip them and report which were skipped.

Think of raw sources as the "source code" — authoritative but hard to query directly.

### Layer 2: The Wiki (LLM-maintained)

A collection of interconnected Obsidian-compatible markdown files. This is the compiled knowledge — synthesized, cross-referenced, navigable. Each page has YAML frontmatter, Obsidian `[[wikilinks]]`, and clear provenance for its claims. The vault is the directory containing `.manifest.json` — that file is the canonical marker.

### Layer 3: The Schema (this skill + config)

The rules governing how the wiki is structured — categories, conventions, page templates, operational workflows. The schema tells the LLM *how* to maintain the wiki.

## Wiki Organization

Organize pages into folders that match your domain. **Categories are discovered from disk**, not declared in config: any top-level directory not prefixed with `_` or `.` is a category. `_foo/` is system state (`_sources/`, `_archives/`), `.foo/` is tool config (`.obsidian/`, `.claude/`). Everything else is content.

**In an existing vault the categories are simply whatever top-level folders are already there.** Discover them by listing the vault root (skipping `_*` and `.*` dirs) and route each new page into the best-fitting existing folder. Never impose a fixed taxonomy on a vault that already has its own.

For a **brand-new empty vault**, any consistent scheme works — two that suit different needs:

- **Domain folders** — folder names mirror the subjects of the notes (`ai/`, `health/`, `recipes/`, etc.). Natural for hand-authored personal wikis.
- **Karpathy taxonomy** — `concepts/`, `entities/`, `skills/`, `references/`, `synthesis/`, `journal/`. Natural for external-source distillation; less so for hand-authored notes.

Neither is privileged: pick whichever fits, or define your own folders, and be consistent within a vault. Because different vaults use different schemas, every downstream skill discovers categories from disk rather than assuming any particular set.

## Special Files

Every wiki has these at its root:

### `index.md`

A content-oriented catalog organized by folder. A curated `index.md` gives each entry a one-line summary and tags:

```markdown
# Wiki Index

## AI
- [[ai/transformer-architecture]] — The dominant architecture for sequence modeling ( #ml #architecture)
- [[ai/attention-mechanism]] — Core building block of transformers ( #ml #fundamentals)
```

**Format rule:** add a space after the opening `(` before the tags.

- ❌ `description (#tag)` — breaks tag parsing
- ✅ `description ( #tag)` — proper spacing

An `index.md` may instead be **base-backed** — an Obsidian Bases query that lists the folder's pages live from their frontmatter. A base renders as rows *only inside Obsidian*; read as raw markdown it is the query source, not a page list. **So never treat `index.md` as the authoritative page inventory** — derive inventory from a `glob` + frontmatter scan. Adding a page needs no edit to a base-backed index; only a hand-curated one gets the new line.

### `log.md`

Append-only operations record. One line per operation:

```markdown
- [2024-03-15T10:30:00Z] INGEST source="papers/attention.pdf" pages_updated=12 pages_created=3
- [2024-03-15T11:00:00Z] QUERY query="How do transformers handle long sequences?" result_pages=4
- [2024-03-16T09:00:00Z] LINT issues_found=2 orphans=1 contradictions=1
```

The op-code list is open — invent new ones as needed. **Don't hand-append.** The `wiki-journal.py` script (see Reference) owns the timestamp, placement, and `updated:` bump; a skill passes it only the distilled one-line entry.

### `hot.md`

A ~500-word semantic snapshot of recent activity — the fast-context file read first by query and ingest skills before they touch `index.md`. It has a `## Recent Activity` list (bounded to the newest few operations) plus hand-curated `## Active Threads`, `## Key Takeaways`, and `## Flagged Contradictions` sections. `wiki-journal.py` prepends and trims the Recent Activity bullet mechanically; the semantic sections are edited by hand.

### `.manifest.json`

The vault marker plus its one piece of config: `{"version", "created", "updated", "private_paths"}`. Its presence marks the vault root for the scripts' walk-up; Obsidian never reads it. It tracks no pages: what changed comes from git, and whether a source was already ingested from its `_sources/` snapshot (`ingest-prep.py`'s `source_status`). `regen-manifest.py` creates or repairs it and strips legacy per-page entries.

## Page Template

Every page has YAML frontmatter (`title`, `category` = its folder, `tags`, `summary` under 200 chars, optional `sources`, date-only `created`/`updated`), a one-paragraph summary, the claims with provenance markers, and full-path `[[wikilinks]]`. `wiki-new.py` writes it; the full template is in `references/page-protocol.md`.

### URL sources

`sources:` entries are vault-relative paths or full URLs (`http(s)://` is the discriminator), mixed freely. For any URL that is **evidence** for a non-trivial claim, store a local snapshot under `_sources/web/<slug>.md` *and* the URL. See **`references/vault-mechanics.md` → URL Sources** for the snapshot conventions.

### Folder naming convention

Top-level folders (categories) and subfolders both use **kebab-case-lowercase**, matching the filename convention. Examples: `ai/`, `git/`, `mcp/`, `science-fair/`, `projects/`.

Why: consistent with kebab-case filenames, URL-safe, no shift-key ambiguity, plays nicely with Obsidian wikilink resolution (case-insensitive on Windows but case-sensitive on Linux/WSL — lowercase removes the footgun).

Exceptions that may keep TitleCase: none enforced, but if you prefer prettier sidebar display in Obsidian and only ever access the vault on Windows/macOS (case-insensitive), TitleCase top-level folders work too. Pick one style per vault — mixing is what breaks.

**To add** a category: `mkdir <name>` at the vault root — skills discover it on next read, no config edit needed. **To rename, remove, or hide** one (including the `kebab-rename.py` lockstep rename + wikilink rewrite), see **`references/vault-mechanics.md` → Renaming a Category**.

Optional frontmatter fields (ingest skills may populate; hand-authored pages can omit):

- `aliases:` — alternate names this page should also resolve as.
- `lifecycle:` — `draft` / `reviewed` / `living` / `archived`. Default `reviewed` for human-authored; only ingest skills set `draft`. `living` = intentionally never-finished pages updated continuously (dossiers, running ledgers); `archived` = retired or superseded (pairs with `superseded_by`). A qualitative, human-curated state — transitions are manual.

## Provenance Markers

Every claim is **extracted** (no marker, the default: a paraphrase of a source), **inferred** (`^[inferred]`: a connection or generalization the LLM drew), or **ambiguous** (`^[ambiguous]`: sources disagree or are unclear). `^[...]` is footnote-adjacent in Obsidian, so it renders cleanly and never collides with `[[wikilinks]]`; unmarked legacy pages stay valid.

## Retrieval, Link Format, Privacy

The cheapest-first retrieval table lives in **`references/primitives.md`**; the wikilink format and the privacy rules (`private_paths`, `visibility/` tags) live in **`references/page-protocol.md`**.

## Core Principles

1. **Compile, don't retrieve.** The wiki is pre-compiled knowledge. When you ingest a source, update every relevant page — don't just create a summary of the source.
2. **Compound over time.** Each ingest should make the wiki smarter, not just bigger. Merge new information into existing pages, resolve contradictions, strengthen cross-references.
3. **Provenance matters.** Every claim should trace to a source. When updating a page, note which source prompted the update.
4. **Mark inferences.** Default = extracted. Mark synthesized claims `^[inferred]`, contested claims `^[ambiguous]`. A wiki that hides its guessing rots silently.
5. **Human curates, LLM maintains.** Human decides what sources to add and what questions to ask. LLM handles the bookkeeping.
6. **Obsidian is the IDE.** The user browses in Obsidian. Everything must be valid Obsidian markdown with working wikilinks.

## Page-Writing Protocol

Every skill that **creates or updates pages** (`wiki-ingest`, including its Claude-history mode; `wiki-capture`, including its project-sync mode; `wiki-compact` rewrites and synthesis) follows one shared contract rather than restating it. In one breath: create new pages with `wiki-new.py` (valid frontmatter, `category` = the disk folder, `lifecycle: draft`), keep `summary:` **under 200 chars**, mark claims `^[inferred]`/`^[ambiguous]` (unmarked = extracted), link each new page to **≥2** existing pages via full vault-relative wikilinks, honour the privacy rules before surfacing anywhere more public, and record the change with `wiki-journal.py` (never hand-edit the journal or manifest). Category, `index.md` membership, and page inventory are all **discovered from disk**, never assumed.

**The full contract — everything a write-side skill needs and nothing else — lives in `references/page-protocol.md`. Read that instead of this whole theory skill when your only job is to write a page.**

## Orphans

An **orphan** is a content page with no incoming wikilinks from other **content** pages — `index.md`, `log.md`, and `hot.md` do not count as incoming links. `wiki-lint.py` and `wiki-graph.py` compute orphans deterministically; treat their output as the source of truth rather than re-deriving it by reading pages.

## Config Resolution Protocol

The vault is self-describing — **zero configuration**, no config file or per-vault settings. The vault is the directory containing `.manifest.json`; every other path derives from it (`_sources/`, `_archives/`, …). Categories are discovered from disk (any top-level dir not prefixed `_` or `.`). No API keys — the agent already has LLM access.

**Resolve the vault** in this order, stopping at the first hit:

1. **Walk up from CWD** for `.manifest.json` (stop at `$HOME` or `/`). Found means you are inside a vault; use it. This always wins, so working inside a vault never needs any config.
2. **Project map.** Look up the current project root (CWD or nearest ancestor) in `~/.obsidian-wiki/projects.json` (a `{ "project-path": "vault-name" }` map). A hit resolves to that registered vault's `OBSIDIAN_VAULT_PATH` (from `~/.obsidian-wiki/config.<name>`).
3. **Quiz (interactive).** No manifest above you and no project-map entry means ask: list the registered vaults (`~/.obsidian-wiki/config.*`) and have the user pick one, then **persist** the choice to `projects.json` under the current project root so you do not ask again. The quiz is in `wiki-vault/references/registry.md`; every skill runs the same one.
4. **Headless fallback.** When no user is present (cron, scripted runs), read `OBSIDIAN_VAULT_PATH` from the active global config `~/.obsidian-wiki/config` (a symlink to one `config.<name>`).
5. **Nothing registered** at all: tell the user to set one up with `wiki-vault`.

The maintenance scripts do the walk-up (step 1) themselves. Standard skill setup line:

> **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`: manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz the registered vaults (persisting the choice). All paths derive from the vault root.

**Relocatability invariant:** `cp -r <vault> <new-location> && cd <new-location>` must produce a fully functional wiki with zero edits — so no absolute paths inside the vault. Runtime state written *outside* the vault is scoped by a hash of the vault path.

The `find_vault` shell function, the derived-paths table, vault-scoped-state hashing, and the full relocatability rules live in **`references/vault-mechanics.md`**.

## Modes of Operation

Three ingest modes:

| Mode | When | What happens |
|---|---|---|
| **Append** | Small delta, incremental updates | Ingest only new or changed sources (`source_status` from the `_sources/` snapshot) |
| **Rebuild** | Major drift, fresh start needed | Archive current wiki to `_archives/`, clear, reprocess all sources |
| **Restore** | Need to go back | Bring back a previous archive |

Use `wiki-lint` Status mode to see what changed and what is waiting. Use `wiki-compact` (Rebuild Mode) for archive/rebuild/restore.

## Reference

Companion skills (`../`):

- **wiki-capture**: Save the current conversation as a wiki page; **project-sync mode** pushes knowledge from any working project into the wiki
- **wiki-ingest**: Distill sources into wiki pages, then the back-link pass; **Claude-history mode** mines `~/.claude` session data
- **wiki-query**: Answer questions against the wiki
- **wiki-lint**: Audit and maintain wiki health; **Status mode** (what changed, what is waiting) and **Insights mode** (hubs, bridges)
- **wiki-compact**: Merge duplicates, archive stale pages, retire dead sub-areas to `_archives/`, roll the log; **synthesis** pages; **Rebuild Mode** archives/rebuilds/restores the whole wiki
- **wiki-archive**, **wiki-journal**: shortcuts into compact's retire action and `wiki-journal.py`
- **wiki-vault**: Set up a new vault; register vaults and map projects to them

Maintenance scripts (`../../scripts/`, symlinked into vaults as `.claude/wiki-scripts/`):

- `wiki-lint.py` — deterministic health checks (orphans, broken links, frontmatter, index, stale, lifecycle, provenance ratios). Used by `wiki-lint`.
- `wiki-graph.py` — wikilink-graph analysis (hubs, tag cohesion, orphans, bridges, cross-category edges, delta). Used by `wiki-lint` Insights mode.
- `regen-manifest.py` — create or repair the `.manifest.json` vault marker (keeps `private_paths`, strips legacy per-page entries). Not a write step.
- `ingest-prep.py` — single-call read-only ingest prep (discovered categories, `private_paths`, per-source `source_status`, `index_status`, keyword-matched `related_pages`); also a `--backlinks-for` mode surfacing back-link candidates for new pages. Run first by every write-side skill (`--source none` when there is no source file); `--backlinks-for` is the back-link pass in ingest and capture.
- `wiki-journal.py` — mechanical `log.md` append + `hot.md` Recent-Activity prepend/trim + `updated:` bump. The write skills call this instead of hand-editing the journal; they supply only the distilled one-line entry.
- `kebab-rename.py` — mass kebab-case rename + wikilink rewrite
- `sync-agents.py` — regenerate a vault's `AGENTS.md` from its `CLAUDE.md` (for agents with no `@`-import mechanism); run after editing `wiki-conventions.md`

Reference (`references/`):

- `karpathy-pattern.md` — the original LLM Wiki pattern explained
- `page-protocol.md` — the full Page-Writing Protocol (template, link format, privacy); what write-side skills read instead of this whole skill
- `primitives.md` — the Retrieval Primitives table; what read-side skills read instead of this whole skill
- `vault-mechanics.md` — config resolution, relocatability, URL snapshots, category renames (read on demand, not every op)
