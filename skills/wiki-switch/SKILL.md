---
name: wiki-switch
description: >
  Choose which Obsidian wiki vault a project targets, and manage the vault registry. Use this skill when
  the user says "/wiki-switch", "/wiki-switch NAME", "switch to my work wiki", "switch vault", "change wiki",
  "which wiki am I on", "list my wikis", "show my vaults", "create a new vault config", "add a new wiki profile",
  or when any wiki skill is run outside a vault and outside a known project and must ask which vault to use.
  Vaults are registered as config files at ~/.obsidian-wiki/config.NAME. A per-project choice is stored in
  ~/.obsidian-wiki/projects.json so a project keeps targeting the same vault without re-asking.
---

# Wiki Switch — Choose a Vault per Project

Each vault is registered as a config file `~/.obsidian-wiki/config.<name>` holding its
`OBSIDIAN_VAULT_PATH`. **Which vault a given project uses** is recorded in the project map
`~/.obsidian-wiki/projects.json` (`{ "project-path": "vault-name" }`). This skill manages both,
and runs the **quiz** that other skills fall back to when they can resolve no vault.

This is the layer above the [Config Resolution Protocol](../wiki/SKILL.md) (manifest walk-up →
project map → quiz → headless fallback). `wiki-switch` never edits a vault; it only touches files
under `~/.obsidian-wiki/`.

**Project root** = the nearest ancestor of CWD containing `.git`, else CWD itself. Use its absolute
path as the `projects.json` key. (A directory already inside a vault is resolved by manifest walk-up
and never reaches this skill.)

## Dispatch

| Invocation | Action |
|---|---|
| `/wiki-switch` (no args) | → **Quiz** (always ask, even if a mapping exists) |
| `/wiki-switch <name>` | → **Set** this project's vault to `<name>` |
| `/wiki-switch list` | → **List** registered vaults + current project's mapping |
| `/wiki-switch where` | → **Where** (show how CWD resolves and why) |
| `/wiki-switch show [name]` | → **Show** a config file |
| `/wiki-switch new <name>` | → **New** (register a vault) |
| `/wiki-switch forget` | → **Forget** this project's mapping |
| `/wiki-switch default <name>` | → **Default** (set the headless global fallback) |

---

## Quiz (no args, and the fallback other skills invoke)

Ask the user which registered vault this project should use, then remember it.

1. List registry entries `~/.obsidian-wiki/config.*` (exclude the `config` symlink). For each, read the
   first non-empty comment line as its description. If none exist, tell the user to run `/wiki-switch new <name>`
   or `wiki-setup` first.
2. Present them as a numbered pick-list with descriptions, marking the project's current mapping (if any):
   ```
   Which vault for this project (/home/me/code/app)?
     1. personal   Personal vault (me/ and context/ namespaces)   ← current
     2. em         em-planning vault
     3. strata     Strata vault (Fairwind / BCS 1972)
   ```
3. On the user's choice, **persist** it: set `projects.json[<project-root>] = <name>` (create the file as
   `{}` if missing; preserve other keys). Confirm:
   ```
   This project (/home/me/code/app) now uses vault: personal  (/mnt/.../ObsidianVault)
   ```
4. Return the resolved `OBSIDIAN_VAULT_PATH` so the calling skill can continue.

> When another skill reaches step 3 of the Config Resolution Protocol, it runs exactly this quiz. If there
> is **no user present** (headless/cron), it does not quiz — it uses the global `config` fallback (see **Default**).

---

## Set (`/wiki-switch <name>`)

Map the current project to an already-registered vault.

1. Verify `~/.obsidian-wiki/config.<name>` exists. If not, say so and run **List**.
2. Set `projects.json[<project-root>] = <name>` (preserve other keys).
3. Confirm:
   ```
   This project (<project-root>) now uses vault: <name>
   Vault path: <OBSIDIAN_VAULT_PATH from config.<name>>
   ```

---

## List

1. Find `~/.obsidian-wiki/config.*` (exclude `config`). Read each one's first comment line as description.
2. Read `projects.json` and resolve the current project root's mapping (if any).
3. Display, marking the current project's vault:
   ```
   Registered vaults:
     personal   Personal vault (me/ and context/ namespaces)   ← this project
     em         em-planning vault
     strata     Strata vault (Fairwind / BCS 1972)

   Headless default (~/.obsidian-wiki/config): personal
   ```
   If the project has no mapping, note that and suggest `/wiki-switch` to set one.

---

## Where

Explain how the current directory resolves, by running the Config Resolution Protocol read-only:

1. Manifest walk-up from CWD — report the vault if found ("inside vault X").
2. Else project map — report the mapping and which ancestor key matched.
3. Else report "would quiz" and list options.
4. Always also show the headless default. This is the diagnostic for "which wiki am I on and why".

---

## Show

Print a vault's config.

- Name given → read `~/.obsidian-wiki/config.<name>`. No name → read the active global `config`.
- Missing → say so and **List**.
- Print verbatim, but redact any line containing `API_KEY` or `SECRET` (show `***`).

---

## New

Register a new vault.

1. Check `~/.obsidian-wiki/config.<name>` does not exist. Abort if it does.
2. Ask the user for the vault's absolute path (`OBSIDIAN_VAULT_PATH`). If an active `config` exists, copy it as
   a template and only ask for the vault-specific fields; otherwise scaffold:
   ```
   # <name> vault
   # --- Vault-specific ---
   OBSIDIAN_VAULT_PATH=<path>
   # --- Vault-independent ---
   LINK_FORMAT=wikilinks
   ```
   Config files group fields with `# --- Section ---` headers: ask for "vault-specific"/"paths" fields, keep
   "vault-independent"/"global"/"shared" as-is, and for "secrets" ask same-or-different.
3. Set the top comment line to a one-line description (shown by **List**/**Quiz**).
4. Write `~/.obsidian-wiki/config.<name>`. Confirm:
   ```
   Registered vault: <name> (<path>)
   Use `/wiki-switch <name>` in a project to target it, then run `wiki-setup` if the vault is new.
   ```
   Do not map any project automatically.

---

## Forget

Remove the current project's mapping: delete the `<project-root>` key from `projects.json` (preserve others).
Confirm, and note the project will be quizzed next time. Does not touch the registry.

---

## Default

Set the **headless fallback** — the vault used by non-interactive runs (cron, scripts) that cannot quiz.

1. Verify `~/.obsidian-wiki/config.<name>` exists.
2. Re-point the symlink: `ln -sf ~/.obsidian-wiki/config.<name> ~/.obsidian-wiki/config`.
3. Confirm: `Headless default vault is now: <name>`. This does not affect interactive resolution, which
   prefers the manifest walk-up and the project map.
