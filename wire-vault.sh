#!/usr/bin/env bash
#
# Wire (or repair) the cm-llm-wiki tooling - two independent layers, three agents.
#
# The tooling serves Claude Code, Codex CLI, and Copilot CLI from one canonical
# copy. The wiki *skills* are installed once at USER level and shared by every
# project, wiki or not: Claude Code reads `~/.claude/skills`, Codex and Copilot
# read the cross-agent standard `~/.agents/skills`; each skill is symlinked
# into both. A *vault* carries the tooling referenced from inside it by a
# vault-relative path: the shared conventions, the maintenance scripts, the
# hooks, plus two per-agent artifacts that cannot be symlinks: a generated
# AGENTS.md (Codex has no @-import, so the conventions are inlined by
# scripts/sync-agents.py) and a generated .codex/hooks.json (needs an absolute
# path). Skills are NOT linked per-vault.
#
# Usage:
#   ./wire-vault.sh --user                     install/repair user-level skills
#   ./wire-vault.sh --user --check             report only
#   ./wire-vault.sh /path/to/vault             wire/repair a vault's tooling (idempotent)
#   ./wire-vault.sh --check /path/to/vault     report only, change nothing
#
# A fresh machine needs both: `--user` once, then one vault run per vault.
# After editing wiki-conventions.md or a vault's CLAUDE.md, re-run the vault
# step (or `scripts/sync-agents.py --all`) so each generated AGENTS.md catches up.
# Exit 0 if everything is wired (or already wired in --check); 1 otherwise.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHECK=0
USER_MODE=0
VAULT_ARG=""
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --user)  USER_MODE=1 ;;
    -*)      echo "unknown option: $arg" >&2; exit 2 ;;
    *)       VAULT_ARG="$arg" ;;
  esac
done

problems=0

# link <link-path> <target> [label]  - idempotent symlink (works for files and dirs).
link() {
  local path="$1" target="$2" label="${3:-$1}"
  if [[ -L "$path" && "$(readlink "$path")" == "$target" ]]; then
    if [[ -e "$path" ]]; then echo "ok       $label"
    else echo "DANGLING $label -> $target  (source missing at that path?)"; problems=1; fi
    return
  fi
  if [[ $CHECK -eq 1 ]]; then echo "MISSING  $label -> $target"; problems=1; return; fi
  rm -rf "$path"           # drop a stale copy or wrong link (path is always under .claude/, .github/, ~/.claude/skills/, or ~/.agents/skills/)
  ln -sfn "$target" "$path"
  echo "linked   $label -> $target"
}

# put_file <path> <content> <label>  - idempotent generated file (write only on change).
put_file() {
  local path="$1" content="$2" label="$3"
  if [[ -f "$path" && "$(cat "$path")" == "$content" ]]; then
    echo "ok       $label"
    return
  fi
  if [[ $CHECK -eq 1 ]]; then
    if [[ -f "$path" ]]; then echo "STALE    $label"; else echo "MISSING  $label"; fi
    problems=1; return
  fi
  printf '%s\n' "$content" > "$path"
  echo "wrote    $label"
}

# ---------- user-level skills (~/.claude/skills + ~/.agents/skills) ----------
wire_user() {
  local dest d name
  for dest in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
    [[ $CHECK -eq 1 ]] || mkdir -p "$dest"
    if [[ $CHECK -eq 1 && ! -d "$dest" ]]; then
      echo "MISSING  $dest (dir absent)"; problems=1; continue
    fi
    for d in "$REPO"/skills/*/; do
      name="$(basename "$d")"
      link "$dest/$name" "$REPO/skills/$name" "${dest/#$HOME/\~}/$name"
    done
  done
}

# ---------- per-vault tooling (no skills) ----------
wire_vault() {
  local vault
  vault="$(cd "$VAULT_ARG" 2>/dev/null && pwd)" || { echo "vault dir not found: $VAULT_ARG" >&2; exit 2; }
  [[ $CHECK -eq 1 ]] || mkdir -p "$vault/.claude" "$vault/.github" "$vault/.codex"

  # Shared tooling, symlinked (Claude Code reads these; Codex/Copilot reach the
  # same scripts through the paths referenced in AGENTS.md and the hook configs).
  link "$vault/.claude/wiki-scripts"        "$REPO/scripts"              ".claude/wiki-scripts"
  link "$vault/.claude/wiki-conventions.md" "$REPO/wiki-conventions.md" ".claude/wiki-conventions.md"
  link "$vault/.claude/hooks"               "$REPO/hooks"               ".claude/hooks"

  # Copilot CLI: repo-level hooks dir; the JSON inside uses vault-relative paths,
  # so the whole dir can be a symlink into the repo.
  link "$vault/.github/hooks"               "$REPO/hooks/copilot"       ".github/hooks"

  # Stray wiki-* skills under .claude/skills are the OLD per-vault model; skills are user-level now.
  # (A .claude/skills holding only non-wiki skills, e.g. docx/pdf, is fine and left alone.)
  if [[ -d "$vault/.claude/skills" ]]; then
    local stale; stale=$(ls "$vault/.claude/skills" 2>/dev/null | grep -E '^wiki' | tr '\n' ' ' || true)
    if [[ -n "$stale" ]]; then
      echo "STALE    .claude/skills has wiki entries (skills are user-level now); remove: $stale"; problems=1
    fi
  fi

  # Vault CLAUDE.md - seed from template only if absent; never overwrite.
  if [[ -f "$vault/CLAUDE.md" ]]; then
    echo "ok       CLAUDE.md (present, left untouched)"
  elif [[ $CHECK -eq 1 ]]; then
    echo "MISSING  CLAUDE.md"; problems=1
  else
    cat > "$vault/CLAUDE.md" <<EOF
# $(basename "$vault")

Shared wiki conventions (filenames, frontmatter, wikilinks, categories, index/log
sync) are imported from the cm-llm-wiki master repo, edit them there, not here:

@.claude/wiki-conventions.md

## This vault's specifics

- (folder taxonomy, private areas, special namespaces; fill in per vault)
EOF
    echo "created  CLAUDE.md (from template; add this vault's specifics)"
  fi

  # AGENTS.md for Codex/Copilot - generated from CLAUDE.md (imports inlined).
  # All Python here runs through uv (PEP 723 scripts), never a bare python3.
  if [[ -f "$vault/CLAUDE.md" ]]; then
    local sync_flags=()
    [[ $CHECK -eq 1 ]] && sync_flags+=(--check)
    if ! uv run --script "$REPO/scripts/sync-agents.py" ${sync_flags[@]+"${sync_flags[@]}"} "$vault"; then
      problems=1
    fi
  fi

  # Codex CLI: project hooks config - generated, not linked, because the command
  # needs an absolute path (Codex resolves hook commands against the session cwd,
  # which is not necessarily the vault root). Codex asks once to trust it: run
  # /hooks inside Codex in this vault the first time.
  # NOTE: Codex's hooks.json schema is strict (deny_unknown_fields) — the ONLY
  # allowed top-level key is "hooks". Do NOT add a "//" or "NOTE" pseudo-comment
  # key to the emitted JSON; Codex fails with "unknown field". Keep provenance in
  # this script comment, not in the file. This file is GENERATED — re-run wire-vault.sh.
  local codex_hooks
  codex_hooks=$(cat <<EOF
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "apply_patch",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --script \\"$REPO/hooks/update-timestamp.py\\"",
            "timeout": 15,
            "statusMessage": "Stamping updated: on edited pages"
          }
        ]
      }
    ]
  }
}
EOF
)
  put_file "$vault/.codex/hooks.json" "$codex_hooks" ".codex/hooks.json"

  # Claude Code: the timestamp hook is registered in the VAULT's settings.json
  # (that is what scopes it to this vault). Seed if absent; never rewrite.
  local settings="$vault/.claude/settings.json"
  if [[ -f "$settings" ]]; then
    if grep -q "update-timestamp.py" "$settings"; then
      echo "ok       .claude/settings.json (hook registered)"
    else
      echo "STALE    .claude/settings.json exists but lacks the update-timestamp hook; add the PostToolUse block (see hooks/update-timestamp.py docstring)"
      problems=1
    fi
  elif [[ $CHECK -eq 1 ]]; then
    echo "MISSING  .claude/settings.json"; problems=1
  else
    cat > "$settings" <<'EOF'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --script \"$CLAUDE_PROJECT_DIR/.claude/hooks/update-timestamp.py\""
          }
        ]
      }
    ]
  }
}
EOF
    echo "created  .claude/settings.json (update-timestamp hook)"
  fi
}

# ---------- dispatch ----------
if [[ $USER_MODE -eq 0 && -z "$VAULT_ARG" ]]; then
  echo "usage: $0 --user [--check] | [--check] /path/to/vault" >&2
  exit 2
fi
[[ $USER_MODE -eq 1 ]] && wire_user
[[ -n "$VAULT_ARG" ]] && wire_vault

if [[ $problems -eq 0 ]]; then
  [[ $CHECK -eq 1 ]] && echo "check: fully wired" || echo "done"
  exit 0
fi
echo "incomplete - re-run without --check to repair (and make sure the repo exists)." >&2
exit 1
