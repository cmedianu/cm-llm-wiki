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

Also rejects duplicate mapping keys (at any nesting level), which
`yaml.safe_load` silently collapses last-wins — a page with two `lifecycle:`
keys would otherwise validate while Obsidian and the linter disagree on which
value is in effect.

  uv run .claude/wiki-scripts/validate-frontmatter.py     # from anywhere in the vault
  # or, if marked executable:  ./.claude/wiki-scripts/validate-frontmatter.py

Exit codes:
  0  every page parses (and no real page is missing frontmatter)
  1  at least one page has invalid frontmatter, or a real page lacks it

Files that legitimately have no frontmatter (index.md, log.md, hot.md,
CLAUDE.md, any README.md) are allow-listed and never reported as missing.

Read-only — never writes. See README.md in this directory.
"""
import argparse
import json
import os
import re
import sys
import pathlib
from collections.abc import Hashable
from typing import Optional

import yaml

# Basenames that are scaffolding / meta, not pages — frontmatter not required.
ALLOW_NO_FRONTMATTER = {"index.md", "log.md", "hot.md", "CLAUDE.md", "AGENTS.md", "README.md"}


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that raises on duplicate mapping keys instead of keeping the last."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                continue  # let SafeLoader raise its own unhashable-key error
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None,
                    f"duplicate frontmatter key: {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


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
        data = yaml.load(block, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as e:
        return ("INVALID", str(e).replace("\n", " ").strip())
    if not isinstance(data, dict):
        return ("INVALID", f"frontmatter parsed as {type(data).__name__}, not a mapping")
    return ("OK", None)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the YAML frontmatter of every page in the vault.",
    )
    parser.add_argument(
        "--vault", default=None,
        help="Path to vault root. If omitted, auto-detected.",
    )
    args = parser.parse_args()
    vault = resolve_vault(args.vault)
    invalid, missing, checked = [], [], 0
    for f in sorted(vault.rglob("*.md")):
        rel = f.relative_to(vault)
        if any(part.startswith(".") or part.startswith("_") for part in rel.parts):
            continue  # skip dotdirs (.claude, ...) and _-dirs (_raw, _bin, _strata-emails) — not wiki content
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
