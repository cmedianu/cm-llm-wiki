---
name: wiki-vault
description: >
  Initialize an Obsidian wiki vault and manage which vault a project targets. Use this skill to set up a
  new wiki from scratch ("set up my wiki", "initialize obsidian", "create a new vault", "get started with
  the wiki"), or to reconfigure/repair an existing vault. Also use it to choose or switch the active vault
  and manage the vault registry ("/wiki-switch", "/wiki-switch NAME", "switch to my work wiki", "switch
  vault", "change wiki", "which wiki am I on", "list my wikis", "show my vaults", "create a new vault
  config", "add a new wiki profile"), and it runs the vault-picker quiz any wiki skill falls back to when
  run outside a vault and outside a known project. Vaults are registered as config files at
  ~/.obsidian-wiki/config.NAME; a per-project choice is stored in ~/.obsidian-wiki/projects.json so a
  project keeps targeting the same vault without re-asking.
---

# Wiki Vault: Initialize a Vault and Choose Which One a Project Uses

This skill owns two related jobs that both sit *around* a vault rather than editing its pages:

- **Initialize** a new Obsidian wiki vault (or repair a broken one). See **Part A**.
- **Select / switch** which registered vault a project targets, plus the registry and the vault-picker
  quiz that the [Config Resolution Protocol](../wiki/SKILL.md) falls back to. See **Part B**.

A vault needs **no config file inside it**: it is defined by where `.manifest.json` lives, and skills
derive every path from that, so the vault stays relocatable. Registration (Part B) is a home-level
convenience for targeting a vault from *other* projects. Working *inside* a vault always resolves by
manifest walk-up with no config at all.

---

# Part A: Initialize a Vault

You are setting up a new Obsidian wiki vault (or repairing an existing one).

## A1: Pick the vault location

Ask the user where the vault should live (e.g. `~/Documents/obsidian-wiki-vault`). The vault is
self-describing: its directory contains `.manifest.json`, and every other path is derived from there by
default (`<vault>/_sources/` for raw inputs, `<vault>/_archives/` for snapshots, `$HOME/.claude/projects`
for Claude history). **No config file is created inside the vault, and none is needed.**

Optionally **register** the vault so it is selectable from other (non-wiki) projects with Part B's
**New** command. That writes `~/.obsidian-wiki/config.<name>`, a home-level pointer, never inside the
vault.

## A2: Create the vault directory structure

First **ask the user which category scheme they want**. The top-level content folders *are* the
categories, so this is the one real decision. Offer three equal options:

- **(a) Domain folders** named after their subjects (`cooking/`, `finance/`, `work/`), best when the
  vault is about a known set of topics.
- **(b) The Karpathy taxonomy** `concepts/ entities/ skills/ references/ synthesis/ journal/`, a
  ready-made general-purpose starter.
- **(c) Their own list** of whatever folders they name.

Then create the infrastructure dirs plus the chosen **content** folders:

```bash
VAULT=<path-from-A1>
CONTENT=(...)   # the folders the user chose
mkdir -p "$VAULT"/.obsidian "$VAULT"/_archives "$VAULT"/_sources
for c in "${CONTENT[@]}"; do mkdir -p "$VAULT/$c"; done
printf '{"version":1,"vault_path":"%s","created":"%s","updated":"%s","sources":{}}\n' \
  "$VAULT" "$(date -u +%FT%TZ)" "$(date -u +%FT%TZ)" > "$VAULT/.manifest.json"
```

The `.manifest.json` is the canonical vault marker: its presence is what every skill walks up the CWD
looking for. The minimal seed above is enough; `private_paths` gets added later if the vault grows a
private area, and you can always re-derive the manifest from disk with `regen-manifest.py`.

- `.obsidian/`: Obsidian's own config; creates vault recognition.
- `_archives/`: wiki snapshots for rebuild/restore (see `wiki-compact` Rebuild Mode).
- `_sources/`: raw inputs staged for ingest.
- `_raw/`: optional staging for unprocessed drafts; `wiki-ingest` promotes them to pages and deletes the
  originals.
- `projects/`: optional; created on demand when `wiki-ingest` files per-project knowledge.

## A3: Create the special files

### index.md

A minimal catalog whose `##` sections mirror the folders chosen in A2, one heading per content folder,
in order. (A base-backed Obsidian query works too and needs no editing as pages are added.)

```markdown
---
title: Wiki Index
---

# Wiki Index

*This index is automatically maintained. Last updated: TIMESTAMP*

## <Category One>

*No pages yet. Use `wiki-ingest` to add your first source.*

## <Category Two>

<!-- one ## section per content folder chosen in A2 -->
```

Entries added later follow the vault format: put a space after `(` before tags, e.g.
`- [[page]] ( #tag )`.

### log.md

```markdown
---
title: Wiki Log
---

# Wiki Log

- [TIMESTAMP] INIT vault_path="OBSIDIAN_VAULT_PATH" categories=<folders chosen in A2, comma-separated>
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

- [TIMESTAMP] INIT, vault created at OBSIDIAN_VAULT_PATH

## Active Threads

*None yet. Start ingesting sources to populate.*

## Key Takeaways

*None yet.*

## Flagged Contradictions

*None yet.*
```

## A4: Create .obsidian configuration

Minimal config for a good out-of-box experience:

```json
// .obsidian/app.json
{ "strictLineBreaks": false, "showFrontmatter": false, "defaultViewMode": "preview", "livePreview": true }
```

```json
// .obsidian/appearance.json
{ "baseFontSize": 16 }
```

## A5: Recommend Obsidian plugins

Tell the user about these community plugins (installed manually): **Dataview** (query metadata, dynamic
tables, essential), **Graph Analysis** (enhanced graph view), **Templater** (manual page templates), and
**Obsidian Git** (auto-backup to a git repo).

## A6: Verify setup

- [ ] Vault has the chosen content folders plus `_archives/`, `_sources/`, `.obsidian/`
- [ ] `.manifest.json` exists at vault root (the canonical vault marker)
- [ ] `index.md`, `log.md`, `hot.md` exist at vault root
- [ ] Walking up from a subdirectory inside the vault finds `.manifest.json` (relocatability check)

Report results and tell the user they can now open the vault in Obsidian, run `wiki-status` to see what
is available, `wiki-ingest` to add sources (documents or Claude history), and `wiki-status` anytime to
check the delta. To target this vault from another project, register it with Part B's **New**, then
**Set**.

---

# Part B: Switch / Manage Vaults

Each vault is registered as a config file `~/.obsidian-wiki/config.<name>` holding its
`OBSIDIAN_VAULT_PATH`. **Which vault a given project uses** is recorded in the project map
`~/.obsidian-wiki/projects.json` (`{ "project-path": "vault-name" }`). This part manages both and runs
the **quiz** that other skills fall back to when they can resolve no vault. It is the layer above the
[Config Resolution Protocol](../wiki/SKILL.md) (manifest walk-up, then project map, then quiz, then
headless fallback). It never edits a vault; it only touches files under `~/.obsidian-wiki/`.

**Project root** is the nearest ancestor of CWD containing `.git`, else CWD itself. Use its absolute path
as the `projects.json` key. (A directory already inside a vault resolves by manifest walk-up and never
reaches this part.)

## Dispatch

| Invocation | Action |
|---|---|
| `/wiki-switch` (no args) | Run **Quiz** (always ask, even if a mapping exists) |
| `/wiki-switch <name>` | **Set** this project's vault to `<name>` |
| `/wiki-switch list` | **List** registered vaults + current project's mapping |
| `/wiki-switch where` | **Where** (show how CWD resolves and why) |
| `/wiki-switch show [name]` | **Show** a config file |
| `/wiki-switch new <name>` | **New** (register a vault) |
| `/wiki-switch forget` | **Forget** this project's mapping |
| `/wiki-switch default <name>` | **Default** (set the headless global fallback) |

## Quiz (no args, and the fallback other skills invoke)

Ask which registered vault this project should use, then remember it.

1. List registry entries `~/.obsidian-wiki/config.*` (exclude the `config` symlink). For each, read the
   first non-empty comment line as its description. If none exist, tell the user to run
   `/wiki-switch new <name>` or initialize one with Part A first.
2. Present a numbered pick-list with descriptions, marking the project's current mapping (if any):
   ```
   Which vault for this project (/home/me/code/app)?
     1. personal   Personal notes vault   [current]
     2. work       Work knowledge base
     3. research   Research vault
   ```
3. On the choice, **persist** it: set `projects.json[<project-root>] = <name>` (create the file as `{}`
   if missing; preserve other keys). Confirm:
   ```
   This project (/home/me/code/app) now uses vault: personal  (~/vaults/personal)
   ```
4. Return the resolved `OBSIDIAN_VAULT_PATH` so the calling skill can continue.

> When another skill reaches step 3 of the Config Resolution Protocol, it runs exactly this quiz. If
> there is **no user present** (headless/cron), it does not quiz; it uses the global `config` fallback
> (see **Default**).

## Set (`/wiki-switch <name>`)

Map the current project to an already-registered vault.

1. Verify `~/.obsidian-wiki/config.<name>` exists. If not, say so and run **List**.
2. Set `projects.json[<project-root>] = <name>` (preserve other keys).
3. Confirm:
   ```
   This project (<project-root>) now uses vault: <name>
   Vault path: <OBSIDIAN_VAULT_PATH from config.<name>>
   ```

## List

1. Find `~/.obsidian-wiki/config.*` (exclude `config`). Read each one's first comment line as description.
2. Read `projects.json` and resolve the current project root's mapping (if any).
3. Display, marking the current project's vault:
   ```
   Registered vaults:
     personal   Personal notes vault   [this project]
     work       Work knowledge base
     research   Research vault

   Headless default (~/.obsidian-wiki/config): personal
   ```
   If the project has no mapping, note that and suggest `/wiki-switch` to set one.

## Where

Explain how the current directory resolves, running the Config Resolution Protocol read-only:

1. Manifest walk-up from CWD: report the vault if found ("inside vault X").
2. Else project map: report the mapping and which ancestor key matched.
3. Else report "would quiz" and list options.
4. Always also show the headless default. This is the diagnostic for "which wiki am I on and why".

## Show

Print a vault's config.

- Name given: read `~/.obsidian-wiki/config.<name>`. No name: read the active global `config`.
- Missing: say so and **List**.
- Print verbatim, but redact any line containing `API_KEY` or `SECRET` (show `***`).

## New

Register a new vault.

1. Check `~/.obsidian-wiki/config.<name>` does not exist. Abort if it does.
2. Ask for the vault's absolute path (`OBSIDIAN_VAULT_PATH`). If an active `config` exists, copy it as a
   template and only ask for the vault-specific fields; otherwise scaffold:
   ```
   # <name> vault
   # --- Vault-specific ---
   OBSIDIAN_VAULT_PATH=<path>
   # --- Vault-independent ---
   LINK_FORMAT=wikilinks
   ```
   Config files group fields with `# --- Section ---` headers: ask for "vault-specific"/"paths" fields,
   keep "vault-independent"/"global"/"shared" as-is, and for "secrets" ask same-or-different.
3. Set the top comment line to a one-line description (shown by **List**/**Quiz**).
4. Write `~/.obsidian-wiki/config.<name>`. Confirm:
   ```
   Registered vault: <name> (<path>)
   Use `/wiki-switch <name>` in a project to target it, then initialize the vault with Part A if it is new.
   ```
   Do not map any project automatically.

## Forget

Remove the current project's mapping: delete the `<project-root>` key from `projects.json` (preserve
others). Confirm, and note the project will be quizzed next time. Does not touch the registry.

## Default

Set the **headless fallback**, the vault used by non-interactive runs (cron, scripts) that cannot quiz.

1. Verify `~/.obsidian-wiki/config.<name>` exists.
2. Re-point the symlink: `ln -sf ~/.obsidian-wiki/config.<name> ~/.obsidian-wiki/config`.
3. Confirm: `Headless default vault is now: <name>`. This does not affect interactive resolution, which
   prefers the manifest walk-up and the project map.
