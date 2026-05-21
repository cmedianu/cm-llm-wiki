# Trimming Log

Record of what was removed from the upstream skills, why, and how to
restore if any cut turns out to be useful in practice.

## How to restore a cut

Every removed section still exists in the upstream:
<https://github.com/Ar9av/obsidian-wiki>. To pull the old text:

```sh
curl -fsSL "https://raw.githubusercontent.com/Ar9av/obsidian-wiki/main/skills/llm-wiki/SKILL.md" > /tmp/upstream.md
# then copy the section you want back into the current file
```

Or clone the upstream and `diff` against this repo:

```sh
git clone https://github.com/Ar9av/obsidian-wiki /tmp/upstream
diff -u /tmp/upstream/skills/llm-wiki/SKILL.md skills/llm-wiki/SKILL.md
```

---

## `skills/llm-wiki/SKILL.md`

Original: 447 lines. Trimmed: ~260 lines. The keystone — every other
skill references it. Lots of speculative machinery had accreted that
goes beyond what Karpathy proposes.

### Cuts

| Section / feature | Approximate upstream lines | Why cut |
|---|---|---|
| **Confidence formula** — `base_confidence = source_count_score * 0.5 + source_quality_score * 0.5` plus the source-quality bucket table (paper/official/documentation/book/repository/blog/...) and `source_id` rules table | ~50 lines (`## Confidence and Lifecycle`) | Karpathy's gist proposes no scoring system. The formula was a speculative add-on. Reduced `base_confidence` to an optional field with a single default (0.85 for human-authored) and let ingest skills set their own defaults. |
| **Per-skill `base_confidence` defaults table** (`ingest-url: 0.17 + 0.5 × classify(url)`, etc.) | ~12 lines | Inferred policy table about skills that don't exist or weren't faithful to upstream. Each skill can document its own default. |
| **Lifecycle state machine** — 5 states (`draft / reviewed / verified / disputed / archived`), transitions table, "only ingest skills set draft," `lifecycle_changed` ISO date, optional `lifecycle_reason` and `superseded_by` | ~30 lines | Karpathy doesn't propose lifecycle. Bureaucratic for personal wikis. Reduced to 3 informal states (draft/reviewed/archived) as an optional field with no formal transitions. |
| **Provenance fractional accounting** in frontmatter — `provenance: {extracted: 0.72, inferred: 0.25, ambiguous: 0.03}` | ~15 lines | Karpathy talks about marking inferences inline (which we kept), not computing fractions. Drift-detection on these numbers was the only reason to maintain them. |
| **Required `base_confidence` / `lifecycle` / `lifecycle_changed` frontmatter fields** in the page template | a few lines, but cross-cuts every page | Made all three optional. Hand-authored pages have no use for any of them; ingest skills can still emit them. |
| **Prescriptive categories table** — `concepts/ entities/ skills/ references/ synthesis/ journal/` listed as the default with the Purpose / Example columns | ~10 lines | Replaced with "pick a pattern that fits your domain — domain folders or karpathy taxonomy, both work." |
| **Projects sub-pattern** — `projects/<name>/<category>/...` directory layout, project overview page template, naming rule (`<project-name>.md` not `_project.md`), cross-referencing guidance | ~50 lines (`### Projects` and onward) | Karpathy doesn't propose a projects/ axis. Adds a second organizational dimension that complicates the model. If a user wants project scoping they can use folders without needing a formal pattern. |

### What was NOT cut (and why)

| Kept | Reason |
|---|---|
| Three-Layer Architecture | Foundational — directly from Karpathy. |
| `index.md` / `log.md` / `.manifest.json` structure | Karpathy mentions all three. |
| `index.md` format rule (space after `(` before tags) | Catches a real parsing bug. |
| Page Template (basic frontmatter) | Minimal version without the speculative fields. |
| `summary:` frontmatter field, 200-char limit | `wiki-query`'s cheap retrieval path depends on it. |
| Provenance Markers (`^[inferred]`, `^[ambiguous]`) | Karpathy mentions provenance; inline marking is the lightest reasonable form. |
| Retrieval Primitives table | Operationally crucial for large vaults — escalation rule keeps token cost bounded. |
| Core Principles list | Karpathy's spirit, condensed. |
| Link Format (wikilink vs markdown) | Needed because `OBSIDIAN_LINK_FORMAT` exists. |
| Config Resolution Protocol (walk-up `.env`) | Enables multi-vault. |
| Vault-scoped state (`VAULT_ID` md5 hash) | Prevents two vaults' runtime state colliding. |
| Environment Variables list | Required for setup. |
| Modes of Operation (append/rebuild/restore) | Karpathy's three operations. |

---

## Dropped upstream skills

Eight skills from the upstream were dropped wholesale as overengineered
or off-pattern (see the main README for the list). To restore any of
them, copy the folder from upstream:

```sh
git clone https://github.com/Ar9av/obsidian-wiki /tmp/upstream
cp -r /tmp/upstream/skills/wiki-dashboard skills/
```

---

## Notes for the future

If you find yourself wanting any of the trimmed machinery back after
actually using the skills:

1. Grab the section from upstream Ar9av/obsidian-wiki.
2. Paste it back into the skill file.
3. Update this log: move the entry from "cuts" to "restored" and note
   what changed your mind. The point is to learn what's genuinely
   useful, not to keep the wiki light for its own sake.

If after a few months nothing has been restored, the cuts proved right.
