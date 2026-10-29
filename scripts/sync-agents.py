#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a vault's AGENTS.md from its CLAUDE.md by expanding @-imports.

Why this exists: Claude Code pulls the shared wiki conventions into every vault
live, through the `@.claude/wiki-conventions.md` import in the vault's CLAUDE.md.
Codex CLI (and other AGENTS.md readers) have no import mechanism: an `@path`
line reaches the model as literal text. So each vault carries a *generated*
AGENTS.md: CLAUDE.md with every import physically inlined. CLAUDE.md stays the
hand-edited master; AGENTS.md is a build artifact of it.

Usage:
  sync-agents.py                 sync the auto-detected vault (see --vault chain)
  sync-agents.py VAULT [...]     sync the given vault dir(s)
  sync-agents.py --vault PATH    sync the vault at PATH (standard resolver override)
  sync-agents.py --all           sync every vault registered in ~/.obsidian-wiki
  sync-agents.py --check [...]   report stale/missing AGENTS.md, change nothing

Exit 0 = everything in sync (or synced); 1 = --check found drift or a vault
had no CLAUDE.md. Writes only when content changed, so cloud-sync churn stays
minimal. If Obsidian's "Update time on edit" plugin has prepended a YAML
frontmatter block to AGENTS.md (it stamps any .md in the vault), that block is
preserved on rewrite and ignored for drift detection, so the two writers never
fight. Stdlib-only, any Python 3.
"""
import os
import re
import sys
import json
import pathlib
from typing import Optional

BANNER = (
    "<!-- GENERATED FILE - DO NOT EDIT.\n"
    "     Source:    CLAUDE.md in this vault, with its @-imports expanded inline\n"
    "                (the shared conventions come from the cm-llm-wiki repo's\n"
    "                wiki-conventions.md, linked at .claude/wiki-conventions.md).\n"
    "     Generator: scripts/sync-agents.py in the cm-llm-wiki repo, run by\n"
    "                wire-vault.sh / wire-vault.ps1.\n"
    "     Refresh:   uv run --script .claude/wiki-scripts/sync-agents.py\n"
    "                (from inside the vault),\n"
    "                or re-run wire-vault on this vault; use --all after editing\n"
    "                wiki-conventions.md to refresh every registered vault.\n"
    "     Why:       Codex CLI reads AGENTS.md but cannot expand @-imports, so\n"
    "                the imported content must be inlined. Edit CLAUDE.md (vault\n"
    "                specifics) or wiki-conventions.md (shared rules), never this. -->\n\n"
)
MAX_DEPTH = 4  # matches Claude Code's import recursion limit
IMPORT_RE = re.compile(r"^@(\S+)\s*$")  # an @path alone on a line


def expand(text: str, base: pathlib.Path, depth: int = 0) -> str:
    if depth >= MAX_DEPTH:
        return text
    out = []
    for line in text.split("\n"):
        m = IMPORT_RE.match(line.strip())
        target = None
        if m:
            raw = m.group(1)
            p = pathlib.Path(os.path.expanduser(raw))
            if not p.is_absolute():
                p = base / p
            if p.is_file():
                target = p
        if target:
            body = target.read_text(encoding="utf-8").rstrip("\n")
            out.append(expand(body, target.parent, depth + 1))
        else:
            out.append(line)
    return "\n".join(out)


def registered_vaults() -> list:
    reg = pathlib.Path.home() / ".obsidian-wiki"
    vaults = []
    for cfg in sorted(reg.glob("config.*")):
        for line in cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^OBSIDIAN_VAULT_PATH=(.+)$", line.strip())
            if m:
                vaults.append(pathlib.Path(m.group(1).strip()))
    return vaults


def resolve_vault(explicit: Optional[str] = None) -> pathlib.Path:
    """Resolve the active vault, in priority order:
      1. explicit --vault override (must be an existing directory);
      2. walk up from CWD to the first dir containing .manifest.json (stop at $HOME or /);
      3. map CWD (or nearest ancestor) via ~/.obsidian-wiki/projects.json to a vault
         name, then read OBSIDIAN_VAULT_PATH from ~/.obsidian-wiki/config.<name>;
      4. the OBSIDIAN_VAULT_PATH env var (back-compat).
    Exit with a clear message if none apply."""
    if explicit:
        v = pathlib.Path(explicit).expanduser().resolve()
        if not v.is_dir():
            raise SystemExit(f"--vault path does not exist or is not a directory: {v}")
        return v
    cwd = pathlib.Path.cwd()
    home = pathlib.Path.home()
    for d in [cwd] + list(cwd.parents):
        if (d / ".manifest.json").is_file():
            return d
        if d == home or d == pathlib.Path("/"):
            break
    v = _vault_from_projects(cwd)
    if v is not None:
        return v
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return pathlib.Path(env).expanduser()
    raise SystemExit(
        "No vault found. Looked for .manifest.json walking up from the current "
        "directory, then for a match in ~/.obsidian-wiki/projects.json. "
        "Pass --vault <path> to point at the vault explicitly."
    )


def _vault_from_projects(start: pathlib.Path) -> Optional[pathlib.Path]:
    """Map CWD (or nearest ancestor) → vault via ~/.obsidian-wiki/projects.json and
    the referenced config.<name>'s OBSIDIAN_VAULT_PATH. None if no mapping applies."""
    reg = pathlib.Path.home() / ".obsidian-wiki"
    try:
        projects = json.loads((reg / "projects.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(projects, dict):
        return None
    name = None
    for d in [start] + list(start.parents):
        if str(d) in projects:
            name = projects[str(d)]
            break
    if not name:
        return None
    try:
        text = (reg / f"config.{name}").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = re.match(r"^\s*OBSIDIAN_VAULT_PATH=(.+)$", line.strip())
        if m:
            return pathlib.Path(m.group(1).strip()).expanduser()
    return None


def split_frontmatter(text: str) -> tuple:
    """(frontmatter block or '', rest) - Obsidian plugins may stamp one on."""
    m = re.match(r"^---\r?\n.*?\r?\n---\r?\n", text, re.DOTALL)
    return (text[:m.end()], text[m.end():]) if m else ("", text)


def sync(vault: pathlib.Path, check: bool) -> bool:
    """Returns True if the vault is (now) in sync."""
    claude_md = vault / "CLAUDE.md"
    agents_md = vault / "AGENTS.md"
    if not claude_md.is_file():
        print(f"NO CLAUDE.md  {vault}")
        return False
    want = BANNER + expand(claude_md.read_text(encoding="utf-8-sig"), vault)
    have = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else None
    fm, have_body = split_frontmatter(have) if have is not None else ("", None)
    if have_body == want:
        print(f"ok       {vault}/AGENTS.md")
        return True
    if check:
        state = "STALE" if have is not None else "MISSING"
        print(f"{state:8} {vault}/AGENTS.md")
        return False
    agents_md.write_text(fm + want, encoding="utf-8")
    print(f"synced   {vault}/AGENTS.md")
    return True


def main():
    argv = sys.argv[1:]
    check = "--check" in argv
    all_vaults = "--all" in argv
    # Extract --vault VALUE / --vault=VALUE; everything else non-flag is a positional path.
    vault_opt = None
    paths = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--vault":
            i += 1
            if i < len(argv):
                vault_opt = argv[i]
        elif a.startswith("--vault="):
            vault_opt = a.split("=", 1)[1]
        elif a.startswith("--"):
            pass
        else:
            paths.append(a)
        i += 1

    if all_vaults:
        vaults = registered_vaults()
        if not vaults:
            raise SystemExit("no vaults registered in ~/.obsidian-wiki (config.* files)")
    elif vault_opt:
        vaults = [resolve_vault(vault_opt)]
    elif paths:
        vaults = [pathlib.Path(p) for p in paths]
    else:
        vaults = [resolve_vault()]

    ok = True
    for v in vaults:
        if not v.is_dir():
            print(f"SKIPPED  {v} (not a directory)")
            ok = False
            continue
        ok = sync(v.resolve(), check) and ok
    sys.exit(0 if ok else 1)


# --- run log (copied verbatim into every script, like resolve_vault) ---------
# One TSV line per run in ~/.obsidian-wiki/runs.tsv: when, script, cwd, seconds,
# exit code, args, and any RUN_STATS the script filled in. Machine-local, never
# inside a vault; `claude-history.py runs` summarizes it. WIKI_RUNLOG=0 disables.
# Never raises: logging must not break the tool.
RUN_STATS: dict = {}


def log_run(t0: float, rc) -> None:
    import os as _os, sys as _sys, time as _time
    from datetime import datetime as _dt
    if _os.environ.get("WIKI_RUNLOG") == "0":
        return
    try:
        d = __import__("pathlib").Path.home() / ".obsidian-wiki"
        d.mkdir(exist_ok=True)
        fields = [_dt.now().isoformat(timespec="seconds"),
                  __import__("pathlib").Path(_sys.argv[0]).name, _os.getcwd(),
                  f"{_time.monotonic() - t0:.2f}", str(rc), " ".join(_sys.argv[1:])[:300],
                  " ".join(f"{k}={v}" for k, v in RUN_STATS.items())]
        with open(d / "runs.tsv", "a", encoding="utf-8") as fh:
            fh.write("\t".join(f.replace("\t", " ").replace("\n", " ") for f in fields) + "\n")
    except Exception:
        pass
# --- end run log -------------------------------------------------------------


if __name__ == "__main__":
    import time as _time
    _t0, _rc = _time.monotonic(), 1
    try:
        _rc = main()
        _rc = 0 if _rc is None else _rc
    except SystemExit as _e:
        _rc = _e.code if isinstance(_e.code, int) else (0 if _e.code is None else 1)
        raise
    finally:
        log_run(_t0, _rc)
    sys.exit(_rc)
