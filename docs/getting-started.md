# Getting started

Five-minute tour. Clone, wire one vault, run your first three commands.

## What you get

- 14 Claude Code skills implementing Andrej Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for Obsidian — distill raw sources into a compounding wiki, query it, keep it tidy.
- 2 Python utilities (stdlib only) for gaps the skills don't cover: rebuild manifest, mass kebab-case rename.

## Prerequisites

- [Claude Code](https://claude.com/claude-code) installed and authenticated.
- An Obsidian vault (existing or empty directory). Anywhere on disk.
- Python 3.8+ in `$PATH`.

## Wire one vault

```sh
# 1. Clone this repo somewhere outside the vault.
git clone https://github.com/cmedianu/cm-llm-wiki /path/to/cm-llm-wiki

# 2. Symlink skills + scripts into the vault's .claude/.
REPO=/path/to/cm-llm-wiki
VAULT=/path/to/your/vault
mkdir -p "$VAULT/.claude"
ln -s "$REPO/skills"  "$VAULT/.claude/skills"
ln -s "$REPO/scripts" "$VAULT/.claude/wiki-scripts"

# 3. Tell the skills where the vault lives.
cat > "$VAULT/.env" <<EOF
OBSIDIAN_VAULT_PATH=$VAULT
OBSIDIAN_SOURCES_DIR=$VAULT
OBSIDIAN_CATEGORIES=AI,Notes,Projects
OBSIDIAN_LINK_FORMAT=wikilink
EOF
```

Skills resolve config by walking up from your shell's CWD until they find a `.env` with `OBSIDIAN_VAULT_PATH`. So `cd $VAULT && claude` puts you in that vault's context — no global flag.

## First three commands

Start Claude Code from inside the vault:

```sh
cd /path/to/your/vault
claude
```

Then say these in plain English. The skills auto-load based on what you ask.

### 1. See the state

> show me the status

Triggers `wiki-status`. Reports how many sources are ingested, what's pending, whether to append or rebuild next.

If the vault is fresh → run `wiki-setup` first ("set up my wiki").
If the vault already has notes but no `.manifest.json` → run `scripts/regen-manifest.py` from the vault root to bootstrap it.

### 2. Add a source

> ingest this folder: ~/Documents/research-papers

Triggers `wiki-ingest`. Reads each source, distills it into wiki pages, updates `index.md`, appends to `log.md`, updates `.manifest.json`. New pages land under the categories you set in `.env`.

### 3. Ask the wiki

> what do I know about transformer attention?

Triggers `wiki-query`. Searches `index.md`, frontmatter, and page bodies; returns a synthesized answer with citations.

For cheap lookups: phrase it as "quick answer: ..." and it'll read only `summary:` frontmatter fields, skipping page bodies.

## Daily workflows

| When you want to... | Say something like | Skill |
|---|---|---|
| Save the current chat | "save this to my wiki" | `wiki-capture` |
| Add new sources | "ingest these papers" | `wiki-ingest` |
| Ask the wiki | "what do I know about X?" | `wiki-query` |
| Run web research and file results | "research LLM evaluation" | `wiki-research` |
| Audit and fix issues | "audit my wiki" | `wiki-lint` |
| Add missing cross-links | "link my pages" | `cross-linker` |
| Push project work to the wiki | "save this project to the wiki" | `wiki-update` |
| Find cross-cutting connections | "synthesize my wiki" | `wiki-synthesize` |
| Mine your Claude session history | "process my Claude history" | `claude-history-ingest` |
| Start fresh | "rebuild the wiki" | `wiki-rebuild` |
| Switch between vaults | "/wiki-switch work" | `wiki-switch` |

Every skill's `description:` field (top of each `SKILL.md`) lists the exact phrases that trigger it. If you forget what to say, browse those.

## Multi-vault

Wire each vault the same way (steps 1–3). Two ways to switch:

- **Just `cd`.** The walked-up `.env` makes whichever vault you're inside the active one. This is the simplest pattern.
- **`/wiki-switch NAME`.** Manages named profiles at `~/.obsidian-wiki/config.NAME`. Useful if you want to operate on vault A while sitting in vault B's directory.

## Read the keystone

[`skills/llm-wiki/SKILL.md`](../skills/llm-wiki/SKILL.md) is the theory doc — three-layer architecture, page template, provenance markers, retrieval primitives. Every other skill defers to it. ~260 lines, ~5 min read. Read it once before going deep.

## Common gotchas

**`.manifest.json` drifts.** If you rename/move/delete files outside the tooling (e.g. in Obsidian directly), run `scripts/regen-manifest.py` from the vault root to resync. Use `DRY_RUN=1` first to preview.

**Mass-rename, broken wikilinks.** `scripts/kebab-rename.py` does file rename + wikilink rewrite + manifest re-key in lockstep. Adapt `FOLDER_RENAMES` / `BRAND_PRESERVATIONS` / `PATH_OVERRIDES` for your own conventions before running.

**WSL + Windows + OneDrive.** Symlinks work fine on the WSL side (where Claude Code runs). Windows tooling may not follow them — but nothing on the Windows side reads `.claude/`, so it's fine in practice. Obsidian itself ignores `.claude/`.

**No `.env`?** Skills refuse to run and tell you to run `wiki-setup`. Make sure your `.env` has `OBSIDIAN_VAULT_PATH` and is in the vault root.

**Trimmed compared to upstream.** This repo intentionally drops 8 skills and trims `llm-wiki/SKILL.md` from 447 to ~260 lines. See [`trimming-log.md`](trimming-log.md) if you want any of it back.
