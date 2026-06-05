# Getting started

Five-minute tour. Clone, wire one vault, run your first three commands.

## What you get

- Claude Code skills implementing Andrej Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for Obsidian — distill raw sources into a compounding wiki, query it, keep it tidy.
- Python utilities: `wiki-lint.py` and `wiki-graph.py` — the deterministic backends behind the `wiki-lint` and `wiki-status` insights skills — plus gap-fillers the skills don't cover (rebuild manifest, mass kebab-case rename, validate frontmatter). The three that parse YAML (`wiki-lint.py`, `wiki-graph.py`, `validate-frontmatter.py`) are `uv` scripts that auto-install `pyyaml`; `regen-manifest.py` and `kebab-rename.py` are stdlib-only.

## Prerequisites

**For most skills (the whole point):** just [Claude Code](https://claude.com/claude-code), installed and authenticated, and an Obsidian vault (existing or empty directory, anywhere on disk). No Python, no `uv` — copy the skills in (see "Easiest: copy" below) and they work. The exceptions are `wiki-lint` and `wiki-status` insights, which call the Python analysis scripts below; everything else (ingest, query, link, capture, synthesize, …) is pure Claude Code.

**If you run the Python scripts** (the `wiki-lint` / `wiki-status`-insights backends, plus rebuild-manifest / mass-rename / validate-frontmatter):

- Python in `PATH` — invoked as `python3` on macOS/Linux, `python` or the `py` launcher on native Windows. `regen-manifest.py` and `kebab-rename.py` run on any 3.x; `wiki-lint.py` and `wiki-graph.py` need **3.10+**.
- [`uv`](https://docs.astral.sh/uv/) (all platforms) — the simplest way to run the YAML-parsing scripts (`wiki-lint.py`, `wiki-graph.py`, `validate-frontmatter.py`): `uv run` auto-installs `pyyaml`, nothing else to set up. Without `uv`, run them with `python3` after a one-time `pip install pyyaml`. `regen-manifest.py` and `kebab-rename.py` are stdlib-only and need neither.

## Wire one vault

### Easiest: copy (non-technical, works on Windows + WSL)

[Download the repo as a ZIP](https://github.com/cmedianu/cm-llm-wiki/archive/refs/heads/main.zip), unzip it, and inside your vault make a folder named `.claude`. Then:

- Copy `skills` into `.claude` (so you have `.claude/skills`).
- Copy `scripts` into `.claude` and rename it to `wiki-scripts`.
- Copy `wiki-conventions.md` into `.claude`.
- Create a `CLAUDE.md` at the vault root containing one line: `@.claude/wiki-conventions.md`.

No symlinks, no terminal — and it works identically from Windows and WSL, including cloud-synced folders like OneDrive, Dropbox, or Google Drive. Trade-off: it's a **snapshot**. When the repo updates, re-copy the files to get the changes.

### Stay in sync: link

Linking instead of copying means repo updates reach the vault automatically:

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

> **Don't link a cloud-synced vault.** If the vault lives under OneDrive/Dropbox/Google Drive, use the copy method above instead — cloud sync silently breaks junctions and symlinks. Details in [Common gotchas](#common-gotchas).

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

> **Heads-up:** `wiki-lint` ("audit my wiki") and `wiki-status` insights ("show me the hubs") run the Python analysis scripts (`wiki-lint.py` / `wiki-graph.py`), so they need `uv` (or `python3` + `pyyaml`) — see [Prerequisites](#prerequisites). Every other skill needs nothing but Claude Code.

Every skill's `description:` field (top of each `SKILL.md`) lists the exact phrases that trigger it. If you forget what to say, browse those.

## Multi-vault

Wire each vault the same way (steps 1–3). Two ways to switch:

- **Just `cd`.** Walking up from CWD to the nearest `.manifest.json` makes whichever vault you're inside the active one. This is the simplest pattern.
- **`/wiki-switch NAME`.** Manages named profiles at `~/.obsidian-wiki/config.NAME`. Useful if you want to operate on vault A while sitting in vault B's directory.

## Read the keystone

[`skills/wiki/SKILL.md`](../skills/wiki/SKILL.md) is the theory doc — three-layer architecture, page template, provenance markers, retrieval primitives. Every other skill defers to it. A ~5-minute read — go through it once before going deep.

## Common gotchas

**`.manifest.json` drifts.** If you rename/move/delete files outside the tooling (e.g. in Obsidian directly), run `scripts/regen-manifest.py` from the vault root to resync. Use `DRY_RUN=1` first to preview.

**Mass-rename, broken wikilinks.** `scripts/kebab-rename.py` does file rename + wikilink rewrite + manifest re-key in lockstep. Adapt `FOLDER_RENAMES` / `BRAND_PRESERVATIONS` / `PATH_OVERRIDES` for your own conventions before running.

**Windows links.** Native Windows (`wire-vault.ps1`) links the two directories with **junctions**, which every Windows tool — Claude Code, Obsidian, Python — follows transparently. The single `wiki-conventions.md` is a real symlink where possible, else a **copy**; if it fell back to a copy, repo-side edits to `wiki-conventions.md` won't reach the vault until you re-run `wire-vault.ps1` (enable Developer Mode for a live link). Obsidian ignores `.claude/` either way.

**Cloud-synced vaults break links (OneDrive / Dropbox / Google Drive).** These sync engines don't understand reparse points. A junction or symlink placed inside a synced folder gets flattened to a 0-byte stub on the Windows side — Explorer shows it as a 0 KB *File* (not a folder), with a perpetual "syncing" icon, and Obsidian/Claude-on-Windows can't traverse it. Verified: `wire-vault.ps1` into a OneDrive vault yields 0 KB stubs, while the identical command into a non-synced path like `C:\TEMP\testVault` yields working `<JUNCTION>`s. Resolutions, in order of preference:

1. **Use the copy method** ([top of this doc](#easiest-copy-non-technical-works-on-windows--wsl)) — real files sync cleanly and work from both Windows and WSL. You re-copy on repo updates; that's the only cost.
2. **Move the vault to a local, non-synced path** (e.g. `C:\Vaults\…`) and link there — junctions/symlinks behave normally off the sync root.

WSL is the exception: it resolves reparse points natively, so a `wire-vault.sh` setup used **only** from WSL works even when the vault sits under OneDrive — right up until a native-Windows tool needs `.claude/`, at which point the link reads as a broken 0 KB file. If your workflow is WSL-only, you can ignore this; if anything on the Windows side touches the vault, copy.

**No `.manifest.json`?** Skills can't locate the vault and tell you to run `wiki-setup`. That file is the canonical vault marker — `wiki-setup` creates it on a fresh vault, or `scripts/regen-manifest.py` bootstraps one on a vault that already has notes.

**Moved the vault, or `.claude` links broke?** Re-run `wire-vault.sh <vault>` from the repo to repair the links — `--check` first if you just want a diagnosis (on Windows: `wire-vault.ps1 <vault>`, `-Check` to diagnose). The vault content travels fine on its own; only the links back into this repo need re-pointing.

**Diverged from its origin.** This project began as a fork of Ar9av/obsidian-wiki but has changed so much — skills rewritten, renamed, and dropped; the config model replaced — that the relationship is now purely historical.
