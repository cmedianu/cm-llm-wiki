---
name: wiki-setup
description: >
  Initialize a new Obsidian wiki vault with the correct structure and special files.
  Use this skill when the user wants to set up a new wiki from scratch, initialize the vault structure,
  or says things like "set up my wiki", "initialize obsidian", "create a new vault",
  "get started with the wiki". Also use when the user needs to reconfigure their existing vault or
  fix a broken setup. A vault needs no config file — paths are derived from the vault location.
---

# Obsidian Setup — Vault Initialization

You are setting up a new Obsidian wiki vault (or repairing an existing one).

## Step 1: Pick the Vault Location

Ask the user where the vault should live (e.g. `~/Documents/obsidian-wiki-vault`). The vault is self-describing: its directory contains `.manifest.json`, and every other path the skills need is derived from there by default (`<vault>/_sources/` for raw inputs, `<vault>/_archives/` for snapshots, `$HOME/.claude/projects` for Claude history).

**No config file is created *inside* the vault — and none is needed.** The vault is defined by where `.manifest.json` lives, and skills derive every path from that, so the vault stays relocatable.

Optionally **register** the vault so it is selectable from other (non-wiki) projects: `/wiki-switch new <name>` writes `~/.obsidian-wiki/config.<name>` (a home-level pointer, never inside the vault). Registered vaults appear in the `wiki-switch` quiz that other skills fall back to when run outside any vault. Registration is convenience, not a requirement: working *inside* the vault always resolves by manifest walk-up with no config at all.

## Step 2: Create Vault Directory Structure

First **ask the user which category scheme they want** — the top-level content folders *are* the categories, so this is the one real decision. Offer three equal options:

- **(a) Domain folders** named after their own subjects (e.g. `cooking/`, `finance/`, `work/`) — best when the vault is about a known set of topics.
- **(b) The Karpathy taxonomy** `concepts/ entities/ skills/ references/ synthesis/ journal/` — a ready-made general-purpose starter.
- **(c) Their own list** — whatever folders they name.

Then create the infrastructure dirs plus whichever **content** folders they chose:

```bash
VAULT=<path-from-step-1>
CONTENT=(...)   # the folders the user chose in step 2
mkdir -p "$VAULT"/.obsidian "$VAULT"/_archives "$VAULT"/_sources
for c in "${CONTENT[@]}"; do mkdir -p "$VAULT/$c"; done
printf '{"version":1,"vault_path":"%s","created":"%s","updated":"%s","sources":{}}\n' \
  "$VAULT" "$(date -u +%FT%TZ)" "$(date -u +%FT%TZ)" > "$VAULT/.manifest.json"
```

The `.manifest.json` is the canonical vault marker — its presence is what every skill walks up the CWD looking for. The minimal seed above is enough; `private_paths` gets added later if the vault grows a private area, and you can always re-derive the manifest from disk with `regen-manifest.py` once folders and pages exist.

- `.obsidian/` — Obsidian's own config. Creates vault recognition.
- `_archives/` — Stores wiki snapshots for rebuild/restore operations.
- `_sources/` — Raw inputs staged for ingest.
- `_raw/` — Optional staging area for unprocessed drafts. Drop rough notes here; `wiki-ingest` will promote them to proper wiki pages and delete the originals.
- `projects/` — Optional; created on demand when `wiki-ingest` files per-project knowledge. Not part of the mandatory scaffold.

## Step 3: Create Special Files

### index.md

A minimal catalog whose `##` sections mirror the folders the user actually chose in Step 2 — one heading per content folder, in the same order. (For a hands-off index, a base-backed Obsidian query per the wiki conventions works too, and needs no editing as pages are added.)

```markdown
---
title: Wiki Index
---

# Wiki Index

*This index is automatically maintained. Last updated: TIMESTAMP*

## <Category One>

*No pages yet. Use `wiki-ingest` to add your first source.*

## <Category Two>

<!-- one ## section per content folder chosen in Step 2 -->
```

Entries added later follow the vault format — put a space after `(` before tags, e.g. `- [[page]] ( #tag )`.

### log.md

```markdown
---
title: Wiki Log
---

# Wiki Log

- [TIMESTAMP] INIT vault_path="OBSIDIAN_VAULT_PATH" categories=<the folders chosen in Step 2, comma-separated>
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
- [ ] Vault directory exists with: the content folders you chose in Step 2, plus `_archives/`, `_sources/`, `.obsidian/`
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
5. Run `wiki-status` again anytime to check the delta
