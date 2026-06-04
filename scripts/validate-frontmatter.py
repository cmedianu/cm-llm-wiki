#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Validate the YAML frontmatter of every page in the vault.

Catches the failure mode where frontmatter is *present but unparseable* — most
commonly an unquoted colon-space (`: `) in a value, which YAML reads as a
key/value separator. One bad line invalidates the whole block, and Obsidian
then silently fails to render the Properties panel for that page.

  uv run .claude/wiki-scripts/validate-frontmatter.py     # from anywhere in the vault
  # or, if marked executable:  ./.claude/wiki-scripts/validate-frontmatter.py

Exit codes:
  0  every page parses (and no real page is missing frontmatter)
  1  at least one page has invalid frontmatter, or a real page lacks it

Files that legitimately have no frontmatter (index.md, log.md, hot.md,
CLAUDE.md, any README.md) are allow-listed and never reported as missing.

Read-only — never writes. See README.md in this directory.
"""
import os
import sys
import pathlib

import yaml

# Basenames that are scaffolding / meta, not pages — frontmatter not required.
ALLOW_NO_FRONTMATTER = {"index.md", "log.md", "hot.md", "CLAUDE.md", "README.md"}


def find_vault() -> pathlib.Path:
    """Resolve the active vault by walking up from CWD looking for .manifest.json
    (the canonical vault marker). Falls back to OBSIDIAN_VAULT_PATH for back-compat."""
    cwd = pathlib.Path.cwd()
    for d in [cwd] + list(cwd.parents):
        if (d / ".manifest.json").is_file():
            return d
        if d == pathlib.Path("/"):
            break
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return pathlib.Path(env)
    raise SystemExit("No vault found: walked up from CWD without finding .manifest.json")


def check(path: pathlib.Path):
    """Return (status, detail). status in {OK, MISSING, UNCLOSED, INVALID}."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ("MISSING", None)
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return ("UNCLOSED", "no closing '---' delimiter")
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as e:
        return ("INVALID", str(e).replace("\n", " ").strip())
    if not isinstance(data, dict):
        return ("INVALID", f"frontmatter parsed as {type(data).__name__}, not a mapping")
    return ("OK", None)


def main() -> int:
    vault = find_vault()
    invalid, missing, checked = [], [], 0
    for f in sorted(vault.rglob("*.md")):
        rel = f.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue  # skip dotdirs (.claude, .obsidian, ...)
        checked += 1
        status, detail = check(f)
        if status == "OK":
            continue
        if status == "MISSING":
            if f.name in ALLOW_NO_FRONTMATTER:
                continue
            missing.append(str(rel))
        else:
            invalid.append((str(rel), status, detail))

    if invalid:
        print("INVALID frontmatter (Obsidian will not render Properties):")
        for rel, status, detail in invalid:
            print(f"  ✗ {rel}\n      [{status}] {detail}")
    if missing:
        print("MISSING frontmatter (real pages should have it):")
        for rel in missing:
            print(f"  ! {rel}")

    bad = len(invalid) + len(missing)
    if bad == 0:
        print(f"OK — all {checked} pages have valid frontmatter.")
        return 0
    print(f"\n{len(invalid)} invalid, {len(missing)} missing, of {checked} pages checked.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
