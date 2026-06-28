#!/usr/bin/env bash
#
# Wire (or repair) the cm-llm-wiki tooling - two independent layers.
#
# The wiki *skills* are now installed once at USER level (~/.claude/skills) and
# are shared by every project, wiki or not. A *vault* only needs the tooling that
# is referenced from inside it by a vault-relative path: the shared conventions
# (CLAUDE.md does `@.claude/wiki-conventions.md`), the maintenance scripts, and
# the hooks. Skills are NOT linked per-vault anymore.
#
# Usage:
#   ./wire-vault.sh --user                     install/repair user-level skills (~/.claude/skills)
#   ./wire-vault.sh --user --check             report only
#   ./wire-vault.sh /path/to/vault             wire/repair a vault's tooling (idempotent)
#   ./wire-vault.sh --check /path/to/vault     report only, change nothing
#
# A fresh machine needs both: `--user` once, then one vault run per vault.
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
  rm -rf "$path"           # drop a stale copy or wrong link (path is always under .claude/ or ~/.claude/skills/)
  ln -sfn "$target" "$path"
  echo "linked   $label -> $target"
}

# ---------- user-level skills (~/.claude/skills) ----------
wire_user() {
  local skills_dir="$HOME/.claude/skills"
  [[ $CHECK -eq 1 ]] || mkdir -p "$skills_dir"
  if [[ $CHECK -eq 1 && ! -d "$skills_dir" ]]; then
    echo "MISSING  ~/.claude/skills (dir absent)"; problems=1; return
  fi
  local d name
  for d in "$REPO"/skills/*/; do
    name="$(basename "$d")"
    link "$skills_dir/$name" "$REPO/skills/$name" "~/.claude/skills/$name"
  done
}

# ---------- per-vault tooling (no skills) ----------
wire_vault() {
  local vault
  vault="$(cd "$VAULT_ARG" 2>/dev/null && pwd)" || { echo "vault dir not found: $VAULT_ARG" >&2; exit 2; }
  [[ $CHECK -eq 1 ]] || mkdir -p "$vault/.claude"

  link "$vault/.claude/wiki-scripts"        "$REPO/scripts"              ".claude/wiki-scripts"
  link "$vault/.claude/wiki-conventions.md" "$REPO/wiki-conventions.md" ".claude/wiki-conventions.md"
  link "$vault/.claude/hooks"               "$REPO/hooks"               ".claude/hooks"

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
