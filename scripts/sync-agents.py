#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
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
  sync-agents.py                 sync the vault found by walking up from CWD
  sync-agents.py VAULT [...]     sync the given vault dir(s)
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
import pathlib

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


def vault_from_cwd() -> pathlib.Path:
    cwd = pathlib.Path.cwd()
    for d in [cwd] + list(cwd.parents):
        if (d / ".manifest.json").is_file():
            return d
    raise SystemExit("No vault found: walked up from CWD without finding .manifest.json")


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
    want = BANNER + expand(claude_md.read_text(encoding="utf-8"), vault)
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
    args = sys.argv[1:]
    check = "--check" in args
    all_vaults = "--all" in args
    paths = [a for a in args if not a.startswith("--")]

    if all_vaults:
        vaults = registered_vaults()
        if not vaults:
            raise SystemExit("no vaults registered in ~/.obsidian-wiki (config.* files)")
    elif paths:
        vaults = [pathlib.Path(p) for p in paths]
    else:
        vaults = [vault_from_cwd()]

    ok = True
    for v in vaults:
        if not v.is_dir():
            print(f"SKIPPED  {v} (not a directory)")
            ok = False
            continue
        ok = sync(v.resolve(), check) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
