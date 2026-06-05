# Vault Mechanics — Reference

Detail that the keystone (`wiki/SKILL.md`) points to but doesn't need in the hot path. Read this only when you actually need to resolve a vault, relocate one, snapshot a URL source, or rename a category — not on every operation.

## Config Resolution Protocol

The vault is self-describing — **no config file or per-vault settings are needed**. The vault is the directory containing `.manifest.json`; every other path derives from that location.

### Vault discovery

1. **Walk up from CWD** — look for `.manifest.json`, stopping at the first match (up to `$HOME` or `/`).
2. **Global config** — if no vault found and `~/.obsidian-wiki/config` exists, read `VAULT` from it.
3. **Prompt setup** — if neither, tell the user: "No vault found. Run `wiki-setup` to initialize."

```bash
find_vault() {
  dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    [[ -f "$dir/.manifest.json" ]] && { echo "$dir"; return; }
    [[ "$dir" == "$HOME" ]] && break
    dir="$(dirname "$dir")"
  done
  [[ -f "$HOME/.obsidian-wiki/config" ]] && grep -m1 '^VAULT=' "$HOME/.obsidian-wiki/config" | cut -d= -f2-
}
```

The maintenance scripts (`wiki-lint.py`, `wiki-graph.py`, `validate-frontmatter.py`, …) implement this same walk-up internally, so you can run them from anywhere inside the vault.

### Paths derived from the vault location

Everything derives from the vault root — there is no config file:

| Setting | Value |
|---|---|
| Vault root | directory containing `.manifest.json` |
| Sources dir | `$OBSIDIAN_VAULT_PATH/_sources` |
| Archives dir | `$OBSIDIAN_VAULT_PATH/_archives` |
| Link format | wikilinks (vault-relative) |
| Claude history | `$HOME/.claude/projects` if it exists |

Skills MUST infer every path from the vault location. A vault with no config of any kind is the only supported case — that's what keeps it relocatable. Skills refer to the resolved vault root as `$OBSIDIAN_VAULT_PATH` in their examples; that's just the variable set from `find_vault`, not a value read from the environment. No API keys are needed — the agent already has LLM access.

### Vault-scoped state

Skills (and scripts) writing runtime state outside the vault must scope it by vault location, not a global path:

```bash
VAULT_ID=$(echo "$VAULT" | md5sum 2>/dev/null | cut -c1-8)
STATE_DIR="$HOME/.obsidian-wiki/state/$VAULT_ID"
```

The vault path is the input to the hash — copying the vault elsewhere produces a new scope, which is the desired behavior (the new vault is a different instance). `wiki-graph.py` uses exactly this for its graph snapshot.

### Standard "Before You Start" block

Every skill's setup section should read:

> **Resolve vault** — walk up from CWD for `.manifest.json` (per the Config Resolution Protocol in `wiki/SKILL.md`). All paths derive from the vault root.

## Relocatability Invariant

The vault is the unit of relocation. A vault must satisfy this invariant:

> **Copy-paste works.** `cp -r <vault> <new-location> && cd <new-location>` must produce a fully functional wiki without editing any file.

This rules out:

- Absolute paths inside the vault pointing back to itself
- Manifest entries keyed by absolute paths (relative paths only)
- Symlinks pointing to absolute paths inside the vault

The skills and scripts follow this. If you find one that violates it, that's a bug.

## URL Sources

`sources:` is a YAML list of strings. Each entry is either a vault-relative path or a full URL (leading `http://` / `https://` is the discriminator). Mix freely:

```yaml
sources:
  - _sources/web/martinfowler-microservices-2014.md   # local snapshot
  - https://martinfowler.com/articles/microservices.html   # original URL
  - _sources/papers/attention-is-all-you-need.pdf   # file source
  - https://example.com/see-also   # URL-only, no snapshot
```

**Recommended:** snapshot + URL (two entries) for any URL that is **evidence** for a non-trivial claim. Snapshot first (what `wiki-lint` verifies), URL second (what a reader clicks).

**URL-only** (one entry) is acceptable only for ephemera — "see also" pointers whose removal would not weaken any claim on the page.

Snapshot conventions:

- Path: `_sources/web/<slug>.md`
- Slug: kebab-case, derived from `<domain>-<title-or-slug>-<year>`, e.g. `martinfowler-microservices-2014.md`, `instructables-carbon-quantum-dots-2019.md`
- Format: Markdown preferred (clean grep target). HTML alongside (`<slug>.html`) only when conversion loses important structure. PDFs unchanged.
- Manifest entry keyed by the snapshot path, with `source_type: "url"`, `source_url:`, `fetched_at:`, `content_hash:`.

`wiki-lint` flags URL-only `sources:` entries that 404 and downgrades dependent claims to `^[ambiguous]` until a snapshot is added.

## Renaming a Category

1. Run `.claude/wiki-scripts/kebab-rename.py` (or a folder-only variant) — it renames the folder, rewrites every wikilink that referenced the old path, and re-keys the manifest in lockstep. Use `DRY_RUN=1` first.
2. Update the section heading in `index.md`.
3. Append a `RECATEGORIZE` entry to `log.md`.

To **add** a category: `mkdir <name>` at the vault root. No config edit needed — skills discover it on next read. To **remove** a category: move its pages elsewhere first, then `rmdir`. To **hide a top-level directory from category discovery** (e.g. a scratch area you don't want ingest to write into), rename it with a `_` prefix.
