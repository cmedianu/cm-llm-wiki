---
name: wiki-vault
description: >
  Set up a new Obsidian wiki vault, and register which vault a project targets. Use it for "set up my
  wiki", "initialize obsidian", "create a new vault", "get started with the wiki", or to repair a vault
  with no .manifest.json marker. Also for the vault registry: "list my wikis", "which wiki am I on",
  "/wiki-switch", "/wiki-switch NAME", "switch vault", "register this vault", and the vault-picker quiz
  any wiki skill falls back to outside a vault and outside a known project.
---

# Wiki Vault — Set Up a Vault, Map Projects to Vaults

Two jobs that sit *around* a vault rather than editing its pages. A vault needs no config inside it: it is
the directory holding `.manifest.json` (the marker the scripts walk up to, plus `private_paths`), and
every path derives from there, so it stays relocatable. Registration is a home-level convenience for
targeting a vault from *other* projects; inside a vault, resolution is the walk-up and needs nothing.

## Set Up a New Vault

1. **Location.** Ask where it should live (e.g. `~/vaults/personal`).
2. **Categories.** The top-level folders *are* the categories, so this is the one real decision. Offer:
   (a) domain folders named after their subjects (`cooking/`, `finance/`), (b) the Karpathy taxonomy
   `concepts/ entities/ skills/ references/ synthesis/ journal/`, or (c) their own list.
3. **Create the tree, wire it, write the marker:**

   ```bash
   VAULT=<path>; CONTENT=(...)     # the chosen folders
   mkdir -p "$VAULT"/.obsidian "$VAULT"/_archives "$VAULT"/_sources
   for c in "${CONTENT[@]}"; do mkdir -p "$VAULT/$c"; done
   git -C "$VAULT" init                                                  # recommended; before wiring (pre-commit gate)
   <cm-llm-wiki>/wire-vault.sh "$VAULT"                                  # scripts, conventions, hooks, CLAUDE.md, AGENTS.md
   uv run "$VAULT/.claude/wiki-scripts/regen-manifest.py" --vault "$VAULT"   # creates .manifest.json
   ```

   `_archives/` holds retired pages and rebuild snapshots, `_sources/` raw inputs; `_raw/` (drafts to
   promote) and `projects/` appear on demand. Add `private_paths` to `.manifest.json` only if the vault
   grows a private area. Add the daily-note ignore to `.gitignore`
   (`/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md`).
4. **Special files** at the root, each with a `title:` frontmatter:
   - `index.md` — one `##` section per content folder (or a base-backed Obsidian query that needs no edits).
   - `log.md` — `# Wiki Log`; then journal the first line:
     `uv run .claude/wiki-scripts/wiki-journal.py --log 'INIT categories=<folders>: vault created'`.
   - `hot.md` — `## Recent Activity`, `## Active Threads`, `## Key Takeaways`, `## Flagged Contradictions`.
5. **Obsidian config** (optional): `.obsidian/app.json` `{ "defaultViewMode": "preview", "livePreview": true }`.
   Suggest the Dataview and Obsidian Git community plugins.
6. **Verify:** `uv run .claude/wiki-scripts/wiki-lint.py --summary` from a subfolder runs clean (proves
   the walk-up finds the marker). Tell the user to open the vault in Obsidian and start with
   `wiki-ingest` or `wiki-capture`. To target it from other projects, register it (below).

## Registry Basics

All of this lives under `~/.obsidian-wiki/`, never inside a vault:

- **Register a vault:** write `~/.obsidian-wiki/config.<name>` with a one-line `# description` comment
  and `OBSIDIAN_VAULT_PATH=<absolute path>`. Refuse if the name exists.
- **Map a project to a vault:** set `projects.json[<project root>] = "<name>"` in
  `~/.obsidian-wiki/projects.json` (create as `{}`; preserve other keys). Project root = nearest
  ancestor of CWD with `.git`, else CWD. Confirm with the resolved vault path.
- **List:** each `config.*` (not the `config` symlink) with its description, marking the current
  project's mapping and the headless default (`~/.obsidian-wiki/config` symlink target).

The quiz other skills fall back to, and the `/wiki-switch` sub-commands (`where`, `show`, `forget`,
`default`), are in `references/registry.md`.
