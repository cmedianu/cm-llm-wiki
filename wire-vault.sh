#!/usr/bin/env bash
#
# Wire (or repair) an Obsidian vault to this cm-llm-wiki master repo.
#
# The vault's *content* is self-contained and portable; its *tooling* (skills,
# scripts, shared conventions) lives here in the repo and is symlinked into the
# vault's .claude/. Those symlinks break if the vault is copied to a machine
# where the repo isn't present at the same path. This script re-establishes
# them — so "set up a new vault" and "recover after a move/clone" are the same
# one command.
#
# Usage:
#   ./wire-vault.sh /path/to/vault            wire or repair (idempotent)
#   ./wire-vault.sh --check /path/to/vault    report only, change nothing
#
# Exit 0 if everything is wired (or, in --check, already wired); 1 otherwise.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHECK=0
if [[ "${1:-}" == "--check" ]]; then CHECK=1; shift; fi
VAULT_ARG="${1:-}"
[[ -n "$VAULT_ARG" ]] || { echo "usage: $0 [--check] /path/to/vault" >&2; exit 2; }
VAULT="$(cd "$VAULT_ARG" 2>/dev/null && pwd)" || { echo "vault dir not found: $VAULT_ARG" >&2; exit 2; }

problems=0

# wire_link <name-under-.claude> <repo-target>
wire_link() {
  local name="$1" target="$2" path="$VAULT/.claude/$1"
  if [[ -L "$path" && "$(readlink "$path")" == "$target" ]]; then
    if [[ -e "$path" ]]; then
      echo "ok       .claude/$name"
    else
      echo "DANGLING .claude/$name -> $target  (repo missing at that path?)"; problems=1
    fi
    return
  fi
  if [[ $CHECK -eq 1 ]]; then
    echo "MISSING  .claude/$name -> $target"; problems=1; return
  fi
  ln -sfn "$target" "$path"
  echo "linked   .claude/$name -> $target"
}

[[ $CHECK -eq 1 ]] || mkdir -p "$VAULT/.claude"
wire_link "skills"              "$REPO/skills"
wire_link "wiki-scripts"        "$REPO/scripts"
wire_link "wiki-conventions.md" "$REPO/wiki-conventions.md"

# Vault CLAUDE.md — seed from template only if absent; never overwrite.
if [[ -f "$VAULT/CLAUDE.md" ]]; then
  echo "ok       CLAUDE.md (present, left untouched)"
elif [[ $CHECK -eq 1 ]]; then
  echo "MISSING  CLAUDE.md"; problems=1
else
  cat > "$VAULT/CLAUDE.md" <<EOF
# $(basename "$VAULT")

Shared wiki conventions (filenames, frontmatter, wikilinks, categories, index/log
sync) are imported from the cm-llm-wiki master repo — edit them there, not here:

@.claude/wiki-conventions.md

## This vault's specifics

- (folder taxonomy, private areas, special namespaces — fill in per vault)
EOF
  echo "created  CLAUDE.md (from template — add this vault's specifics)"
fi

if [[ $problems -eq 0 ]]; then
  [[ $CHECK -eq 1 ]] && echo "check: fully wired to $REPO" || echo "done: wired to $REPO"
  exit 0
fi
echo "incomplete — re-run without --check to repair (and make sure the repo exists)." >&2
exit 1
