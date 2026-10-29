# Design notes

Decision log for the wiki tooling. Git history answers *what changed*; this file answers *why it is this way*. One dated entry per decision — Context → Decision → Consequences, with pointers to where the decision lives in code. Append new entries at the top.

## 2026-10-28 — the skill family is trimmed to what gets used; the manifest is only a marker

**Context:** Over ~140 sessions in two vaults (2026-07 to 10-27), skill use was lopsided: `wiki-capture` 13 invocations, `wiki-ingest` 3 (+11 typed `/wiki-ingest`), `wiki-query` 1 (+9 typed; the `wiki.query` CLI is the real query surface), `wiki-lint` 1, `wiki-compact` 1. `wiki-link` (and its synthesis mode), `wiki-status`, `wiki-research` and `wiki-vault` were never invoked, yet carried about a third of the SKILL.md text. The user typed `/wiki-archive` and `/wiki-journal`, which did not exist. Separately, `.manifest.json`'s per-page entries disagreed with page frontmatter on 83% of pages and nothing read them; the only live consumer was `wiki-status`'s delta, and `ingest-prep`'s new/modified verdict already came from the `_sources/` snapshot.

**Decision:** Keep `wiki`, `wiki-capture`, `wiki-ingest`, `wiki-query`, `wiki-lint`, `wiki-compact`. `wiki-status` becomes `wiki-lint`'s Status mode (git status/log for pages, `ingest-prep.py --sources-dir` for sources, `claude-history.py sessions` for conversations, `wiki-lint.py --summary` for health) and Insights mode (`wiki-graph.py`, in `references/insights.md`). `wiki-link`'s back-link pass becomes a step of ingest and capture; synthesis moves to `wiki-compact/references/synthesis.md`; its triggers moved into those skills' descriptions. `wiki-research` is retired (generic research skills cover it). `wiki-vault` keeps the new-vault flow and register/map/list, with the quiz and `/wiki-switch` in a reference. Two thin routers were added for the names the user typed: `wiki-archive` (compact's retire action) and `wiki-journal` (`wiki-journal.py`). `.manifest.json` shrinks to `{version, created, updated, private_paths}`: it marks the vault root for the scripts' walk-up (Obsidian never reads it), `regen-manifest.py` creates or repairs it and strips legacy entries, and `ingest-prep`'s `manifest_status` becomes `source_status` (old key kept as an alias), decided by the `_sources/` snapshot, falling back to a page whose filename matches.

**Consequences:** Skill text dropped by about a quarter (21.8k to 16.4k words across `skills/`), and every invocation loads less. No skill reads or writes per-page manifest state, so renames re-key nothing and resync diffs disappear. Status needs a git-managed vault for its page delta. Removed skills leave dangling `~/.claude/skills` / `~/.agents/skills` links; `wire-vault --user` has to prune links into `skills/` that no longer exist.

## 2026-10-27 — the gate checks the commit, not the vault

**Context:** The pre-commit hook ran frontmatter validation and a whole-vault lint on every commit: 21-27 s on the 450-page reference vault, 100-230 s on a small vault holding a large `_`-prefixed mail archive, two commits killed by a tool timeout. The workaround convention ("`--no-verify` on every commit but the last") was followed on 32% and 91% of commits respectively, and drifted into "always skip". Profiling showed ~85% of lint time was redundant filesystem traffic: a `stat()` per wikilink, each page read three times, recursive globs descending into `_` and dot dirs.

**Decision:** `wiki-lint.py` walks once (dot- and `_`-dirs pruned), reads each page once with 16 reads in flight, resolves links in memory case-insensitively, and parses YAML with libyaml (3 s full run). `--staged --errors-only` reads only the staged pages and is the whole gate; `validate-frontmatter.py` is an alias. `stamp-staged.py` sets `updated:` on staged pages at commit time, because agents edit pages through the shell about half the time and the PostToolUse hook never sees those edits. `is_content_page()` joins `resolve_vault()` as a deliberately copy-pasted helper with one documented rule.

**Consequences:** A commit is gated in about two seconds and an unstaged page left by another session never blocks it. The batching convention is gone. A partially staged page is not stamped (re-adding it would stage hunks the author held back). Graph-wide warnings (orphans, index coverage) are not part of the gate; run `wiki-lint.py --summary` for them.

## 2026-07-17 — SKILL.md files use progressive disclosure

**Context:** A SKILL.md loads whole into the agent's context on every invocation, so its length is a per-invocation token cost. `wiki-ingest/SKILL.md` carried ~100 lines of Claude-history mode plus the multimodal branch on every plain document ingest, and every write-side skill was told to read the full ~280-line `wiki/SKILL.md` just for the Page-Writing Protocol.

**Decision:** Slim SKILL.md routers plus on-demand `references/` files. Mode-specific flows live in `wiki-ingest/references/claude-history-mode.md` and `multimodal-sources.md`; the write-side contract lives in `wiki/references/page-protocol.md` (~100 lines, self-sufficient).

**Consequences:** `wiki-ingest/SKILL.md` went 329 → 243 lines; write-side skills load the protocol reference instead of the theory skill — roughly 2–3k tokens saved per ordinary ingest. A new ingest mode is a new reference file, never SKILL.md growth. The SKILL.md must stay complete for the *default* path without opening any reference.

## 2026-07-17 — one-call ingest prep (`ingest-prep.py`)

**Context:** A real ingest session spent 4–5 sequential shell round-trips on survey work before writing anything: list categories, check the manifest for the source, grep for related pages, detect whether `index.md` is base-backed, read `private_paths`. Round-trips, not tokens, dominated wall-clock.

**Decision:** One read-only script, `scripts/ingest-prep.py`, emits all of it as a single JSON object (`categories`, `private_paths`, `manifest_status`, `index_base_backed` (since 2026-10-27 `index_status`: base_backed / hybrid / manual), `related_pages`), plus a `--backlinks-for` mode that surfaces post-write back-link candidates.

**Consequences:** One tool call replaces the survey; ad-hoc python heredocs disappear from ingest transcripts. The skill instructs agents to call it instead of hand-rolling greps.

## 2026-07-17 — vault resolver is deliberately copy-pasted into every script

**Context:** All scripts are standalone PEP-723 `uv` scripts with no cross-imports — by design, since they're copied (not symlinked) into vaults, which must stay relocatable with zero wiring.

**Decision:** `resolve_vault()` (flag → walk-up → `projects.json` → env) is replicated verbatim in all 8 scripts rather than extracted into a shared module.

**Consequences:** A change to the resolution chain must touch every copy — `scripts/README.md` says so. The alternative (a shared module) would break the copy-one-file deployment model. All scripts accept `--vault` with identical semantics; legacy `REGEN_AT` and `OBSIDIAN_VAULT_PATH` env fallbacks are kept for back-compat.

## 2026-07-17 — back-link candidates use a document-frequency cap

**Context:** In `ingest-prep.py --backlinks-for`, a pure stopword + minimum-length filter on title terms let generic words like "agent" flag 89 of ~250 pages as back-link candidates — noise, not signal.

**Decision:** Skip any term appearing in more than 15% of pages (`df_cap` in `scripts/ingest-prep.py`) as too generic to indicate a real relationship.

**Consequences:** Candidates dropped to a reviewable ~19 on the reference vault. The 0.15 constant is the tuning knob: loosen it if a much larger vault makes candidates too sparse. The filter operationalizes "distinctive term"; the agent still applies judgment before adding links.

## 2026-07-17 — `manifest_status` for external sources matches by basename against produced pages

**Context:** The manifest tracks wiki *pages*, not raw `_sources/` files, so a source living outside the vault (a tmp dir, a download) has no manifest key to delta against directly.

**Decision:** `ingest-prep.py` settles external sources byte-level first: when an on-disk `_sources/<basename>` snapshot exists, identical content → `unchanged`, differing → `modified` — the snapshot, not manifest timestamps, is the ground truth for "already ingested" (a first test run of the flow showed timestamp-based matching alone could never say `unchanged` for external sources). Only without a snapshot does it fall back to matching the basename against existing page keys.

**Consequences:** `modified` means "this source already produced pages and its content changed — merge, don't duplicate"; `unchanged` means skip. The prep JSON reports the `snapshot` path alongside `manifest_key`. Paired rule in the ingest skill: snapshot external sources into `_sources/` and key `sources:` frontmatter on the vault-relative snapshot path, so provenance never dangles when tmp dirs vanish.

## 2026-07-17 — dense sources restructure; they don't shrink

**Context:** Ingesting a hand-written, already-distilled, command-heavy how-to at standard depth produced near-1:1 line volume versus the source, prompting a "what did distillation buy?" question.

**Decision:** Codify the expectation in `wiki-ingest`'s Ingest Depth section: for a source with no filler, the value-add is atomization into linkable concept pages plus cross-references — not compression. A "reference-grade" ingest (how-to page stays close to source, only reusable concepts extracted) is the lighter alternative.

**Consequences:** Near-parity volume on dense sources is expected behavior, not a quality failure, and no longer needs re-litigating per ingest.
