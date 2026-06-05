# cm-llm-wiki

An implementation of Andrej Karpathy's
[LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
for Obsidian — a family of Claude Code skills plus maintenance scripts, extracted from
an Obsidian vault so multiple vaults can share one canonical copy.

It began as a fork of [Ar9av/obsidian-wiki](https://github.com/Ar9av/obsidian-wiki), but
has diverged so far since — skills rewritten and renamed, most of them trimmed away, the
config model replaced, new tooling added — that it no longer has anything meaningful in
common with that project. The shared ancestry is **purely historical**.

MIT licensed — see `LICENSE`. Original copyright (c) 2026 Ar9av; modifications (c) 2026
cmedianu. The attribution is retained because the license requires it, not because the
code still resembles the original.

**New here?** Start with [`docs/getting-started.md`](docs/getting-started.md) — five-minute tour from clone to first wiki query.

## Layout

```
skills/              Claude Code skills — the schema layer of the wiki pattern
scripts/             Python maintenance scripts (kebab-rename, regen-manifest, validate-frontmatter)
wiki-conventions.md  Shared CLAUDE.md conventions, @-imported by every vault
```

Each Obsidian vault symlinks `<vault>/.claude/skills`,
`<vault>/.claude/wiki-scripts`, and `<vault>/.claude/wiki-conventions.md` to the
files here, so an edit in the repo takes effect everywhere immediately.

## Wiring a new vault

One command from the repo:

```sh
./wire-vault.sh /path/to/your/vault
```

On **native Windows** (PowerShell, no WSL) use the `.ps1` port — same flags, same output:

```powershell
.\wire-vault.ps1 C:\path\to\your\vault          # -Check to diagnose without changing anything
```

`wire-vault.sh` is idempotent: it creates the three `.claude` symlinks (`skills`,
`wiki-scripts`, `wiki-conventions.md`) and seeds a `CLAUDE.md` from the template
**only if one isn't already there**. Re-run it any time to repair links — e.g.
after moving the vault or cloning the repo to a new path. `./wire-vault.sh --check
<vault>` reports the wiring state without changing anything (exit 0 = fully wired).
`wire-vault.ps1` does the same on Windows, linking the two directories with
junctions and `wiki-conventions.md` with a symlink (or a copy if Developer Mode is
off) — see [`docs/getting-started.md`](docs/getting-started.md) for the details.

By hand, it's just:

```sh
REPO=/path/to/cm-llm-wiki
VAULT=/path/to/your/vault
mkdir -p "$VAULT/.claude"
ln -s "$REPO/skills"              "$VAULT/.claude/skills"
ln -s "$REPO/scripts"             "$VAULT/.claude/wiki-scripts"
ln -s "$REPO/wiki-conventions.md" "$VAULT/.claude/wiki-conventions.md"

cat > "$VAULT/CLAUDE.md" <<'EOF'
# <Vault Name>

Shared wiki conventions (filenames, frontmatter, wikilinks, categories, index/log
sync) are imported from the cm-llm-wiki master repo — edit them there, not here:

@.claude/wiki-conventions.md

## This vault's specifics

- (folder taxonomy, private areas, special namespaces — fill in per vault)
EOF
```

`@.claude/wiki-conventions.md` is a Claude Code import: the shared rules in
[`wiki-conventions.md`](wiki-conventions.md) are pulled into every vault's `CLAUDE.md`
through that symlink, so editing them once in the repo updates all vaults. Keep
per-vault rules below the import.

That's the whole wiring. The vault is self-describing: it's the directory
containing `.manifest.json`, and skills derive every path (sources, archives, link
format) from that location. They find the active vault by walking up from your
shell's CWD for `.manifest.json`, so `cd`-ing into a vault sets the context — no
global flag, no config file.

If the vault has no `.manifest.json` yet, initialize it: run `wiki-setup` ("set up
my wiki") from inside the vault, or `wiki-scripts/regen-manifest.py` if it already
has notes. Keep the vault relocatable — no hard-coded absolute paths pointing back
at itself, so `cp -r <vault> elsewhere && cd elsewhere` just works (see the keystone
`skills/wiki/SKILL.md`).

## Portability & moving a vault

The setup has two layers with different portability — worth understanding before you
copy or share a vault:

- **Vault content is portable.** Pages, `index.md`, `log.md`, and `.manifest.json` use
  relative paths only, so `cp -r <vault> elsewhere` keeps the wiki fully functional *as
  data*.
- **Tooling is shared, not copied.** The skills, scripts, and conventions live here in
  the repo and are *symlinked* into each vault's `.claude/`. That's deliberate — edit
  once, every vault updates — but it means those symlinks (and the `@.claude/wiki-conventions.md`
  import in `CLAUDE.md`) only resolve where this repo exists at the linked path.

So moving a vault to a **new machine** is two steps, not one: copy the vault, then clone
this repo there and run `./wire-vault.sh <vault>` (or `wire-vault.ps1 <vault>` on Windows)
to re-point the links. The same command repairs a vault whose links broke for any reason;
`./wire-vault.sh --check <vault>` (`-Check` on Windows) tells you whether you need to. The mental model: **vault = data (portable), repo = tooling
(clone-and-link)**.

## Skills

Core karpathy operations:

- `wiki` — three-layer architecture and conventions (the "theory" keystone)
- `wiki-setup` — initialize a new vault
- `wiki-ingest` — distill source documents into wiki pages
- `wiki-query` — answer questions against the wiki
- `wiki-lint` — health check (orphans, contradictions, stale pages)
- `wiki-status` — manifest delta vs sources
- `wiki-rebuild` — archive, rebuild from scratch, restore

Adjuncts:

- `wiki-link` — write-side: discover and insert missing wikilinks
- `wiki-switch` — manage multiple named vault profiles
- `wiki-update` — push knowledge from any working project into the vault
- `wiki-capture` — save current conversation as a structured page
- `wiki-claude-history` — mine `~/.claude` session data into the wiki
- `wiki-research` — multi-round web research + auto-file results
- `wiki-synthesize` — discover cross-page synthesis opportunities

## Scripts

See `scripts/README.md`.

## References

- Andrej Karpathy, *LLM Wiki* — https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
  The pattern this repo implements: raw sources → distilled wiki → schema.
