# cm-llm-wiki

Shared tooling for Obsidian LLM wikis: the `wiki-*` agent skills under `skills/`, the
PEP 723 `uv` scripts under `scripts/`, the hooks under `hooks/`, and the shared
`wiki-conventions.md` that every wired vault imports. `README.md` is the user-facing
tour; `docs/design-notes.md` records why things are the way they are; `scripts/README.md`
documents each script.

## Working here

- Scripts are standalone `uv run --script` files that never import one another; the
  vault resolver and the `is_content_page()` rule are copied verbatim into each one on
  purpose (see design notes). A change
  to shared logic has to touch every copy.
- Run `uv run tests/selftest.py` after changing any script or hook (about 20 s, fixture
  vaults in a temp dir; add a check when you add a behaviour).
- Test against a real vault read-only: `uv run --script scripts/<tool>.py --vault <vault>`.
  Never run `regen-manifest.py` without `--dry-run`, `kebab-rename.py`, or any `--fix`
  against a user's vault unless asked.
- Skills must stay complete for their default path without opening `references/`; mode
  variants go in `references/`, not into `SKILL.md`.
- Vaults are wired by symlink (`wire-vault.sh` / `wire-vault.ps1`), so an edit here is live
  in every vault immediately; re-run `wire-vault.sh <vault>` after editing
  `wiki-conventions.md` so the generated `AGENTS.md` catches up.
- Conventional Commits, no attribution trailers.
