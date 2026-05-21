# cm-llm-wiki

Personal fork of [Ar9av/obsidian-wiki](https://github.com/Ar9av/obsidian-wiki) —
an implementation of Andrej Karpathy's
[LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) —
trimmed, plus maintenance scripts. Extracted from an Obsidian vault so
multiple vaults can share one canonical copy.

MIT licensed — see `LICENSE`. Original copyright (c) 2026 Ar9av;
modifications (c) 2026 cmedianu.

**New here?** Start with [`docs/getting-started.md`](docs/getting-started.md) — five-minute tour from clone to first wiki query.

## Layout

```
skills/    Claude Code skills — the schema layer of the wiki pattern
scripts/   Python maintenance scripts (kebab-rename, regen-manifest, etc.)
```

Each Obsidian vault symlinks `<vault>/.claude/skills` and
`<vault>/.claude/wiki-scripts` to the folders here, so an edit in the repo
takes effect everywhere immediately.

## Wiring a new vault

```sh
REPO=/path/to/cm-llm-wiki
VAULT=/path/to/your/vault
mkdir -p "$VAULT/.claude"
ln -s "$REPO/skills"  "$VAULT/.claude/skills"
ln -s "$REPO/scripts" "$VAULT/.claude/wiki-scripts"
```

Then create `<vault>/.env`:

```env
OBSIDIAN_VAULT_PATH=/path/to/new/vault
OBSIDIAN_SOURCES_DIR=/path/to/new/vault
OBSIDIAN_CATEGORIES=Foo,Bar,Baz
OBSIDIAN_LINK_FORMAT=wikilink
```

Skills walk up from CWD to find `.env`, so `cd`-ing into a vault sets the
active context — no global flag.

## Skills (14)

Core karpathy operations:

- `llm-wiki` — three-layer architecture and conventions (the "theory")
- `wiki-setup` — initialize a new vault
- `wiki-ingest` — distill source documents into wiki pages
- `wiki-query` — answer questions against the wiki
- `wiki-lint` — health check (orphans, contradictions, stale pages)
- `wiki-status` — manifest delta vs sources
- `wiki-rebuild` — archive, rebuild from scratch, restore

Adjuncts:

- `cross-linker` — write-side: discover and insert missing wikilinks
- `wiki-switch` — manage multiple named vault profiles
- `wiki-update` — push knowledge from any working project into the vault
- `wiki-capture` — save current conversation as a structured page
- `claude-history-ingest` — mine `~/.claude` session data into the wiki
- `wiki-research` — multi-round web research + auto-file results
- `wiki-synthesize` — discover cross-page synthesis opportunities

## Dropped from upstream

The following skills were dropped as overengineered or off-pattern for
this use:

`wiki-dashboard`, `wiki-digest`, `wiki-export`, `graph-colorize`,
`memory-bridge`, `wiki-agent`, `wiki-history-ingest`, `obsidian-wiki-ingest`.

If you want any back, they still exist in the upstream (pinned):
<https://github.com/Ar9av/obsidian-wiki/tree/6f20faa/.skills>.

## Scripts

See `scripts/README.md`.

## Status

Skills are kept as-extracted in the initial commit. Trimming and rewriting
for karpathy-fidelity is a separate task — issues / branches to follow.

## References

- Andrej Karpathy, *LLM Wiki* — https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
  The pattern this repo implements: raw sources → distilled wiki → schema.
