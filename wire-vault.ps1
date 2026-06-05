#Requires -Version 5.1
<#
.SYNOPSIS
  Wire (or repair) an Obsidian vault to this cm-llm-wiki master repo - native Windows.

.DESCRIPTION
  PowerShell port of wire-vault.sh for users without WSL. The vault's *content* is
  self-contained and portable; its *tooling* (skills, scripts, shared conventions) lives
  here in the repo and is linked into the vault's .claude/. Those links break if the vault
  is copied to a machine where the repo isn't present at the same path. This script
  re-establishes them - so "set up a new vault" and "recover after a move/clone" are the
  same one command.

  Link primitives on Windows:
    - skills, wiki-scripts (directories) use JUNCTIONS - no admin, no Developer Mode.
    - wiki-conventions.md (a single file) tries a real SYMLINK first (needs Developer Mode
      or an elevated shell) and falls back to a COPY if that privilege is unavailable. The
      copy is a snapshot: edits to the repo's wiki-conventions.md won't propagate until you
      re-run this script. Enable Developer Mode (or run elevated) and re-wire for a live link.

.PARAMETER Check
  Report only - change nothing. Exit 0 if already wired, 1 otherwise.

.PARAMETER Vault
  Path to the Obsidian vault to wire or repair.

.EXAMPLE
  .\wire-vault.ps1 C:\path\to\vault            # wire or repair (idempotent)

.EXAMPLE
  .\wire-vault.ps1 -Check C:\path\to\vault     # report only, change nothing
#>
[CmdletBinding()]
param(
  [switch]$Check,
  [Parameter(Position = 0)]
  [string]$Vault
)

$ErrorActionPreference = 'Stop'   # mirror `set -e`

function Write-Err([string]$msg) { [Console]::Error.WriteLine($msg) }

$Repo = $PSScriptRoot             # mirror BASH_SOURCE -> repo root

# --- argument guards (exit 2) ---
if (-not $Vault) {
  Write-Err "usage: wire-vault.ps1 [-Check] <path-to-vault>"
  exit 2
}
try {
  $VaultFull = (Resolve-Path -LiteralPath $Vault).Path
} catch {
  Write-Err "vault dir not found: $Vault"
  exit 2
}

$vaultClaude = Join-Path $VaultFull '.claude'
$script:problems = 0

# Normalize a path for comparison: full path, trimmed trailing separator, lowercased.
function Normalize-Path([string]$p) {
  if (-not $p) { return '' }
  return ($p.TrimEnd('\', '/')).ToLowerInvariant()
}

# Delete an existing item at $path whether it's a reparse point (junction/symlink) or a
# plain file/dir - without ever recursing into a junction's target.
function Remove-LinkPoint([string]$path) {
  $item = Get-Item -LiteralPath $path -Force
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    if ($item.PSIsContainer) { [IO.Directory]::Delete($path) }   # junction/dir symlink
    else { [IO.File]::Delete($path) }                            # file symlink
  } elseif ($item.PSIsContainer) {
    [IO.Directory]::Delete($path, $true)
  } else {
    [IO.File]::Delete($path)
  }
}

# wire_link for a DIRECTORY target -> junction (no privilege required).
function Wire-DirLink([string]$name, [string]$target) {
  $path = Join-Path $vaultClaude $name
  if (Test-Path -LiteralPath $path) {
    $item = Get-Item -LiteralPath $path -Force
    $linkTarget = $item.Target
    if ($linkTarget -and (Normalize-Path $linkTarget) -eq (Normalize-Path $target)) {
      if (Test-Path -LiteralPath $target) {
        Write-Host "ok       .claude/$name"
      } else {
        Write-Host "DANGLING .claude/$name -> $target  (repo missing at that path?)"
        $script:problems = 1
      }
      return
    }
  }
  if ($Check) {
    Write-Host "MISSING  .claude/$name -> $target"
    $script:problems = 1
    return
  }
  if (Test-Path -LiteralPath $path) { Remove-LinkPoint $path }
  New-Item -ItemType Junction -Path $path -Target $target | Out-Null
  Write-Host "linked   .claude/$name -> $target"
}

# wire_link for a single FILE target -> symlink, falling back to a copy.
function Wire-FileLink([string]$name, [string]$target) {
  $path = Join-Path $vaultClaude $name
  if (Test-Path -LiteralPath $path) {
    $item = Get-Item -LiteralPath $path -Force
    $linkTarget = $item.Target
    if ($linkTarget -and (Normalize-Path $linkTarget) -eq (Normalize-Path $target)) {
      if (Test-Path -LiteralPath $target) {
        Write-Host "ok       .claude/$name"
      } else {
        Write-Host "DANGLING .claude/$name -> $target  (repo missing at that path?)"
        $script:problems = 1
      }
      return
    }
    # Plain-file copy whose content already matches the repo source = wired (degraded).
    if (-not $linkTarget -and (Test-Path -LiteralPath $target)) {
      $a = Get-FileHash -LiteralPath $path -Algorithm SHA256
      $b = Get-FileHash -LiteralPath $target -Algorithm SHA256
      if ($a.Hash -eq $b.Hash) {
        Write-Host "ok       .claude/$name (copy - re-run for a live link if Developer Mode is on)"
        return
      }
    }
  }
  if ($Check) {
    Write-Host "MISSING  .claude/$name -> $target"
    $script:problems = 1
    return
  }
  if (Test-Path -LiteralPath $path) { Remove-LinkPoint $path }
  try {
    New-Item -ItemType SymbolicLink -Path $path -Target $target -ErrorAction Stop | Out-Null
    Write-Host "linked   .claude/$name -> $target"
  } catch {
    Copy-Item -LiteralPath $target -Destination $path
    Write-Host "copied   .claude/$name (no symlink privilege - enable Developer Mode or run elevated, then re-run for a live link)"
  }
}

# --- main flow (mirror wire-vault.sh:47-71) ---
if (-not $Check) { New-Item -ItemType Directory -Force -Path $vaultClaude | Out-Null }
Wire-DirLink  'skills'              (Join-Path $Repo 'skills')
Wire-DirLink  'wiki-scripts'        (Join-Path $Repo 'scripts')
Wire-FileLink 'wiki-conventions.md' (Join-Path $Repo 'wiki-conventions.md')

# Vault CLAUDE.md - seed from template only if absent; never overwrite.
$claudeMd = Join-Path $VaultFull 'CLAUDE.md'
if (Test-Path -LiteralPath $claudeMd) {
  Write-Host "ok       CLAUDE.md (present, left untouched)"
} elseif ($Check) {
  Write-Host "MISSING  CLAUDE.md"
  $script:problems = 1
} else {
  $vaultName = Split-Path $VaultFull -Leaf
  $template = @"
# $vaultName

Shared wiki conventions (filenames, frontmatter, wikilinks, categories, index/log
sync) are imported from the cm-llm-wiki master repo - edit them there, not here:

@.claude/wiki-conventions.md

## This vault's specifics

- (folder taxonomy, private areas, special namespaces - fill in per vault)
"@
  [IO.File]::WriteAllText($claudeMd, ($template -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
  Write-Host "created  CLAUDE.md (from template - add this vault's specifics)"
}

if ($script:problems -eq 0) {
  if ($Check) { Write-Host "check: fully wired to $Repo" } else { Write-Host "done: wired to $Repo" }
  exit 0
}
Write-Err "incomplete - re-run without -Check to repair (and make sure the repo exists)."
exit 1
