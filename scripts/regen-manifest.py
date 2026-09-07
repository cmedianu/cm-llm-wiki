#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""Re-sync .manifest.json with the current state of the vault.

Walks the vault, finds every content .md (skipping dotdirs and scaffolding),
preserves the original ingested_at timestamp for sources that already existed,
and reports added / removed / modified pages.

Idempotent — running it twice in a row should produce no changes on the second
run except the top-level `updated` field. Use DRY_RUN=1 to preview without
writing.
"""
import argparse
import os
import re
import json
import datetime
import pathlib
from typing import Optional


def resolve_vault(explicit: Optional[str] = None) -> pathlib.Path:
    """Resolve the active vault, in priority order:
      1. explicit --vault override (must be an existing directory);
      2. walk up from CWD to the first dir containing .manifest.json (stop at $HOME or /);
      3. map CWD (or nearest ancestor) via ~/.obsidian-wiki/projects.json to a vault
         name, then read OBSIDIAN_VAULT_PATH from ~/.obsidian-wiki/config.<name>;
      4. the REGEN_AT bootstrap env var (regen-specific: names a dir that may not
         have a .manifest.json yet);
      5. the OBSIDIAN_VAULT_PATH env var (back-compat).
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
    # Bootstrapping case: no manifest exists yet
    regen_at = os.environ.get("REGEN_AT")
    if regen_at:
        return pathlib.Path(regen_at).expanduser()
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return pathlib.Path(env).expanduser()
    raise SystemExit(
        "No vault found. Looked for .manifest.json walking up from the current "
        "directory, then for a match in ~/.obsidian-wiki/projects.json. To "
        "bootstrap a new vault, pass --vault <path> (or set REGEN_AT=<vault-path>)."
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


_ARGS = argparse.ArgumentParser(description="Re-sync .manifest.json with the vault.")
_ARGS.add_argument("--vault", default=None, help="Path to vault root. Overrides auto-detection and REGEN_AT.")
_ARGS.add_argument("--dry-run", action="store_true", help="Preview changes without writing (same as DRY_RUN=1).")
_ns = _ARGS.parse_args()

VAULT = resolve_vault(_ns.vault)
# Scaffolding basenames (any depth) — same set as wiki-lint/wiki-graph/validate-frontmatter.
SCAFFOLD = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md", "AGENTS.md"}
DRY = _ns.dry_run or os.environ.get("DRY_RUN") == "1"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mtime_iso(p: pathlib.Path) -> str:
    return datetime.datetime.fromtimestamp(p.stat().st_mtime, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_sources():
    out = {}
    for p in sorted(VAULT.rglob("*.md")):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith(".") or part.startswith("_") for part in rel.split("/")):
            continue  # skip dotdirs and _-dirs (_raw, _bin, _archive-emails) — not wiki content
        if rel.split("/")[-1] in SCAFFOLD:
            continue  # scaffolding at any depth (folder indexes, READMEs) — not sources
        st = p.stat()
        out[rel] = {"size_bytes": st.st_size, "mtime": mtime_iso(p)}
    return out


def main():
    manifest_path = VAULT / ".manifest.json"
    now = now_iso()

    if manifest_path.exists():
        prev = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        prev = {"version": 1, "vault_path": str(VAULT), "created": now, "sources": {}}

    prev_sources = prev.get("sources", {})
    current = discover_sources()

    sources = {}
    added, modified, unchanged = [], [], []

    for rel, stat in current.items():
        if rel in prev_sources:
            old = prev_sources[rel]
            ingested = old.get("ingested_at", now)
            entry = {
                "source_path": rel,
                "kind": old.get("kind", "self-authored"),
                "ingested_at": ingested,
                "lifecycle": old.get("lifecycle", "reviewed"),
                "pages": old.get("pages", [rel]),
                "size_bytes": stat["size_bytes"],
                "mtime": stat["mtime"],
            }
            if old.get("size_bytes") != stat["size_bytes"] or old.get("mtime") != stat["mtime"]:
                modified.append(rel)
            else:
                unchanged.append(rel)
        else:
            entry = {
                "source_path": rel,
                "kind": "self-authored",
                "ingested_at": now,
                "lifecycle": "reviewed",
                "pages": [rel],
                "size_bytes": stat["size_bytes"],
                "mtime": stat["mtime"],
            }
            added.append(rel)
        sources[rel] = entry

    removed = [r for r in prev_sources if r not in current]

    manifest = {
        "version": prev.get("version", 1),
        "vault_path": str(VAULT),
        "created": prev.get("created", now),
        "updated": now,
        "sources": sources,
    }
    # Preserve vault-level config that lives in the manifest but isn't rebuilt from
    # the file walk (e.g. private_paths consumed by wiki-lint's privacy-scope check).
    if "private_paths" in prev:
        manifest["private_paths"] = prev["private_paths"]

    if DRY:
        print("[DRY-RUN] no file written")
    else:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(f"sources total : {len(sources)}")
    print(f"  added       : {len(added)}")
    for r in added:
        print(f"    + {r}")
    print(f"  removed     : {len(removed)}")
    for r in removed:
        print(f"    - {r}")
    print(f"  modified    : {len(modified)}")
    for r in modified:
        print(f"    ~ {r}")
    print(f"  unchanged   : {len(unchanged)}")


if __name__ == "__main__":
    main()
