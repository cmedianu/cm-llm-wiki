# Getting started

Five-minute tour. Clone, wire one vault, run your first three commands.

## What you get

- Claude Code skills implementing Andrej Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for Obsidian — distill raw sources into a compounding wiki, query it, keep it tidy.
- Python utilities for gaps the skills don't cover: rebuild manifest, mass kebab-case rename, and validate frontmatter. Most are stdlib-only; the validator is a `uv` script (auto-installs `pyyaml`).

## Prerequisites

- [Claude Code](https://claude.com/claude-code) installed and authenticated.
- An Obsidian vault (existing or empty directory). Anywhere on disk.
- Python 3.8+ in `PATH` — invoked as `python3` on macOS/Linux, `python` or the `py` launcher on native Windows.
- [`uv`](https://docs.astral.sh/uv/) (all platforms) — only `validate-frontmatter.py` needs it; the other scripts are stdlib-only.

## Wire one vault

```sh
# 1. Clone this repo somewhere outside the vault.
git clone https://github.com/cmedianu/cm-llm-wiki /path/to/cm-llm-wiki

# 2. Wire your vault to it (idempotent — also repairs links later).
/path/to/cm-llm-wiki/wire-vault.sh /path/to/your/vault
```

On **native Windows** (PowerShell, no WSL) use the `.ps1` port instead of step 2:

```powershell
git clone https://github.com/cmedianu/cm-llm-wiki C:\path\to\cm-llm-wiki
& C:\path\to\cm-llm-wiki\wire-vault.ps1 C:\path\to\your\vault
```

The two directory links use **junctions** (no admin, no Developer Mode). The single `wiki-conventions.md` link uses a real **symlink** when it can, falling back to a **copy** if Developer Mode is off and the shell isn't elevated — re-run after [enabling Developer Mode](https://learn.microsoft.com/windows/apps/get-started/enable-your-device-for-development) for a live link.

That creates the three `.claude` links (`skills`, `wiki-scripts`, `wiki-conventions.md`) and seeds a `CLAUDE.md` that imports the shared conventions. Open it and fill in the "This vault's specifics" section (folder taxonomy, private areas, special namespaces).

The vault is the directory containing `.manifest.json`; skills find the active vault by walking up from your shell's CWD for it, so `cd /path/to/your/vault && claude` puts you in that vault's context — no global flag. If the vault has no `.manifest.json` yet, create it with `wiki-setup` (see below).

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
If the vault already has notes but no `.manifest.json` → run `scripts/regen-manifest.py` from the vault root to bootstrap it (`python3 regen-manifest.py`; on Windows `python regen-manifest.py`).

### 2. Add a source

> ingest this folder: ~/Documents/research-papers

Triggers `wiki-ingest`. Reads each source, distills it into wiki pages, updates `index.md`, appends to `log.md`, updates `.manifest.json`. New pages land under your vault's category folders (the top-level folders are the taxonomy).

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
| Add missing cross-links | "link my pages" | `wiki-link` |
| Push project work to the wiki | "save this project to the wiki" | `wiki-update` |
| Find cross-cutting connections | "synthesize my wiki" | `wiki-synthesize` |
| Mine your Claude session history | "process my Claude history" | `wiki-claude-history` |
| Start fresh | "rebuild the wiki" | `wiki-rebuild` |
| Switch between vaults | "/wiki-switch work" | `wiki-switch` |

Every skill's `description:` field (top of each `SKILL.md`) lists the exact phrases that trigger it. If you forget what to say, browse those.

## Multi-vault

Wire each vault the same way (steps 1–3). Two ways to switch:

- **Just `cd`.** Walking up from CWD to the nearest `.manifest.json` makes whichever vault you're inside the active one. This is the simplest pattern.
- **`/wiki-switch NAME`.** Manages named profiles at `~/.obsidian-wiki/config.NAME`. Useful if you want to operate on vault A while sitting in vault B's directory.

## Read the keystone

[`skills/wiki/SKILL.md`](../skills/wiki/SKILL.md) is the theory doc — three-layer architecture, page template, provenance markers, retrieval primitives. Every other skill defers to it. ~260 lines, ~5 min read. Read it once before going deep.

## Common gotchas

**`.manifest.json` drifts.** If you rename/move/delete files outside the tooling (e.g. in Obsidian directly), run `scripts/regen-manifest.py` from the vault root to resync. Use `DRY_RUN=1` first to preview.

**Mass-rename, broken wikilinks.** `scripts/kebab-rename.py` does file rename + wikilink rewrite + manifest re-key in lockstep. Adapt `FOLDER_RENAMES` / `BRAND_PRESERVATIONS` / `PATH_OVERRIDES` for your own conventions before running.

**Windows links.** Native Windows (`wire-vault.ps1`) links the two directories with **junctions**, which every Windows tool — Claude Code, Obsidian, Python — follows transparently. The single `wiki-conventions.md` is a real symlink where possible, else a **copy**; if it fell back to a copy, repo-side edits to `wiki-conventions.md` won't reach the vault until you re-run `wire-vault.ps1` (enable Developer Mode for a live link). Obsidian ignores `.claude/` either way.

**WSL + Windows + OneDrive.** Under WSL, symlinks work fine on the WSL side (where Claude Code runs). Windows tooling may not follow WSL-created symlinks — but nothing on the Windows side reads `.claude/`, so it's fine in practice.

**No `.manifest.json`?** Skills can't locate the vault and tell you to run `wiki-setup`. That file is the canonical vault marker — `wiki-setup` creates it on a fresh vault, or `scripts/regen-manifest.py` bootstraps one on a vault that already has notes.

**Moved the vault, or `.claude` links broke?** Re-run `wire-vault.sh <vault>` from the repo to repair the links — `--check` first if you just want a diagnosis (on Windows: `wire-vault.ps1 <vault>`, `-Check` to diagnose). The vault content travels fine on its own; only the links back into this repo need re-pointing.

**Diverged from its origin.** This project began as a fork of Ar9av/obsidian-wiki but has changed so much — skills rewritten, renamed, and dropped; the config model replaced — that the relationship is now purely historical.
