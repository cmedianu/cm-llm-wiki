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
scripts/             Python maintenance + analysis scripts (wiki-lint, wiki-graph, kebab-rename, regen-manifest, validate-frontmatter)
wiki-conventions.md  Shared CLAUDE.md conventions, @-imported by every vault
```

The tooling installs in **two layers**, so an edit in the repo takes effect everywhere immediately:

- **Skills, once per machine at user level.** Each `wiki-*` skill is symlinked into
  `~/.claude/skills/`, so the `/wiki-*` commands work in *every* project, wiki or not.
- **Per vault, only the vault-relative tooling.** Each vault symlinks
  `<vault>/.claude/wiki-scripts` (to `scripts/`), `<vault>/.claude/wiki-conventions.md`,
  and `<vault>/.claude/hooks`. Skills are **not** linked per-vault anymore.

Skills run from anywhere; the active vault is resolved at run time (manifest walk-up, then a
project map, then a quiz). See **Choosing a vault** below.

## Wiring

Two steps, matching the two layers. Both are idempotent and support `--check` (report only,
exit 0 = fully wired).

**1. Install the skills once per machine** (user level):

```sh
./wire-vault.sh --user
```

**2. Wire each vault's tooling** (no skills; scripts, conventions, hooks):

```sh
./wire-vault.sh /path/to/your/vault
```

On **native Windows** (PowerShell, no WSL) use the `.ps1` port, same flags, same output:

```powershell
.\wire-vault.ps1 -User                      # step 1
.\wire-vault.ps1 C:\path\to\your\vault      # step 2  (-Check to diagnose without changing anything)
```

`--user` symlinks every `wiki-*` skill into `~/.claude/skills/`. The per-vault run creates the
three `.claude` symlinks (`wiki-scripts`, `wiki-conventions.md`, `hooks`), seeds a `CLAUDE.md`
from the template **only if one isn't already there**, and flags a stray `wiki-*` under
`.claude/skills` left over from the old per-vault model. Re-run either any time to repair links,
e.g. after moving a vault or cloning the repo to a new path (the `.sh` even converts a stale real
copy back into a symlink). `wire-vault.ps1` links directories with junctions and
`wiki-conventions.md` with a symlink (or a copy if Developer Mode is off); see
[`docs/getting-started.md`](docs/getting-started.md).

By hand, the per-vault step is just:

```sh
REPO=/path/to/cm-llm-wiki
VAULT=/path/to/your/vault
mkdir -p "$VAULT/.claude"
ln -s "$REPO/scripts"             "$VAULT/.claude/wiki-scripts"
ln -s "$REPO/wiki-conventions.md" "$VAULT/.claude/wiki-conventions.md"
ln -s "$REPO/hooks"               "$VAULT/.claude/hooks"

cat > "$VAULT/CLAUDE.md" <<'EOF'
# <Vault Name>

Shared wiki conventions (filenames, frontmatter, wikilinks, categories, index/log
sync) are imported from the cm-llm-wiki master repo, edit them there, not here:

@.claude/wiki-conventions.md

## This vault's specifics

- (folder taxonomy, private areas, special namespaces, fill in per vault)
EOF
```

`@.claude/wiki-conventions.md` is a Claude Code import: the shared rules in
[`wiki-conventions.md`](wiki-conventions.md) are pulled into every vault's `CLAUDE.md`
through that symlink, so editing them once in the repo updates all vaults. Keep
per-vault rules below the import.

If the vault has no `.manifest.json` yet, initialize it: run `wiki-setup` ("set up
my wiki") from inside the vault, or `wiki-scripts/regen-manifest.py` if it already
has notes. Keep the vault relocatable, with no hard-coded absolute paths pointing back
at itself, so `cp -r <vault> elsewhere && cd elsewhere` just works (see the keystone
`skills/wiki/SKILL.md`).

## Choosing a vault

Because the skills are global, a `/wiki-*` command resolves which vault to act on at run time,
first match wins:

1. **Manifest walk-up.** If your CWD is inside a vault (a `.manifest.json` above you), that vault
   is used. Working inside a vault needs no config at all.
2. **Project map.** Otherwise the project root (git root, else CWD) is looked up in
   `~/.obsidian-wiki/projects.json`, a `{ "project-path": "vault-name" }` map.
3. **Quiz.** With neither, the skill lists the registered vaults and asks you to pick, then saves
   the choice to the project map so it does not ask again.
4. **Headless default.** Non-interactive runs (cron, scripts) fall back to the active global
   `~/.obsidian-wiki/config` symlink.

A vault is *registered* by a `~/.obsidian-wiki/config.<name>` file holding its
`OBSIDIAN_VAULT_PATH`. The `wiki-switch` skill manages the registry, the project map, and the
quiz (`/wiki-switch` with no args re-runs the quiz; `/wiki-switch <name>` maps the current
project; `/wiki-switch list|where|new|forget|default`). None of this lives inside a vault, so
vaults stay relocatable.

## Portability & moving a vault

The setup has two layers with different portability — worth understanding before you
copy or share a vault:

- **Vault content is portable.** Pages, `index.md`, `log.md`, and `.manifest.json` use
  relative paths only, so `cp -r <vault> elsewhere` keeps the wiki fully functional *as
  data*.
- **Tooling is shared, not copied.** The skills, scripts, and conventions live here in
  the repo. Skills are linked once at user level; scripts/conventions/hooks are *symlinked*
  into each vault's `.claude/`. That is deliberate (edit once, every vault updates) but it
  means those links (and the `@.claude/wiki-conventions.md` import in `CLAUDE.md`) only
  resolve where this repo exists at the linked path.

A note on **shared/synced vaults**: WSL symlinks do not replicate as working links through
OneDrive/Dropbox, and `.claude/` is typically gitignored, so the per-vault links are inherently
per-machine. Each person clones this repo and wires the vault on their own machine; only the
vault *content* travels.

So bringing a vault to a **new machine** is: clone this repo, run `./wire-vault.sh --user` once,
then `./wire-vault.sh <vault>` per vault (or the `-User` / `<vault>` `.ps1` forms on Windows).
The same commands repair links that broke for any reason; `--check` (`-Check` on Windows) tells
you whether you need to. The mental model: **vault = data (portable), repo = tooling
(clone-and-link), skills = user-level (link once)**.

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
- `wiki-switch` — register vaults, map a project to a vault, and run the vault-picker quiz
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
