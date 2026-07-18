# Design notes

Decision log for the wiki tooling. Git history answers *what changed*; this file answers *why it is this way*. One dated entry per decision — Context → Decision → Consequences, with pointers to where the decision lives in code. Append new entries at the top.

## 2026-07-17 — SKILL.md files use progressive disclosure

**Context:** A SKILL.md loads whole into the agent's context on every invocation, so its length is a per-invocation token cost. `wiki-ingest/SKILL.md` carried ~100 lines of Claude-history mode plus the multimodal branch on every plain document ingest, and every write-side skill was told to read the full ~280-line `wiki/SKILL.md` just for the Page-Writing Protocol.

**Decision:** Slim SKILL.md routers plus on-demand `references/` files. Mode-specific flows live in `wiki-ingest/references/claude-history-mode.md` and `multimodal-sources.md`; the write-side contract lives in `wiki/references/page-protocol.md` (~100 lines, self-sufficient).

**Consequences:** `wiki-ingest/SKILL.md` went 329 → 243 lines; write-side skills load the protocol reference instead of the theory skill — roughly 2–3k tokens saved per ordinary ingest. A new ingest mode is a new reference file, never SKILL.md growth. The SKILL.md must stay complete for the *default* path without opening any reference.

## 2026-07-17 — one-call ingest prep (`ingest-prep.py`)

**Context:** A real ingest session spent 4–5 sequential shell round-trips on survey work before writing anything: list categories, check the manifest for the source, grep for related pages, detect whether `index.md` is base-backed, read `private_paths`. Round-trips, not tokens, dominated wall-clock.

**Decision:** One read-only script, `scripts/ingest-prep.py`, emits all of it as a single JSON object (`categories`, `private_paths`, `manifest_status`, `index_base_backed`, `related_pages`), plus a `--backlinks-for` mode that surfaces post-write back-link candidates.

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

**Decision:** `ingest-prep.py` falls back to matching the source's basename against existing page keys and reports `modified` with the matched `manifest_key`.

**Consequences:** `modified` here means "this source already produced pages — merge, don't duplicate," not "the source file's content changed." Paired rule in the ingest skill: snapshot external sources into `_sources/` and key `sources:` frontmatter on the vault-relative snapshot path, so provenance never dangles when tmp dirs vanish.

## 2026-07-17 — dense sources restructure; they don't shrink

**Context:** Ingesting a hand-written, already-distilled, command-heavy how-to at standard depth produced near-1:1 line volume versus the source, prompting a "what did distillation buy?" question.

**Decision:** Codify the expectation in `wiki-ingest`'s Ingest Depth section: for a source with no filler, the value-add is atomization into linkable concept pages plus cross-references — not compression. A "reference-grade" ingest (how-to page stays close to source, only reusable concepts extracted) is the lighter alternative.

**Consequences:** Near-parity volume on dense sources is expected behavior, not a quality failure, and no longer needs re-litigating per ingest.
