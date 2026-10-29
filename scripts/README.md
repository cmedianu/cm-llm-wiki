# scripts

Python utilities for the wiki. Two of them — `wiki-lint.py` and `wiki-graph.py` —
are the deterministic compute backends for the `wiki-lint` skill (health, status and
insights modes); the rest fill gaps no skill covers. **Every script is a PEP 723 `uv`
script — run them all with `uv run` (or `uv run --script`), never a bare
`python3`.** The YAML-parsing ones (`wiki-lint.py`, `wiki-graph.py`,
`ingest-prep.py`) pull in `pyyaml` on the fly; the rest declare no
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
| `wiki-lint.py` | `wiki-lint` | orphans, broken links, missing/oversized frontmatter & summary, index drift, stale reviewed pages, lifecycle/supersession integrity, provenance marker ratios, misc-promotion candidates, index privacy leaks, non-date-only date fields |
| `wiki-graph.py` | `wiki-lint` (insights mode) | wikilink graph: hubs, tag cohesion, orphans/orphan-adjacent, bridges (articulation points), cross-category edges, run-to-run delta |
| `wiki-journal.py` | `wiki-ingest` / `wiki-capture` / any log+hot writer | mechanical `log.md` append + `hot.md` Recent-Activity prepend/trim + `updated:` bump. The LLM supplies only the distilled one-line entry; the script owns timestamps, placement, trimming, and template creation. |

The rest cover **specific operations the skills do not implement**:

| Script | Fills this gap |
|---|---|
| `ingest-prep.py` | One read-only call that gathers everything an ingest needs before distilling a source: categories, `private_paths`, whether the source is already tracked, which category indexes are base-backed (live queries needing no manual edit), and keyword-related pages — replacing 4–5 ad-hoc grep/shell round-trips. A backlinks mode finds link candidates for pages you just wrote. |
| `regen-manifest.py` | Create or repair `.manifest.json`, the vault marker plus vault config (`private_paths`). It no longer tracks pages; this strips legacy per-page entries from an old manifest. |
| `kebab-rename.py` | Mass-rename pages to kebab-case-lowercase, rewriting every wikilink (and re-keying a legacy manifest's page entries, if any). `wiki-lint` reports broken wikilinks but doesn't perform renames. |
| `wiki-new.py` | Scaffold a page: kebab name and folder checked, date-only frontmatter, summary length checked, optional `--supersedes` wiring on the previous dated snapshot. Replaces hand-written `cat > page.md` frontmatter that failed at commit time. |
| `claude-history.py` | Search and summarize Claude Code transcripts for a vault: `search TERM…` finds the session about something (with its id to resume), `sessions` lists them, `stats` shows skills used, scripts run with median/total seconds, commits, `--no-verify` and gate failures. |
| `wiki-commit.py` | Land a session's changes as grouped Conventional Commits from a short plan (message line, indented paths): stages by name, never `-A`; journal/manifest ride whole in the last group (optionally writing the journal line first); each commit gated; leftovers surfaced, not swept. |
| `wiki-mv.py` | Rename or move one page and repoint every wikilink to it (aliases, headings, block refs, embeds, table pipes kept; code skipped; CRLF/BOM kept), update `category:` and re-key the manifest. Dry run by default, `--apply` to write. |
| `stamp-staged.py` | Run by the vault pre-commit hook: sets `updated:` to today on staged pages whose content changed, so pages edited from a shell (which the PostToolUse hook never sees) are stamped too. |
| `validate-frontmatter.py` | Compatibility alias for `wiki-lint.py --only invalid_frontmatter,missing_frontmatter --errors-only`: the strict parse (unquoted colon-space, duplicate keys) now lives in `wiki-lint.py`. |
| `sync-agents.py` | Regenerate a vault's `AGENTS.md` from its `CLAUDE.md` by inlining the `@`-imports, for agents without an import mechanism (Codex CLI). `wire-vault.sh` / `.ps1` call it per vault; run it directly (or with `--all`) after editing `wiki-conventions.md`. |

If a skill covers what you need, prefer the skill.

`uv run tests/selftest.py` checks every script's contract against throwaway fixture
vaults (CRLF/BOM, the staged gate, stamping, wiki-new, wiki-mv, wiki-commit, journal caps,
the hook) in about 20 seconds.

## Vault discovery

**Every script accepts `--vault <path>`** as an explicit override, and every
script resolves the vault the same way when it is omitted. The resolution chain,
in priority order:

1. `--vault <path>` — explicit override (must be an existing directory). Wins over
   everything else, including any positional vault arg and env vars.
2. Walk up from `CWD` to the first dir containing `.manifest.json` — the canonical
   vault marker. The walk stops at `$HOME` or `/`.
3. Map `CWD` (or its nearest ancestor) via `~/.obsidian-wiki/projects.json`
   (`{"project-path": "vault-name"}`) to a vault name, then read
   `OBSIDIAN_VAULT_PATH` from `~/.obsidian-wiki/config.<vault-name>`.
4. `OBSIDIAN_VAULT_PATH` env var — backward-compat only.

If none apply the script exits with a consistent message telling you to pass
`--vault`. This matches the Config Resolution Protocol the skills follow (see
`skills/wiki/SKILL.md`). A default vault needs no env var — `.manifest.json`, a
`projects.json` entry, or an explicit `--vault` is all it takes.

Because each script is a standalone PEP 723 `uv` script (they never import one
another), the resolver is *replicated verbatim* in each file rather than shared
through a module, and so is `is_content_page()` (the page rule in
`wiki-conventions.md`): keep the copies in sync when changing either. `regen-manifest.py`
additionally honours its legacy `REGEN_AT` bootstrap env var (between steps 3 and
4), so a brand-new vault with no `.manifest.json` yet can still be seeded.

## `ingest-prep.py`

```sh
# Prep mode — one JSON object with everything the ingest needs up front
uv run .claude/wiki-scripts/ingest-prep.py \
  --vault "$OBSIDIAN_VAULT_PATH" \
  --source ~/Downloads/some-source.md \
  --keywords "ssh,yubikey,1password"

# Backlinks mode — link candidates for pages you just wrote
uv run .claude/wiki-scripts/ingest-prep.py \
  --vault "$OBSIDIAN_VAULT_PATH" \
  --backlinks-for "sysadmin/page-a.md,sysadmin/page-b.md"

# Sources mode — what changed in a source archive since the last log entry
uv run .claude/wiki-scripts/ingest-prep.py --sources-dir _mail-archive/threads \
  --ocr-cache _mail-archive/ocr [--since 2026-10-23] [--limit 50] [--fresh-folders-only]
```

```powershell
uv run .claude\wiki-scripts\ingest-prep.py --vault $env:OBSIDIAN_VAULT_PATH --source C:\path\src.md --keywords "ssh,yubikey"
```

A read-only, single-call prep tool that replaces the pile of grep/`ls`/`cat`
round-trips a skill otherwise runs at the start of an ingest. Emits JSON to
stdout; `--vault` follows the standard resolution chain when omitted. Exactly one
of `--source` (prep mode) or `--backlinks-for` (backlinks mode) is required.

**Prep mode** (`--source <file>`, optional `--keywords "k1,k2"`) returns one object:

- `vault` — resolved vault path; `source` — the source path as given.
- `categories` — top-level category dirs (skips `_*` and `.*`).
- `private_paths` — from `.manifest.json` (empty list if absent).
- `source_status` — has this source been ingested? Decided from the vault, not the
  manifest: an external source with a `_sources/<basename>` snapshot is byte-compared
  (`unchanged` / `modified`); otherwise a page whose `sources:` frontmatter names it
  means `unchanged` (or `modified` when the file is newer than that page's `updated:`);
  a page with the same filename stem means `modified` (merge, don't duplicate); else
  `new`. `source_key` names the snapshot or page that settled it. `manifest_status` /
  `manifest_key` are kept as aliases for older skill text.
- `snapshot` — vault-relative `_sources/<basename>` when that snapshot exists on
  disk, else `null`.
- `index_status` — `folder → base_backed | hybrid | manual` for every top-level
  category and nested folder with an `index.md`. `base_backed`: the index embeds a
  ` ```base ` live query, so a new page needs no index edit. `hybrid`: a base plus a
  hand list of the same pages (also needs no edit; `index_hand_listed` names the hand
  entries to migrate). `manual`: hand-curated or missing, add the entry yourself.
  `index_base_backed` (top-level, `true` for base_backed and hybrid) stays for
  compatibility.
- Sources mode returns `{since, total_new, shown, files: [{path, modified, size,
  text_from, excerpt, needs_ocr?}]}`, newest first. `since` defaults to the newest
  `log.md` entry. PDF text comes from the vault's OCR cache when `--ocr-cache` names one,
  else `pdftotext` (first 3 pages, cached under `~/.cache/cm-llm-wiki`); a PDF with no
  text is marked `needs_ocr`. A full scan of a 6,000-file archive on OneDrive takes about
  a minute; `--fresh-folders-only` skips top-level folders older than the cut-off (about
  10 s) but misses files rewritten in place, such as a thread gaining a reply.
- `related_pages` — only when `--keywords` is given. Pages matching any keyword
  (case-insensitive) in title, tags, summary, filename, or body, as
  `[{path, summary}]`, strongest-first (a frontmatter/title/filename hit outranks
  a body-only hit), capped at ~20.

**Backlinks mode** (`--backlinks-for "a.md,b.md"`, vault-relative pages) returns
`[{page, candidate, matched_term}]`: for each listed page, the OTHER content pages
whose body mentions a *distinctive* term from the page's title or filename stem
(stopwords and words < 4 chars are dropped) but that contain no `[[…]]` wikilink
back to it — i.e. missing-backlink candidates. `index.md` / `log.md` / `hot.md`
and anything under `_*` dirs are excluded. "Distinctive" is enforced with a
document-frequency cap (a term appearing in > 15% of pages, e.g. `agent` or
`windows`, is treated as generic and skipped) so the output stays focused instead
of flagging half the vault — this DF guard is an addition beyond a pure
stopword/length filter, made so the tool returns usable candidates.

Read-only; never writes. Needs `pyyaml` via the PEP 723 header.

## `wiki-lint.py`

```sh
uv run .claude/wiki-scripts/wiki-lint.py --summary          # one line per check: start here
uv run .claude/wiki-scripts/wiki-lint.py --only broken_link --format md   # one check's findings
uv run .claude/wiki-scripts/wiki-lint.py --staged --errors-only  # the pre-commit gate
uv run .claude/wiki-scripts/wiki-lint.py                    # full JSON report (default)
uv run .claude/wiki-scripts/wiki-lint.py --fix              # complete unambiguous link paths
uv run .claude/wiki-scripts/wiki-lint.py --fix-snapshots    # wire dated-snapshot supersession
uv run .claude/wiki-scripts/wiki-lint.py --vault "$OBSIDIAN_VAULT_PATH" \
  --pages "sysadmin/page-a.md" "sysadmin/home-network/*.md"  # scope the report
```

```powershell
uv run .claude\wiki-scripts\wiki-lint.py --summary
```

Runs every mechanical health check in one pass: orphans, broken wikilinks, missing,
invalid (unparseable, duplicate keys) or oversized frontmatter and summaries, index
drift, stale `lifecycle: reviewed` pages, unwired dated snapshots, lifecycle and
supersession integrity, provenance marker ratios, misc-promotion candidates, **index
privacy leaks**, and date fields that aren't date-only `yyyy-MM-dd`. Exit `0` when
there are no error-level findings, `1` when there are.

It walks the vault once (dot- and `_`-dirs pruned), reads each page once and resolves
links in memory, case-insensitively as Obsidian does: about 3 s for 450 pages on a
OneDrive mount. Wikilinks inside fenced or inline code are ignored; `templates/` and
root daily notes are not pages.

**`--staged`** reports only on `.md` files staged in git, plus links elsewhere broken
by a staged deletion or rename. With `--errors-only` it reads only the staged pages,
which is what the pre-commit hook runs (about a second). **`--only key[,key]`** keeps
one or more check keys; **`--summary`** prints one line per check with a count and
example locations. **`--errors-only`** drops warnings entirely (not shown, not
counted; exit code unchanged).

**`--fix`** completes a broken (or index bare-basename) wikilink whose basename matches
exactly one file to its full vault-relative path (alias and `#heading` kept).
**`--fix-snapshots`** gives each older member of a dated snapshot family (for example
`position-review-<date>`) `superseded_by`, `lifecycle: archived` and
`lifecycle_changed`; families named as event series (meetings, minutes, standups,
agendas) are never treated as snapshots. Both print one line per fix, run before the
checks, leave anything ambiguous alone, and refuse to combine with `--errors-only` or
`--staged`. A page that is not valid UTF-8 is skipped with a message.

A page can suppress a specific **warning**-level check with a `lint_ignore:`
frontmatter list (e.g. `lint_ignore: [stale_snapshot]`). Errors are never
suppressible, and a listed key that isn't a known check key is flagged
(`lint_ignore_unknown`) so a typo can't silently suppress nothing.

**Index privacy leak** (`index_privacy_leak`): if the vault declares `private_paths`
in `.manifest.json` (e.g. `["me", "context/me"]`), a private content page must only be
listed in an `index.md` inside its own private area. A more-public index (the shareable
root, or another area's index) may reference the area only via a link to its section
`index.md` — never by listing private pages or their summaries. The `missing_from_index`
check is privacy-aware too: a page counts as indexed if *any* index (root or section)
lists it. No `private_paths` → both behave exactly as before. The key survives
`regen-manifest.py`. The `wiki-lint` skill calls this, then adds the judgement-only
checks it can't: contradictions, provenance interpretation, and visibility/PII.
Read-only unless `--fix` or `--fix-snapshots` is given. Needs `pyyaml` via the PEP 723 header — nothing to install.

**`--pages <path|glob> …`** scopes the *report* to the given vault-relative pages
(literal paths or globs). Per-page checks (frontmatter, summary, broken outgoing
links, etc.) then apply only to those pages, while graph-wide checks (orphans,
incoming links, index coverage) still compute against the whole vault and are
merely filtered down to findings about the listed pages — so a page isn't falsely
flagged an orphan just because you narrowed the view. `pages_checked` reflects the
scoped count. Without `--pages`, behaviour and output shape are exactly as before.
A positional vault path still works; `--vault` overrides it.

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
used to compute the next delta. The `wiki-lint` insights mode renders this JSON
into `_insights.md`. Needs `pyyaml`.

## `wiki-journal.py`

```sh
uv run .claude/wiki-scripts/wiki-journal.py --log 'INGEST source=_sources/x.pdf: insurance terms [[home/insurance]]' --hot-trim 3
uv run .claude/wiki-scripts/wiki-journal.py --log 'LINT 0 errors 54 warnings' --no-hot   # read-only runs
```

The mechanical half of every skill's "update the journal" step. The LLM composes only
the distilled entry text; the script appends the timestamped `log.md` line, prepends the
`hot.md` **Recent Activity** bullet, trims to the newest N, bumps `updated:`, and creates
`hot.md` from template if missing. `--log` is refused (exit 2, nothing written) past 240
characters: the detail belongs on the page. `--log` also feeds hot.md unless `--hot-entry
TEXT` replaces it or `--no-hot` suppresses it. log.md rotates itself into
`_archives/log-<year>.md` past 50 KB (keeping the newest ~25 KB); `--log-trim N` does the
same on demand. A warning goes to stderr when hot.md's body passes 600 words. `--hot-trim N`
bounds Recent Activity (only a top-level `## ` heading ends the section); `--date-only` for
a date-only log stamp; `--ts` / `--date` to override the clock. CRLF and BOM are preserved; a
non-UTF-8 sidecar is refused rather than rewritten. **Semantic sections (Key Takeaways,
Active Threads, Flagged Contradictions) are deliberately untouched**, edit those by hand.
Stdlib only; no `pyyaml`.

## `regen-manifest.py`

```sh
uv run .claude/wiki-scripts/regen-manifest.py --dry-run   # preview
uv run .claude/wiki-scripts/regen-manifest.py             # create or repair
```

`.manifest.json` is the vault marker (the scripts' walk-up looks for it; Obsidian never
reads it) plus vault-level config: `{version, created, updated, private_paths}`. It does
not track pages: git records what changed, and the old per-page entries drifted from the
pages they described. This script creates a missing manifest, moves an unparsable one to
`.manifest.json.bad`, and strips a legacy `sources` map and absolute `vault_path` while
keeping `private_paths` and any other top-level key. Idempotent: `updated` moves only when
the content changes. `--json` prints what was or would be done. `--vault` selects the
target; the legacy `REGEN_AT` / `DRY_RUN=1` env vars still work.

## `kebab-rename.py`

```sh
uv run .claude/wiki-scripts/kebab-rename.py --vault /path/to/vault --dry-run   # always preview first
uv run .claude/wiki-scripts/kebab-rename.py --vault /path/to/vault --apply
```

```powershell
# Windows / PowerShell — env vars persist for the session, so CLEAR them between
# runs or a stale APPLY=1 will fire on your next invocation.
cd C:\path\to\vault
$env:DRY_RUN=1; uv run .claude\wiki-scripts\kebab-rename.py; Remove-Item Env:DRY_RUN   # always preview first
$env:APPLY=1;   uv run .claude\wiki-scripts\kebab-rename.py; Remove-Item Env:APPLY
```

Refuses to run without exactly one of `--dry-run`/`DRY_RUN=1` or `--apply`/`APPLY=1`
(the `--dry-run` / `--apply` flags are the flag form of the env vars; `--vault`
selects the target, auto-detected when omitted).

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

Link parsing handles table-escaped pipes (`[[a\|b]]`), `#heading` and `^block` refs, a
`.md` suffix and `![[embeds]]`, skips fenced code, keeps CRLF, leaves attachment links
alone, and never renames daily notes, `templates/` or scaffolding. A non-UTF-8 page is
skipped with a message.

## `wiki-new.py`

```sh
uv run .claude/wiki-scripts/wiki-new.py <category>/<slug> --title "..." --summary "..." \
  [--tags a,b] [--sources x,y] [--lifecycle draft] [--supersedes <page>] [--mkdir] \
  [--body-file FILE | --body-file -]
```

Writes `<category>/<slug>.md` with `title`, `category` (the folder), `tags`, `summary`,
`lifecycle` and date-only `created`/`updated`, then the body (a `# Title` stub if none is
given). Refuses a non-kebab name, a missing folder (unless `--mkdir`), an existing page and
a summary over 200 characters. `--supersedes` sets `superseded_by`, `lifecycle: archived`
and `lifecycle_changed` on the page it replaces. Prints the path it wrote. Stdlib only.

## `claude-history.py`

```sh
uv run .claude/wiki-scripts/claude-history.py search fireplace thermostat   # which chat was that?
uv run .claude/wiki-scripts/claude-history.py sessions --limit 10
uv run .claude/wiki-scripts/claude-history.py stats --since 2026-09-01      # where the time goes
uv run .claude/wiki-scripts/claude-history.py runs                          # script timings
```

`runs` reads `~/.obsidian-wiki/runs.tsv`: every wiki script appends one line per run
(time, script, cwd, seconds, exit code, args, and stats such as lint's page and finding
counts), and the timestamp hook adds a line when it stamps or fails, so a silent miss is
visible. The file is machine-local, never in a vault; set `WIKI_RUNLOG=0` to disable.

Streams `~/.claude/projects/<project>/*.jsonl` line by line (a few hundred MB in seconds).
`--project` defaults to the current directory. `search` requires every term in a user
prompt (`--all` adds assistant text and tool inputs). Read-only, stdlib only.

## `wiki-commit.py`

```sh
uv run .claude/wiki-scripts/wiki-commit.py --journal 'CAPTURE page=[[sysadmin/x2/freeze-log]] freeze 5 and aspm test' <<'PLAN'
docs(sysadmin): record x2 freeze 5 and the aspm test
  sysadmin/x2/freeze-log.md
  sysadmin/x2/aspm.md
docs(home): add the furnace filter schedule
  home/furnace.md
PLAN
```

The agent writes the grouping and the messages; the script stages each group by name,
commits it through the normal gate, and stops at the first rejected commit (earlier ones
stay). Modified `.manifest.json`, `log.md` and `hot.md` that are not listed ride whole in
the last group, so they never get split across commits or need their own `chore(journal)`
commit; `--journal LINE` runs `wiki-journal.py --log LINE` first so the entry lands there
too. Refuses to start if anything is already staged. Prints the files that belong to no
group (another session's work) and leaves them alone. `--dry-run` shows the plan with
riders and leftovers. Stdlib only.

## `wiki-mv.py`

```sh
uv run .claude/wiki-scripts/wiki-mv.py sysadmin/old-name sysadmin/backup/new-name          # preview
uv run .claude/wiki-scripts/wiki-mv.py sysadmin/old-name sysadmin/backup/new-name --apply  # do it
```

Prints every changed line as a `-`/`+` pair, then with `--apply` moves the page,
rewrites links in content pages and `index.md` files (full-path links get the new path;
a bare-name link stays bare when the new name is unique, and an ambiguous one is reported,
not changed), rewrites bare-path frontmatter values such as `superseded_by:`, sets
`category:` when the folder changes (and re-keys a legacy manifest entry, if one exists). Links in `log.md`,
`hot.md` and `templates/` are listed but left as history; `_` and dot dirs are not read.
Refuses when the new path exists, is not kebab-case, is not a content page, or its folder
is missing (unless `--mkdir`). For merging into an existing page, repoint by hand.

## `stamp-staged.py`

```sh
uv run .claude/wiki-scripts/stamp-staged.py [--dry-run]   # from inside the vault work tree
```

Called by the vault pre-commit hook before the lint gate. For each staged, added or
modified content page whose `updated:` is not today, rewrites that one frontmatter line
(CRLF and BOM preserved) and re-stages the file. A partially staged file is left alone
with a note, since re-adding it would stage hunks you chose not to commit. Always exits
`0`; the lint gate decides. Stdlib only.

## `validate-frontmatter.py`

```sh
uv run .claude/wiki-scripts/validate-frontmatter.py [--vault PATH] [--staged]
```

Compatibility alias: runs `wiki-lint.py --only invalid_frontmatter,missing_frontmatter
--errors-only --format md`. INVALID means frontmatter present but unparseable (almost
always an unquoted colon-space such as `title: Acme: A Platform`, or a duplicate key);
MISSING means a real page without it or without a required field. Fix per the
colon-space rule: **rewrite to drop the colon (preferred), else double-quote the value.**

## `sync-agents.py`

```sh
uv run .claude/wiki-scripts/sync-agents.py                    # sync the auto-detected vault
uv run .claude/wiki-scripts/sync-agents.py --vault /path/vault # sync a specific vault
uv run /path/to/repo/scripts/sync-agents.py --all             # sync every registered vault
uv run .claude/wiki-scripts/sync-agents.py --check            # report drift, change nothing
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
