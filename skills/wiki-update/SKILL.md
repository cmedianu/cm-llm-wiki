---
name: wiki-update
description: >
  Sync the current project's knowledge into the Obsidian wiki. Use this skill from any project
  when the user says "update wiki", "sync to wiki", "save this to my wiki", "update obsidian",
  or wants to distill what they've been working on into their knowledge base. This is the
  cross-project skill that lets you push knowledge from wherever you are into the vault.
---

# Wiki Update — Sync Any Project to Your Wiki

You are distilling knowledge from the current project into the user's Obsidian wiki. This skill works from any project directory, not just the obsidian-wiki repo.

## Before You Start

1. **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`: manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz the registered vaults (persisting the choice). All paths derive from the vault root.
2. **Discover categories from disk** — `ls` the vault root (skip `_*` and `.*` dirs); the top-level folders *are* the categories. Never assume a fixed taxonomy.
3. **Check whether this project is already in the vault** — glob `$OBSIDIAN_VAULT_PATH/projects/<project-name>/` and/or grep the pages' `sources:` frontmatter for the project. Don't parse `index.md` for this — it may be a base-backed query, not a page list; derive inventory from `.manifest.json` or a `glob` + frontmatter grep instead.

When writing internal links in Steps 4–5, apply the link format from `wiki/SKILL.md` (Link Format section) using vault-relative wikilinks.

## Step 1: Understand the Project

Figure out what this project is by scanning the current working directory:

- `README.md`, docs/, any markdown files
- Source structure (frameworks, languages, key abstractions)
- `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml` or whatever defines the project
- Git log (focus on commit messages that signal decisions, not "fix typo" stuff)
- Claude memory files if they exist (`.claude/` in the project)

Derive a clean project name from the directory name.

## Step 2: Compute the Delta

There is no per-project tracking in the manifest, so bound the delta from what's already on disk:

- **First-time sync?** (the existence check in *Before You Start* found no vault pages for this project) → full scan. Everything is new.
- **Re-sync?** Find the newest `updated:` timestamp across this project's existing vault pages and only consider what changed since then: `git log --since="<that date>" --oneline`. If the user supplied a ref, bound with `git log <ref>..HEAD --oneline` instead.

Focus on commit messages that signal decisions, not "fix typo" churn. If nothing meaningful changed since last sync, tell the user and stop.

## Step 3: Decide What to Distill

This is the core question from Karpathy's pattern: **what would you want to know about this project if you came back in 3 months with zero context?**

Worth distilling:

- Architecture decisions and *why* they were made
- Patterns discovered while building (things you'd Google again otherwise)
- What tools, services, APIs the project depends on and how they're wired together
- Key abstractions, how they connect, what the mental model is
- Trade-offs that were evaluated, what was picked and why
- Things learned while building that aren't obvious from reading the code

Not worth distilling:

- File listings, boilerplate, config that's obvious
- Individual bug fixes with no broader lesson
- Dependency versions, lock file contents
- Implementation details the code already says clearly
- Routine changes anyone could read from the diff

The heuristic: **if reading the codebase answers the question, don't wiki it. If you'd have to re-derive the reasoning by reading git blame across 20 commits, wiki it.**

## Step 4: Distill into Wiki Pages

Write each page per the **Page-Writing Protocol** in `wiki/SKILL.md` (frontmatter, summary <200 chars, provenance markers, ≥2 wikilinks, privacy, journal, manifest). This step covers only what's specific to a project sync: where pages go and how to map code/commits to provenance.

### Project-specific knowledge

Goes under `$VAULT/projects/<project-name>/`, with an overview page plus discovered subcategories:

- `projects/<project-name>/<project-name>.md` — the overview page (named after the project, **never** `_project.md`): what the project is (one paragraph), its key concepts and how they connect, and links out to the project-specific and global pages.
- `projects/<project-name>/<subcategory>/…` — group the rest into whatever subcategories fit the project (e.g. an architecture concept, a how-to pattern, a source summary). Reuse subfolders that already exist under this project; don't impose a fixed set.

### Global knowledge

Anything that isn't project-specific is general knowledge — route it to the **best-fitting existing category** discovered by listing the vault root (Step 2 of *Before You Start*), not to an assumed taxonomy. A general concept, a reusable technique, a tool or person each belong wherever the vault already keeps that kind of page. If genuinely nothing fits, `mkdir` a new top-level category rather than forcing a page into the wrong folder.

### Provenance for code

Apply the markers per the Page-Writing Protocol, mapped to a codebase:

- **Extracted** *(no marker)* — anything visible in the code, config, or a doc/commit message: file structure, dependencies, function signatures, what a file does.
- **Inferred** `^[inferred]` — *why* a decision was made, design rationale, trade-offs, "the team chose X because Y" — unless a commit message, doc, or ADR states it explicitly.
- **Ambiguous** `^[ambiguous]` — when the code and docs disagree, or when there's clearly an in-progress migration with two patterns living side by side.

A good project-sync `summary:` answers "what does this page tell me about the project I wouldn't guess from its title?"

### Updating vs creating

- If a page already exists in the vault, **merge** new information into it. Don't create duplicates.
- If you're adding to an existing page, update the `updated` timestamp and add the new source.
- Before creating anything, check for an existing page via `.manifest.json` or a `glob` + frontmatter grep — never by parsing `index.md` (it may be base-backed).

## Step 5: Cross-link

After creating/updating pages:

- Add `[[wikilinks]]` from new pages to existing related pages
- Add `[[wikilinks]]` from existing pages back to the new ones where relevant
- Link the project overview to all project-specific pages and relevant global pages

## Step 6: Update Tracking

### Resync `.manifest.json`

Never hand-write the manifest. After writing pages, run `regen-manifest.py` to resync it from disk (it preserves `ingested_at` and `private_paths`):

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/regen-manifest.py" --vault "$OBSIDIAN_VAULT_PATH"
```

### Update `index.md`

A base-backed index needs no edit — it lists pages live from their frontmatter. Only a hand-curated `index.md` gets a new line per created page.

### Update `log.md` and `hot.md`

Drive both with `wiki-journal.py` — don't hand-edit. You compose the distilled Recent-Activity line (write it *conceptually*, e.g. "Synced obsidian-wiki — added wiki-capture and wiki-research skills; core new capabilities are autonomous web research and conversation capture"); the script owns the timestamped log append, `hot.md` prepend/trim to the newest 3, and `updated:` bump:

```bash
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-journal.py" --vault "$OBSIDIAN_VAULT_PATH" \
  --log 'WIKI_UPDATE project=<project-name> pages_updated=X pages_created=Y source_cwd=/path/to/project' \
  --hot-entry '**One-line conceptual summary of what was synced.**' \
  --hot-trim 3
```

**Active Threads** and **Key Takeaways** are semantic — the script won't touch them; edit them by hand with Edit if this sync made this project an ongoing focus or surfaced a key architectural insight/decision.

## Tips

- **Be aggressive about merging.** If the project uses React Server Components, don't create a new page if `concepts/react-server-components.md` already exists. Update the existing one and add this project as a source.
- **Consult the tag taxonomy.** Read `$VAULT/_meta/taxonomy.md` if it exists, and use canonical tags.
- **Don't copy code.** Distill the *knowledge*, not the implementation. "This project uses a debounced search pattern with 300ms delay" is useful. Pasting the actual debounce function is not.
- **Project overview is the anchor.** The `<project-name>.md` file is what you'd read to get oriented. Make it good.
