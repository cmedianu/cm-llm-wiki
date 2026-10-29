#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Validate the YAML frontmatter of every page in the vault.

Kept as a compatibility alias: the check now lives in wiki-lint.py (the same
strict parse, including duplicate keys and the unquoted colon-space trap), so the
pre-commit gate runs one command. This forwards to:

  wiki-lint.py --only invalid_frontmatter,missing_frontmatter --errors-only --format md

Usage:
  uv run .claude/wiki-scripts/validate-frontmatter.py [--vault PATH] [--staged]

Exit codes: 0 every page parses, 1 at least one page is invalid or missing it.
"""
import argparse
import pathlib
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate page frontmatter (alias for wiki-lint).")
    ap.add_argument("--vault", default=None, help="Path to vault root. If omitted, auto-detected.")
    ap.add_argument("--staged", action="store_true", help="Only pages staged in git.")
    args = ap.parse_args()
    lint = pathlib.Path(__file__).resolve().with_name("wiki-lint.py")
    cmd = ["uv", "run", "--script", str(lint), "--errors-only", "--format", "md",
           "--only", "invalid_frontmatter,missing_frontmatter"]
    if args.vault:
        cmd += ["--vault", args.vault]
    if args.staged:
        cmd.append("--staged")
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
