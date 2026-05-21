#!/usr/bin/env python3
"""Re-sync .manifest.json with the current state of the vault.

Walks the vault, finds every content .md (skipping dotdirs and scaffolding),
preserves the original ingested_at timestamp for sources that already existed,
and reports added / removed / modified pages.

Idempotent — running it twice in a row should produce no changes on the second
run except the top-level `updated` field. Use DRY_RUN=1 to preview without
writing.
"""
import os
import json
import datetime
import pathlib


def find_vault() -> pathlib.Path:
    """Resolve the active vault: OBSIDIAN_VAULT_PATH env var, else walk up
    from CWD looking for a .env with OBSIDIAN_VAULT_PATH=..."""
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return pathlib.Path(env)
    cwd = pathlib.Path.cwd()
    home = pathlib.Path.home()
    for d in [cwd] + list(cwd.parents):
        f = d / ".env"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("OBSIDIAN_VAULT_PATH="):
                    return pathlib.Path(line.split("=", 1)[1].strip().strip('"').strip("'"))
        if d == home:
            break
    raise SystemExit("OBSIDIAN_VAULT_PATH not set and no .env found walking up from CWD")


VAULT = find_vault()
SCAFFOLD = {"index.md", "log.md"}
DRY = os.environ.get("DRY_RUN") == "1"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mtime_iso(p: pathlib.Path) -> str:
    return datetime.datetime.fromtimestamp(p.stat().st_mtime, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_sources():
    out = {}
    for p in sorted(VAULT.rglob("*.md")):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if rel in SCAFFOLD:
            continue
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
