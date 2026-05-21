---
name: wiki-setup
description: >
  Initialize a new Obsidian wiki vault with the correct structure and special files.
  Use this skill when the user wants to set up a new wiki from scratch, initialize the vault structure,
  or says things like "set up my wiki", "initialize obsidian", "create a new vault",
  "get started with the wiki". Also use when the user needs to reconfigure their existing vault or
  fix a broken setup. A default vault needs no .env — paths are derived from the vault location.
---

# Obsidian Setup — Vault Initialization

You are setting up a new Obsidian wiki vault (or repairing an existing one).

## Step 1: Pick the Vault Location

Ask the user where the vault should live (e.g. `~/Documents/obsidian-wiki-vault`). The vault is self-describing: its directory contains `.manifest.json`, and every other path the skills need is derived from there by default (`<vault>/_sources/` for raw inputs, `<vault>/_archives/` for snapshots, `$HOME/.claude/projects` for Claude history).

**No `.env` file is created at setup.** Skills work without one. Only create `<vault>/.env` later if the user wants to override a default — e.g. sources living outside the vault, or Claude history at a non-standard path. Even then, never put `OBSIDIAN_VAULT_PATH` in it: the vault is defined by where `.manifest.json` lives, not by an absolute path baked into a config file.

Optional integrations the user may also want (still no `.env` required unless overriding):

- **QMD semantic search.** Enables semantic search in `wiki-query` and source discovery in `wiki-ingest`. Defaults to `QMD_TRANSPORT=mcp`; CLI mode uses `QMD_CLI_SEARCH_MODE=quality`. If unsure, skip — both skills fall back to `Grep` automatically.

## Step 2: Create Vault Directory Structure

```bash
VAULT=<path-from-step-1>
mkdir -p "$VAULT"/{concepts,entities,skills,references,synthesis,journal,projects,_archives,_sources,.obsidian}
echo '{"version":1,"sources":{},"projects":{},"stats":{}}' > "$VAULT/.manifest.json"
```

The `.manifest.json` is the canonical vault marker — its presence is what every skill walks up the CWD looking for.

- `.obsidian/` — Obsidian's own config. Creates vault recognition.
- `projects/` — Per-project knowledge (populated during ingest).
- `_archives/` — Stores wiki snapshots for rebuild/restore operations.
- `_raw/` — Staging area for unprocessed drafts. Drop rough notes here; `wiki-ingest` will promote them to proper wiki pages and delete the originals.

## Step 3: Create Special Files

### index.md

```markdown
---
title: Wiki Index
---

# Wiki Index

*This index is automatically maintained. Last updated: TIMESTAMP*

## Concepts

*No pages yet. Use `wiki-ingest` to add your first source.*

## Entities

## Skills

## References

## Synthesis

## Journal
```

### log.md

```markdown
---
title: Wiki Log
---

# Wiki Log

- [TIMESTAMP] INIT vault_path="OBSIDIAN_VAULT_PATH" categories=concepts,entities,skills,references,synthesis,journal
```

### hot.md

```markdown
---
title: Hot Cache
updated: TIMESTAMP
---

# Hot Cache

*A ~500-word semantic snapshot of recent activity. Updated after every major write operation.*

## Recent Activity

- [TIMESTAMP] INIT — vault created at OBSIDIAN_VAULT_PATH

## Active Threads

*None yet — start ingesting sources to populate.*

## Key Takeaways

*None yet.*

## Flagged Contradictions

*None yet.*
```

## Step 4: Create .obsidian Configuration

Create minimal Obsidian config for a good out-of-box experience:

### .obsidian/app.json
```json
{
  "strictLineBreaks": false,
  "showFrontmatter": false,
  "defaultViewMode": "preview",
  "livePreview": true
}
```

### .obsidian/appearance.json
```json
{
  "baseFontSize": 16
}
```

## Step 5: Recommend Obsidian Plugins

Tell the user about these recommended community plugins (they install manually):

1. **Dataview** — Query page metadata, create dynamic tables. Essential for a wiki.
2. **Graph Analysis** — Enhanced graph view for exploring connections.
3. **Templater** — If they want to create pages manually using templates.
4. **Obsidian Git** — Auto-backup the vault to a git repo.

## Step 6: Verify Setup

Run a quick sanity check:
- [ ] Vault directory exists with: `concepts/`, `entities/`, `skills/`, `references/`, `synthesis/`, `journal/`, `projects/`, `_archives/`, `_sources/`
- [ ] `.manifest.json` exists at vault root (the canonical vault marker)
- [ ] `index.md` exists at vault root
- [ ] `log.md` exists at vault root
- [ ] `hot.md` exists at vault root
- [ ] `.obsidian/` directory exists
- [ ] Walking up from a subdirectory inside the vault finds `.manifest.json` (relocatability check)

Report the results and tell the user they can now:
1. Open the vault in Obsidian (File → Open Vault → select the directory)
2. Run `wiki-status` to see what's available to ingest
3. Run `wiki-ingest` to add their first sources
4. Run `wiki-claude-history` to mine their Claude conversations
5. Run `codex-history-ingest` to mine their Codex sessions (if they use Codex)
6. Run `wiki-status` again anytime to check the delta
