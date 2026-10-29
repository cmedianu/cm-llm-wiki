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
    # A plain copy counts as wired if identical. A reparse point with no readable
    # target (a WSL symlink - Windows cannot open it) is never a copy: replace it.
    $isLink = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    if (-not $linkTarget -and -not $isLink -and (Test-Path -LiteralPath $target)) {
      $a = Get-FileHash -LiteralPath $path -Algorithm SHA256
      $b = Get-FileHash -LiteralPath $target -Algorithm SHA256
      if ($a.Hash -eq $b.Hash) {
        # Upgrade the copy to a live link when we now can (Developer Mode or an
        # elevated shell): build the link beside it first, so a failure leaves the copy.
        if (-not $Check) {
          $tmp = "$path.wire-tmp"
          try {
            New-Item -ItemType SymbolicLink -Path $tmp -Target $target -ErrorAction Stop | Out-Null
            [IO.File]::Delete($path)
            [IO.File]::Move($tmp, $path)
            Write-Host "linked   $label -> $target (upgraded from copy)"
            return
          } catch {
            if (Test-Path -LiteralPath $tmp) { [IO.File]::Delete($tmp) }
          }
        }
        Write-Host "ok       $label (copy - run once elevated, or enable Developer Mode, then re-run for a live link)"
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

# Windows path -> its WSL (/mnt/c/...) and Git Bash (/c/...) spellings.
function ConvertTo-WslPath([string]$p)     { '/mnt/' + $p.Substring(0, 1).ToLowerInvariant() + ($p.Substring(2) -replace '\\', '/') }
function ConvertTo-GitBashPath([string]$p) { '/' + $p.Substring(0, 1).ToLowerInvariant() + ($p.Substring(2) -replace '\\', '/') }

# Generated git pre-commit shim (see precommit_shim in wire-vault.sh; the content
# must stay byte-identical so the two scripts never rewrite each other's file).
# A real file, not a link: it runs from Git for Windows and from WSL git alike.
function Get-PreCommitShim {
  $lines = @(
    '#!/usr/bin/env bash',
    '# GENERATED by cm-llm-wiki wire-vault - do not edit; re-run wire-vault instead.',
    '# Delegates to the repo pre-commit gate from WSL git or Git for Windows.',
    ('for h in "{0}/hooks/pre-commit" "{1}/hooks/pre-commit"; do' -f (ConvertTo-WslPath $Repo), (ConvertTo-GitBashPath $Repo)),
    '  [ -f "$h" ] && exec bash "$h" "$@"',
    'done',
    'echo "pre-commit: cm-llm-wiki hook not found; skipping wiki checks" >&2',
    'exit 0'
  )
  return (($lines -join "`n") + "`n")
}

# Wire a generated file that may currently be a link - including a WSL symlink,
# which Windows cannot even read. Drop the link first so we never write through
# it into its target (the repo's own hook).
function Wire-GeneratedFileUnlinked([string]$path, [string]$content, [string]$label) {
  if (Test-Path -LiteralPath $path) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      if ($Check) { Write-Host "STALE    $label (is a link; re-run to replace it with a generated file)"; $script:problems = 1; return }
      Remove-LinkPoint $path
    }
  }
  Wire-GeneratedFile $path $content $label
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
    # Prune links to skills this repo no longer ships (retired or merged): only links
    # whose target is under this repo's skills folder and no longer exists.
    $repoSkills = Join-Path $Repo 'skills'
    Get-ChildItem -LiteralPath $skillsDir -Filter 'wiki*' -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.LinkType } | ForEach-Object {
        $tgt = [string]($_.Target | Select-Object -First 1)
        if ($tgt -and $tgt.StartsWith($repoSkills, [StringComparison]::OrdinalIgnoreCase) -and -not (Test-Path -LiteralPath $tgt)) {
          if ($Check) { Write-Host "STALE    ~/$($destRel -replace '\\','/')/$($_.Name) -> retired skill"; $script:problems = 1 }
          else { Remove-Item -LiteralPath $_.FullName -Force; Write-Host "removed  ~/$($destRel -replace '\\','/')/$($_.Name) (skill retired)" }
        }
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

  # Git pre-commit gate (frontmatter validation + errors-only lint) - only when the
  # vault is a git repo. The gitdir may sit outside the vault via a `gitdir:` pointer
  # file (e.g. parked under ~\gitdirs to keep it out of OneDrive sync), so ask git.
  $gitdir = $null
  if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitdir = (& git -C $VaultFull rev-parse --absolute-git-dir 2>$null)
    if ($LASTEXITCODE -ne 0) { $gitdir = $null }
  }
  if ($gitdir) {
    $hooksDir = Join-Path ($gitdir -replace '/', '\') 'hooks'
    if (-not $Check) { New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null }
    Wire-GeneratedFileUnlinked (Join-Path $hooksDir 'pre-commit') (Get-PreCommitShim) 'gitdir/hooks/pre-commit'
    # core.hooksPath makes git ignore gitdir/hooks, so the gate would never run (see wire-vault.sh).
    $hp = (& git -C $VaultFull config core.hooksPath 2>$null)
    if ($hp) {
      $hpHook = Join-Path ($hp -replace '/', '\') 'pre-commit'
      $hasGate = (Test-Path -LiteralPath $hpHook) -and (Select-String -LiteralPath $hpHook -Pattern 'cm-llm-wiki' -Quiet)
      if (-not $hasGate) {
        Write-Host "BYPASSED pre-commit: core.hooksPath=$hp, so git skips gitdir/hooks and the wiki gate never runs. Unset it (git -C `"$VaultFull`" config --unset core.hooksPath) or call the gate from $hp/pre-commit"
        $script:problems = 1
      }
    }
  } else {
    Write-Host "ok       pre-commit (vault is not a git repo; nothing to wire)"
  }

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

  # Generated files stay out of a git-managed vault (see wire-vault.sh for the why).
  if (Get-Command git -ErrorAction SilentlyContinue) {
    & git -C $VaultFull rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -eq 0) {
      $gi = Join-Path $VaultFull '.gitignore'
      $lines = @(); if (Test-Path -LiteralPath $gi) { $lines = Get-Content -LiteralPath $gi }
      foreach ($pat in @('/AGENTS.md', '/.codex/')) {
        $bare = $pat.TrimStart('/')
        if ($lines -contains $pat -or $lines -contains $bare) {
          Write-Host "ok       .gitignore has $pat"
        } elseif ($Check) {
          Write-Host "STALE    .gitignore lacks $pat (generated file)"; $script:problems = 1
        } else {
          Add-Content -LiteralPath $gi -Value $pat
          Write-Host "added    $pat to .gitignore (generated file)"
        }
      }
      & git -C $VaultFull ls-files --error-unmatch AGENTS.md *> $null
      if ($LASTEXITCODE -eq 0) {
        Write-Host "NOTE     AGENTS.md is still tracked; untrack it once: git -C `"$VaultFull`" rm --cached AGENTS.md"
      }
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
  $codexFile = Join-Path $vaultCodex 'hooks.json'
  $codexContent = (($codexJson -replace "`r`n", "`n")) + "`n"
  # A vault shared with WSL can hold only one of the two absolute paths; accept the
  # /mnt/<drive>/ form wire-vault.sh wrote instead of flip-flopping it.
  $wslHook = (ConvertTo-WslPath (Join-Path $Repo 'hooks\update-timestamp.py'))
  $wslContent = $codexContent.Replace($hookScript, $wslHook)
  if ((Test-Path -LiteralPath $codexFile) -and ([IO.File]::ReadAllText($codexFile) -eq $wslContent)) {
    Write-Host "ok       .codex/hooks.json (WSL path, written by wire-vault.sh)"
  } else {
    Wire-GeneratedFile $codexFile $codexContent '.codex/hooks.json'
  }

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
