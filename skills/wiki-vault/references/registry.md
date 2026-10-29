# Vault Registry — Quiz and /wiki-switch

Files: `~/.obsidian-wiki/config.<name>` (one per registered vault: a `# description` line plus
`OBSIDIAN_VAULT_PATH=`), `~/.obsidian-wiki/projects.json` (`{ "project-path": "vault-name" }`), and the
`~/.obsidian-wiki/config` symlink (headless default). Project root = nearest ancestor of CWD with `.git`,
else CWD. Nothing here ever edits a vault.

| Invocation | Action |
|---|---|
| `/wiki-switch` | **Quiz** (always asks, even if mapped) |
| `/wiki-switch <name>` | Map this project to `<name>` (verify `config.<name>` exists, else List) |
| `/wiki-switch list` | List (see SKILL.md) |
| `/wiki-switch new <name>` | Register (see SKILL.md); do not map any project automatically |
| `/wiki-switch where` | **Where** |
| `/wiki-switch show [name]` | Print `config.<name>` (no name: the active `config`); redact lines with `API_KEY` or `SECRET` |
| `/wiki-switch forget` | Delete this project's key from `projects.json`; it will be quizzed next time |
| `/wiki-switch default <name>` | `ln -sf ~/.obsidian-wiki/config.<name> ~/.obsidian-wiki/config` |

## Quiz

Step 3 of the Config Resolution Protocol (`wiki/SKILL.md`): no marker above CWD and no project mapping.

1. List `config.*` with their descriptions, numbered, marking the current mapping. None registered: tell
   the user to set up a vault (`wiki-vault`) or register one.
2. On the choice, persist `projects.json[<project root>] = <name>` and confirm
   `This project (<root>) now uses vault: <name> (<path>)`.
3. Return the vault path so the calling skill continues.

Headless runs (cron, scripts) never quiz; they use the `config` symlink.

## Where

Run the resolution read-only and say which step matched: marker walk-up ("inside vault X"), else the
`projects.json` key that matched, else "would quiz" with the options. Always show the headless default.
