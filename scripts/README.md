# scripts

Small Python utilities that fill gaps no skill covers. Most are stdlib-only;
`validate-frontmatter.py` is a `uv` script that pulls in `pyyaml` on the fly
(PEP 723 inline metadata — `uv run` handles it, no manual install).

## When to use these vs the skills

The skills in `../skills/` are the primary surface — ingest, query, lint,
rebuild, etc. These scripts cover **specific operations the skills do
not implement**:

| Script | Fills this gap |
|---|---|
| `regen-manifest.py` | Rebuild `.manifest.json` from scratch by scanning the filesystem. The skills *read* and *update* the manifest but none of them bootstraps one from an existing populated vault, or repairs one that drifted after a bulk filesystem operation done outside the tooling. |
| `kebab-rename.py` | Mass-rename pages to kebab-case-lowercase, rewriting every wikilink and re-keying the manifest in lockstep. `wiki-lint` reports broken wikilinks but doesn't perform renames. |
| `validate-frontmatter.py` | Verify every page's YAML frontmatter actually *parses*. Catches the unquoted colon-space (`: `) trap that silently breaks Obsidian's Properties panel — `wiki-lint` checks for *missing* summaries/frontmatter but not for syntactically *invalid* YAML. |

If a skill covers what you need, prefer the skill.

## Vault discovery

All scripts pick up the active vault automatically:

1. Walk up from `CWD` looking for `.manifest.json` — the canonical vault marker.
2. Else `OBSIDIAN_VAULT_PATH` if set — backward-compat only.

That matches the Config Resolution Protocol the skills follow (see
`skills/wiki/SKILL.md`). A default vault needs no env var or config file —
`.manifest.json` is all it takes.

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

## `validate-frontmatter.py`

```sh
uv run .claude/wiki-scripts/validate-frontmatter.py   # from anywhere in the vault
```

Walks every content `.md`, extracts the `---` … `---` block, and parses it with
a real YAML parser. Reports two problem classes:

- **INVALID** — frontmatter present but unparseable. Almost always an unquoted
  colon-space (e.g. `title: Speculor: A Platform`) or another YAML
  metacharacter leading a value. This is the one that makes Obsidian silently
  drop the whole Properties panel.
- **MISSING** — a real page with no frontmatter. Scaffolding/meta files
  (`index.md`, `log.md`, `hot.md`, `CLAUDE.md`, any `README.md`) are
  allow-listed and never flagged.

Exit `0` when clean, `1` when anything is wrong — so it works as a pre-commit /
pre-publish gate. Read-only; never writes. Run it after any bulk frontmatter
edit or ingest. Fix per the colon-space rule in the vault `CLAUDE.md`:
**rewrite to drop the colon (preferred), else double-quote the value.**

Unlike the stdlib scripts this one needs `pyyaml`; the PEP 723 header makes
`uv run` provide it automatically, so there's nothing to install.
