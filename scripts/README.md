# scripts

Two small Python utilities that fill gaps no skill covers. Stdlib only, no
dependencies.

## When to use these vs the skills

The 14 skills in `../skills/` are the primary surface — ingest, query, lint,
rebuild, etc. These scripts cover **two specific operations the skills do
not implement**:

| Script | Fills this gap |
|---|---|
| `regen-manifest.py` | Rebuild `.manifest.json` from scratch by scanning the filesystem. The skills *read* and *update* the manifest but none of them bootstraps one from an existing populated vault, or repairs one that drifted after a bulk filesystem operation done outside the tooling. |
| `kebab-rename.py` | Mass-rename pages to kebab-case-lowercase, rewriting every wikilink and re-keying the manifest in lockstep. `wiki-lint` reports broken wikilinks but doesn't perform renames. |

If a skill covers what you need, prefer the skill.

## Vault discovery

Both scripts pick up the active vault automatically:

1. `OBSIDIAN_VAULT_PATH` environment variable if set, else
2. Walk up from `CWD` looking for a `.env` with `OBSIDIAN_VAULT_PATH=...`

That matches the Config Resolution Protocol the skills follow (see
`skills/llm-wiki/SKILL.md`).

## `regen-manifest.py`

```sh
cd /path/to/vault          # or set OBSIDIAN_VAULT_PATH
python3 regen-manifest.py  # or: DRY_RUN=1 python3 regen-manifest.py
```

Scans every content `.md` (skipping dotdirs and the `index.md` / `log.md`
scaffolding). For each:

- New file → manifest entry with `ingested_at` set to now.
- Existing file → preserves `ingested_at`, updates `size_bytes` / `mtime`.
- Missing file → removed from manifest.

Prints added / removed / modified / unchanged counts.

Idempotent. Running it twice produces no second-pass changes other than the
top-level `updated` timestamp.

## `kebab-rename.py`

```sh
cd /path/to/vault
DRY_RUN=1 python3 kebab-rename.py   # always preview first
APPLY=1   python3 kebab-rename.py
```

Refuses to run without exactly one of `DRY_RUN=1` or `APPLY=1`.

Performs three coordinated actions:

1. Renames `.md` files to kebab-case-lowercase.
2. Rewrites every `[[wikilink]]` across the vault to match the new paths.
3. Re-keys `.manifest.json` so `ingested_at` survives the rename.

Knobs at the top of the file (all empty by default — edit before running):

- `FOLDER_RENAMES` — explicit folder-rename map, e.g.
  `{"Notes/OldFolderName": "Notes/new-folder-name"}`.
- `BRAND_PRESERVATIONS` — compound names to NOT split on internal
  capitalization. Example: a brand like `FooBar` would split to
  `foo-bar` without an entry; adding `{"FooBar": "foobar"}` keeps it
  as one word.
- `PATH_OVERRIDES` — manual override for pages where slugify produces a
  bad result (typically because the source filename had already lost a
  word boundary).
- `LEGACY_WIKILINK_TARGETS` — old paths that should still resolve to a
  new canonical path. Use this for dangling-link recovery when files
  were renamed outside this tool.

### NTFS case-insensitivity

`mv Foo.md foo.md` is a silent no-op on NTFS / case-insensitive macOS.
`kebab-rename.py` detects case-only renames and routes via a `_tmp_`
intermediate. If you write a new rename script, replicate this pattern.
