# Copilot CLI repo hooks

A vault's `.github/hooks` is symlinked to this dir by `wire-vault.sh`.

- `wiki-update-timestamp.json` — PostToolUse hook that stamps `updated:` on edited
  pages. The PascalCase event name (`PostToolUse`) selects the Claude-compatible
  payload format and matcher semantics, so `hooks/update-timestamp.py` sees the same
  JSON shape Claude Code sends. `cwd: "."` resolves to the repo (vault) root.

**Do not put a pseudo-comment key (`//`, `NOTE`, …) inside the hook JSON.** These
configs are parsed by strict schemas — Codex's `hooks.json` rejects any unknown
top-level key with `unknown field`, and the same trap can bite Copilot. Keep notes
here in this README, not in the JSON.
