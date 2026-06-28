#Requires -Version 5.1
<#
.SYNOPSIS
  Wire (or repair) the cm-llm-wiki tooling - native Windows. Two independent layers.

.DESCRIPTION
  PowerShell port of wire-vault.sh for users without WSL.

  The wiki *skills* are installed once at USER level (%USERPROFILE%\.claude\skills) and
  shared by every project. A *vault* only needs the tooling referenced from inside it by a
  vault-relative path: the shared conventions (CLAUDE.md does `@.claude/wiki-conventions.md`),
  the maintenance scripts, and the hooks. Skills are NOT linked per-vault anymore.

  Link primitives on Windows:
    - skill dirs, wiki-scripts, hooks (directories) use JUNCTIONS - no admin, no Developer Mode.
    - wiki-conventions.md (a single file) tries a real SYMLINK first (needs Developer Mode or an
      elevated shell) and falls back to a COPY. A copy is a snapshot: edits to the repo source
      won't propagate until you re-run. Enable Developer Mode (or run elevated) for a live link.

.PARAMETER User
  Install/repair the user-level skills (%USERPROFILE%\.claude\skills).

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

# ---------- user-level skills ----------
function Wire-User {
  $skillsDir = Join-Path $env:USERPROFILE '.claude\skills'
  if (-not $Check) { New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null }
  if ($Check -and -not (Test-Path -LiteralPath $skillsDir)) {
    Write-Host "MISSING  ~/.claude/skills (dir absent)"; $script:problems = 1; return
  }
  Get-ChildItem -LiteralPath (Join-Path $Repo 'skills') -Directory | ForEach-Object {
    $name = $_.Name
    Wire-DirLink (Join-Path $skillsDir $name) $_.FullName "~/.claude/skills/$name"
  }
}

# ---------- per-vault tooling (no skills) ----------
function Wire-Vault {
  try { $VaultFull = (Resolve-Path -LiteralPath $Vault).Path }
  catch { Write-Err "vault dir not found: $Vault"; exit 2 }
  $vaultClaude = Join-Path $VaultFull '.claude'
  if (-not $Check) { New-Item -ItemType Directory -Force -Path $vaultClaude | Out-Null }

  Wire-DirLink  (Join-Path $vaultClaude 'wiki-scripts')        (Join-Path $Repo 'scripts')              '.claude/wiki-scripts'
  Wire-DirLink  (Join-Path $vaultClaude 'hooks')               (Join-Path $Repo 'hooks')                '.claude/hooks'
  Wire-FileLink (Join-Path $vaultClaude 'wiki-conventions.md') (Join-Path $Repo 'wiki-conventions.md')  '.claude/wiki-conventions.md'

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
