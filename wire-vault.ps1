#Requires -Version 5.1
<#
.SYNOPSIS
  Wire (or repair) the cm-llm-wiki tooling - native Windows. Two independent layers, three agents.

.DESCRIPTION
  PowerShell port of wire-vault.sh for users without WSL.

  The tooling serves Claude Code, Codex CLI, and Copilot CLI from one canonical copy.
  The wiki *skills* are installed once at USER level and shared by every project:
  Claude Code reads %USERPROFILE%\.claude\skills, Codex and Copilot read the
  cross-agent standard %USERPROFILE%\.agents\skills - each skill is linked into both.
  A *vault* carries the tooling referenced from inside it by a vault-relative path:
  the shared conventions, the maintenance scripts, the hooks, plus two per-agent
  artifacts that cannot be links - a generated AGENTS.md (Codex has no @-import, so
  the conventions are inlined by scripts/sync-agents.py) and a generated
  .codex\hooks.json (needs an absolute path). Skills are NOT linked per-vault.

  Link primitives on Windows:
    - skill dirs, wiki-scripts, hooks, .github\hooks (directories) use JUNCTIONS -
      no admin, no Developer Mode.
    - wiki-conventions.md (a single file) tries a real SYMLINK first (needs Developer
      Mode or an elevated shell) and falls back to a COPY. A copy is a snapshot: edits
      to the repo source won't propagate until you re-run.

  Note: the Copilot timestamp hook runs through bash, so on native Windows (no WSL)
  it is wired but inert; Claude Code and Codex hooks work everywhere `uv` does.

.PARAMETER User
  Install/repair the user-level skills (.claude\skills and .agents\skills).

.PARAMETER Check
  Report only - change nothing. Exit 0 if already wired, 1 otherwise.

.PARAMETER Vault
  Path to the Obsidian vault to wire or repair (tooling only, no skills).

.EXAMPLE
  .\wire-vault.ps1 -User                       # install/repair user-level skills
.EXAMPLE
  .\wire-vault.ps1 C:\path\to\vault            # wire/repair a vault's tooling
.EXAMPLE
  .\wire-vault.ps1 -Check C:\path\to\vault     # report only
#>
[CmdletBinding()]
param(
  [switch]$User,
  [switch]$Check,
  [Parameter(Position = 0)]
  [string]$Vault
)

$ErrorActionPreference = 'Stop'   # mirror `set -e`

function Write-Err([string]$msg) { [Console]::Error.WriteLine($msg) }

$Repo = $PSScriptRoot
$script:problems = 0

# --- argument guard (exit 2) ---
if (-not $User -and -not $Vault) {
  Write-Err "usage: wire-vault.ps1 -User [-Check] | [-Check] <path-to-vault>"
  exit 2
}

function Normalize-Path([string]$p) {
  if (-not $p) { return '' }
  return ($p.TrimEnd('\', '/')).ToLowerInvariant()
}

# All Python in this repo runs through uv (PEP 723 scripts), never a bare python.
function Test-Uv {
  return [bool](Get-Command uv -ErrorAction SilentlyContinue)
}

# Delete an item whether reparse point (junction/symlink) or plain file/dir,
# without ever recursing into a junction's target.
function Remove-LinkPoint([string]$path) {
  $item = Get-Item -LiteralPath $path -Force
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    if ($item.PSIsContainer) { [IO.Directory]::Delete($path) }
    else { [IO.File]::Delete($path) }
  } elseif ($item.PSIsContainer) {
    [IO.Directory]::Delete($path, $true)
  } else {
    [IO.File]::Delete($path)
  }
}

# DIRECTORY target -> junction (no privilege required). $path is a full destination path.
function Wire-DirLink([string]$path, [string]$target, [string]$label) {
  if (Test-Path -LiteralPath $path) {
    $item = Get-Item -LiteralPath $path -Force
    $linkTarget = $item.Target
    if ($linkTarget -and (Normalize-Path $linkTarget) -eq (Normalize-Path $target)) {
      if (Test-Path -LiteralPath $target) { Write-Host "ok       $label" }
      else { Write-Host "DANGLING $label -> $target  (source missing at that path?)"; $script:problems = 1 }
      return
    }
  }
  if ($Check) { Write-Host "MISSING  $label -> $target"; $script:problems = 1; return }
  if (Test-Path -LiteralPath $path) { Remove-LinkPoint $path }
  New-Item -ItemType Junction -Path $path -Target $target | Out-Null
  Write-Host "linked   $label -> $target"
}

# Single FILE target -> symlink, falling back to a copy. $path is a full destination path.
function Wire-FileLink([string]$path, [string]$target, [string]$label) {
  if (Test-Path -LiteralPath $path) {
    $item = Get-Item -LiteralPath $path -Force
    $linkTarget = $item.Target
    if ($linkTarget -and (Normalize-Path $linkTarget) -eq (Normalize-Path $target)) {
      if (Test-Path -LiteralPath $target) { Write-Host "ok       $label" }
      else { Write-Host "DANGLING $label -> $target  (source missing at that path?)"; $script:problems = 1 }
      return
    }
    if (-not $linkTarget -and (Test-Path -LiteralPath $target)) {
      $a = Get-FileHash -LiteralPath $path -Algorithm SHA256
      $b = Get-FileHash -LiteralPath $target -Algorithm SHA256
      if ($a.Hash -eq $b.Hash) {
        Write-Host "ok       $label (copy - re-run for a live link if Developer Mode is on)"
        return
      }
    }
  }
  if ($Check) { Write-Host "MISSING  $label -> $target"; $script:problems = 1; return }
  if (Test-Path -LiteralPath $path) { Remove-LinkPoint $path }
  try {
    New-Item -ItemType SymbolicLink -Path $path -Target $target -ErrorAction Stop | Out-Null
    Write-Host "linked   $label -> $target"
  } catch {
    Copy-Item -LiteralPath $target -Destination $path
    Write-Host "copied   $label (no symlink privilege - enable Developer Mode or run elevated, then re-run)"
  }
}

# Generated file -> write only on change (mirror of wire-vault.sh put_file).
function Wire-GeneratedFile([string]$path, [string]$content, [string]$label) {
  if (Test-Path -LiteralPath $path) {
    $have = [IO.File]::ReadAllText($path)
    if ($have -eq $content) { Write-Host "ok       $label"; return }
  }
  if ($Check) {
    if (Test-Path -LiteralPath $path) { Write-Host "STALE    $label" } else { Write-Host "MISSING  $label" }
    $script:problems = 1; return
  }
  [IO.File]::WriteAllText($path, $content, (New-Object Text.UTF8Encoding($false)))
  Write-Host "wrote    $label"
}

# ---------- user-level skills (.claude\skills + .agents\skills) ----------
function Wire-User {
  foreach ($destRel in @('.claude\skills', '.agents\skills')) {
    $skillsDir = Join-Path $env:USERPROFILE $destRel
    if (-not $Check) { New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null }
    if ($Check -and -not (Test-Path -LiteralPath $skillsDir)) {
      Write-Host "MISSING  ~/$($destRel -replace '\\','/') (dir absent)"; $script:problems = 1; continue
    }
    Get-ChildItem -LiteralPath (Join-Path $Repo 'skills') -Directory | ForEach-Object {
      $name = $_.Name
      Wire-DirLink (Join-Path $skillsDir $name) $_.FullName "~/$($destRel -replace '\\','/')/$name"
    }
  }
}

# ---------- per-vault tooling (no skills) ----------
function Wire-Vault {
  try { $VaultFull = (Resolve-Path -LiteralPath $Vault).Path }
  catch { Write-Err "vault dir not found: $Vault"; exit 2 }
  $vaultClaude = Join-Path $VaultFull '.claude'
  $vaultGithub = Join-Path $VaultFull '.github'
  $vaultCodex  = Join-Path $VaultFull '.codex'
  if (-not $Check) {
    New-Item -ItemType Directory -Force -Path $vaultClaude, $vaultGithub, $vaultCodex | Out-Null
  }

  Wire-DirLink  (Join-Path $vaultClaude 'wiki-scripts')        (Join-Path $Repo 'scripts')              '.claude/wiki-scripts'
  Wire-DirLink  (Join-Path $vaultClaude 'hooks')               (Join-Path $Repo 'hooks')                '.claude/hooks'
  Wire-FileLink (Join-Path $vaultClaude 'wiki-conventions.md') (Join-Path $Repo 'wiki-conventions.md')  '.claude/wiki-conventions.md'
  Wire-DirLink  (Join-Path $vaultGithub 'hooks')               (Join-Path $Repo 'hooks\copilot')        '.github/hooks'

  # Stray wiki-* skills are the OLD per-vault model; a skills dir with only non-wiki skills is fine.
  $staleSkills = Join-Path $vaultClaude 'skills'
  if (Test-Path -LiteralPath $staleSkills) {
    $stale = Get-ChildItem -LiteralPath $staleSkills -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'wiki*' }
    if ($stale) {
      Write-Host ("STALE    .claude/skills has wiki entries (skills are user-level now); remove: " + ($stale.Name -join ', '))
      $script:problems = 1
    }
  }

  $claudeMd = Join-Path $VaultFull 'CLAUDE.md'
  if (Test-Path -LiteralPath $claudeMd) {
    Write-Host "ok       CLAUDE.md (present, left untouched)"
  } elseif ($Check) {
    Write-Host "MISSING  CLAUDE.md"; $script:problems = 1
  } else {
    $vaultName = Split-Path $VaultFull -Leaf
    $template = @"
# $vaultName

Shared wiki conventions (filenames, frontmatter, wikilinks, categories, index/log
sync) are imported from the cm-llm-wiki master repo, edit them there, not here:

@.claude/wiki-conventions.md

## This vault's specifics

- (folder taxonomy, private areas, special namespaces; fill in per vault)
"@
    [IO.File]::WriteAllText($claudeMd, ($template -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    Write-Host "created  CLAUDE.md (from template; add this vault's specifics)"
  }

  # AGENTS.md for Codex/Copilot - generated from CLAUDE.md (imports inlined).
  if (Test-Path -LiteralPath $claudeMd) {
    if (Test-Uv) {
      $syncArgs = @('run', '--script', (Join-Path $Repo 'scripts\sync-agents.py'))
      if ($Check) { $syncArgs += '--check' }
      $syncArgs += $VaultFull
      & uv @syncArgs
      if ($LASTEXITCODE -ne 0) { $script:problems = 1 }
    } else {
      Write-Host "SKIPPED  AGENTS.md (no uv on PATH - install uv, then re-run)"
      $script:problems = 1
    }
  }

  # Codex CLI: project hooks config - generated, not linked, because the command
  # needs an absolute path. Trust it once via /hooks inside Codex in this vault.
  $hookScript = (Join-Path $Repo 'hooks\update-timestamp.py') -replace '\\', '\\'
  # NOTE: Codex's hooks.json schema is strict (deny_unknown_fields) — the ONLY
  # allowed top-level key is "hooks". Do NOT add a "//" or "NOTE" pseudo-comment
  # key to the emitted JSON; Codex fails with "unknown field". Keep provenance in
  # this script comment, not in the file. This file is GENERATED — re-run wire-vault.ps1.
  $codexJson = @"
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "apply_patch",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --script \"$hookScript\"",
            "timeout": 15,
            "statusMessage": "Stamping updated: on edited pages"
          }
        ]
      }
    ]
  }
}
"@
  Wire-GeneratedFile (Join-Path $vaultCodex 'hooks.json') ((($codexJson -replace "`r`n", "`n")) + "`n") '.codex/hooks.json'

  # Claude Code: the timestamp hook is registered in the VAULT's settings.json
  # (that is what scopes it to this vault). Seed if absent; never rewrite.
  $settings = Join-Path $vaultClaude 'settings.json'
  if (Test-Path -LiteralPath $settings) {
    if (Select-String -LiteralPath $settings -Pattern 'update-timestamp\.py' -Quiet) {
      Write-Host "ok       .claude/settings.json (hook registered)"
    } else {
      Write-Host "STALE    .claude/settings.json exists but lacks the update-timestamp hook; add the PostToolUse block (see hooks/update-timestamp.py docstring)"
      $script:problems = 1
    }
  } elseif ($Check) {
    Write-Host "MISSING  .claude/settings.json"; $script:problems = 1
  } else {
    $settingsJson = @'
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
'@
    [IO.File]::WriteAllText($settings, (($settingsJson -replace "`r`n", "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
    Write-Host "created  .claude/settings.json (update-timestamp hook)"
  }
}

# ---------- dispatch ----------
if ($User)  { Wire-User }
if ($Vault) { Wire-Vault }

if ($script:problems -eq 0) {
  if ($Check) { Write-Host "check: fully wired" } else { Write-Host "done" }
  exit 0
}
Write-Err "incomplete - re-run without -Check to repair (and make sure the repo exists)."
exit 1
