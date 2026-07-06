# scripts

Python utilities for the wiki. Two of them — `wiki-lint.py` and `wiki-graph.py` —
are the deterministic compute backends for the `wiki-lint` and `wiki-status`
skills; the rest fill gaps no skill covers. **Every script is a PEP 723 `uv`
script — run them all with `uv run` (or `uv run --script`), never a bare
`python3`.** The YAML-parsing ones (`wiki-lint.py`, `wiki-graph.py`,
`validate-frontmatter.py`) pull in `pyyaml` on the fly; the rest declare no
dependencies, so `uv` adds nothing but a consistent interpreter. Direct execution
(`./regen-manifest.py`) also routes through `uv` via the shebang.

They run unchanged on native Windows — `uv` is cross-platform, so the command is
identical; just set env knobs with `$env:VAR=1` (PowerShell) or `set VAR=1` (cmd)
instead of the `VAR=1 cmd` inline form. Each block below shows both.

## When to use these vs the skills

The skills in `../skills/` are the primary surface — ingest, query, lint,
rebuild, etc. Two scripts are the **deterministic backends** those skills call so
the LLM doesn't recompute mechanical things by reading every page:

| Script | Backs | Computes |
|---|---|---|
| `wiki-lint.py` | `wiki-lint` | orphans, broken links, missing/oversized frontmatter & summary, index drift, hardcoded counts, stale pages, lifecycle/supersession integrity, provenance marker ratios, misc-promotion candidates, index privacy leaks |
| `wiki-graph.py` | `wiki-status` (insights) | wikilink graph: hubs, tag cohesion, orphans/orphan-adjacent, bridges (articulation points), cross-category edges, run-to-run delta |
| `wiki-journal.py` | `wiki-ingest` / `wiki-capture` / any log+hot writer | mechanical `log.md` append + `hot.md` Recent-Activity prepend/trim + `updated:` bump. The LLM supplies only the distilled one-line entry; the script owns timestamps, placement, trimming, and template creation. |

The rest cover **specific operations the skills do not implement**:

| Script | Fills this gap |
|---|---|
| `regen-manifest.py` | Rebuild `.manifest.json` from scratch by scanning the filesystem. The skills *read* and *update* the manifest but none of them bootstraps one from an existing populated vault, or repairs one that drifted after a bulk filesystem operation done outside the tooling. |
| `kebab-rename.py` | Mass-rename pages to kebab-case-lowercase, rewriting every wikilink and re-keying the manifest in lockstep. `wiki-lint` reports broken wikilinks but doesn't perform renames. |
| `validate-frontmatter.py` | Verify every page's YAML frontmatter actually *parses*. Catches the unquoted colon-space (`: `) trap that silently breaks Obsidian's Properties panel — `wiki-lint` checks for *missing* summaries/frontmatter but not for syntactically *invalid* YAML. |
| `sync-agents.py` | Regenerate a vault's `AGENTS.md` from its `CLAUDE.md` by inlining the `@`-imports, for agents without an import mechanism (Codex CLI). `wire-vault.sh` / `.ps1` call it per vault; run it directly (or with `--all`) after editing `wiki-conventions.md`. |

If a skill covers what you need, prefer the skill.

## Vault discovery

All scripts pick up the active vault automatically:

1. Walk up from `CWD` looking for `.manifest.json` — the canonical vault marker.
2. Else `OBSIDIAN_VAULT_PATH` if set — backward-compat only.

That matches the Config Resolution Protocol the skills follow (see
`skills/wiki/SKILL.md`). A default vault needs no env var or config file —
`.manifest.json` is all it takes.

## `wiki-lint.py`

```sh
uv run .claude/wiki-scripts/wiki-lint.py              # JSON report (default)
uv run .claude/wiki-scripts/wiki-lint.py --format md  # human-readable report
```

```powershell
uv run .claude\wiki-scripts\wiki-lint.py --format md
```

Runs every mechanical health check in one read-only pass and prints a report:
orphans, broken wikilinks, missing/oversized frontmatter and summaries, index
drift, hardcoded inventory counts, stale pages, lifecycle/supersession integrity,
provenance marker ratios, misc-promotion candidates, and **index privacy leaks**.
Exit `0` when there are no error-level findings, `1` when there are (broken links,
missing required frontmatter, invalid lifecycle/supersession, privacy leaks) — so
it works as a pre-commit / pre-publish gate.

**Index privacy leak** (`index_privacy_leak`): if the vault declares `private_paths`
in `.manifest.json` (e.g. `["me", "context/me"]`), a private content page must only be
listed in an `index.md` inside its own private area. A more-public index (the shareable
root, or another area's index) may reference the area only via a link to its section
`index.md` — never by listing private pages or their summaries. The `missing_from_index`
check is privacy-aware too: a page counts as indexed if *any* index (root or section)
lists it. No `private_paths` → both behave exactly as before. The key survives
`regen-manifest.py`. The `wiki-lint` skill calls this, then adds the judgement-only
checks it can't: contradictions, provenance interpretation, and visibility/PII.
Read-only; never writes. Needs `pyyaml` via the PEP 723 header — nothing to install.

## `wiki-graph.py`

```sh
uv run .claude/wiki-scripts/wiki-graph.py             # JSON (default)
uv run .claude/wiki-scripts/wiki-graph.py --format md # readable summary
```

```powershell
uv run .claude\wiki-scripts\wiki-graph.py --format md
```

Builds the wikilink graph once and reports hubs, tag cohesion, orphans /
orphan-adjacent pages, bridges (real articulation points via iterative Tarjan
DFS), cross-category edges, and the delta since the last run. It does not touch
the vault — its one side effect is a graph snapshot under
`~/.obsidian-wiki/state/<vault-id>/graph-snapshot.json` (outside the vault, keyed
by a hash of the vault path, so copies stay relocatable and get a fresh snapshot),
used to compute the next delta. The `wiki-status` insights mode renders this JSON
into `_insights.md`. Needs `pyyaml`.

## `wiki-journal.py`

```sh
uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/wiki-journal.py" --vault "$OBSIDIAN_VAULT_PATH" \
  --log 'INGEST source="path/to/src" pages_updated=1 pages_created=0 mode=append' \
  --hot-entry '**One-line conceptual change.** Detail with [[wikilinks]].' \
  --hot-trim 3
```

The mechanical half of every skill's "update the journal" step. The LLM composes only
the distilled entry text; the script appends the timestamped `log.md` line, prepends the
`hot.md` **Recent Activity** bullet, trims to the newest N, bumps `updated:`, and creates
`hot.md` from template if missing. Flags: `--log` and `--hot-entry` are independent (pass
either or both); `--hot-trim N` bounds Recent Activity (only a top-level `## ` heading ends
the section, so a `## Tooling …` subsection below survives); `--date-only` for a date-only
log stamp; `--ts` / `--date` to override the clock. **Semantic sections (Key Takeaways,
Active Threads, Flagged Contradictions) are deliberately untouched** — edit those by hand.
Stdlib only; no `pyyaml`.

## `regen-manifest.py`

```sh
cd /path/to/vault          # or set OBSIDIAN_VAULT_PATH
uv run .claude/wiki-scripts/regen-manifest.py  # or: DRY_RUN=1 uv run .claude/wiki-scripts/regen-manifest.py
```

```powershell
# Windows / PowerShell
cd C:\path\to\vault
uv run .claude\wiki-scripts\regen-manifest.py
$env:DRY_RUN=1; uv run .claude\wiki-scripts\regen-manifest.py; Remove-Item Env:DRY_RUN   # preview, then clear
```

Scans every content `.md` (skipping dotdirs and the `index.md` / `log.md` /
`CLAUDE.md` / `AGENTS.md` scaffolding). For each:

- New file → manifest entry with `ingested_at` set to now.
- Existing file → preserves `ingested_at`, updates `size_bytes` / `mtime`.
- Missing file → removed from manifest.

Prints added / removed / modified / unchanged counts.

Idempotent. Running it twice produces no second-pass changes other than the
top-level `updated` timestamp.

## `kebab-rename.py`

```sh
cd /path/to/vault
DRY_RUN=1 uv run .claude/wiki-scripts/kebab-rename.py   # always preview first
APPLY=1   uv run .claude/wiki-scripts/kebab-rename.py
```

```powershell
# Windows / PowerShell — env vars persist for the session, so CLEAR them between
# runs or a stale APPLY=1 will fire on your next invocation.
cd C:\path\to\vault
$env:DRY_RUN=1; uv run .claude\wiki-scripts\kebab-rename.py; Remove-Item Env:DRY_RUN   # always preview first
$env:APPLY=1;   uv run .claude\wiki-scripts\kebab-rename.py; Remove-Item Env:APPLY
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

```powershell
# Windows — same command (uv is cross-platform); the ./script.py shebang form is POSIX-only.
uv run .claude\wiki-scripts\validate-frontmatter.py
```

Walks every content `.md`, extracts the `---` … `---` block, and parses it with
a real YAML parser. Reports two problem classes:

- **INVALID** — frontmatter present but unparseable. Almost always an unquoted
  colon-space (e.g. `title: Speculor: A Platform`) or another YAML
  metacharacter leading a value. This is the one that makes Obsidian silently
  drop the whole Properties panel.
- **MISSING** — a real page with no frontmatter. Scaffolding/meta files
  (`index.md`, `log.md`, `hot.md`, `CLAUDE.md`, `AGENTS.md`, any `README.md`)
  are allow-listed and never flagged.

Exit `0` when clean, `1` when anything is wrong — so it works as a pre-commit /
pre-publish gate. Read-only; never writes. Run it after any bulk frontmatter
edit or ingest. Fix per the colon-space rule in the vault `CLAUDE.md`:
**rewrite to drop the colon (preferred), else double-quote the value.**

Unlike the stdlib scripts this one needs `pyyaml`; the PEP 723 header makes
`uv run` provide it automatically, so there's nothing to install.

## `sync-agents.py`

```sh
uv run .claude/wiki-scripts/sync-agents.py           # sync the vault you're in
uv run /path/to/repo/scripts/sync-agents.py --all    # sync every registered vault
uv run .claude/wiki-scripts/sync-agents.py --check   # report drift, change nothing
```

```powershell
uv run .claude\wiki-scripts\sync-agents.py
```

Rebuilds the vault's `AGENTS.md` from `CLAUDE.md` with every Claude-style
`@path` import physically inlined (recursion capped at 4, like Claude Code).
Claude Code resolves those imports live, but Codex CLI has no import mechanism —
it needs the conventions *inside* AGENTS.md. The output carries a
`GENERATED FILE - DO NOT EDIT` banner; `CLAUDE.md` stays the hand-edited master.

`--all` iterates every vault registered in `~/.obsidian-wiki` (`config.*` files) —
use it after editing `wiki-conventions.md` so no vault's AGENTS.md goes stale.
Writes only when content actually changed (no cloud-sync churn); `--check`
exits `1` on drift, so it composes with `wire-vault.sh --check`. Stdlib-only.
