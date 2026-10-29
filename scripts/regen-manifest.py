#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Create or repair a vault's .manifest.json: the vault marker plus vault config.

The manifest holds only {version, created, updated, private_paths} (and any other
top-level config key a vault adds). It no longer tracks pages: git records what
changed, and every per-page field drifted from the pages it described. Its
existence is what the scripts' vault walk-up looks for; Obsidian never reads it.

This script creates a missing manifest, moves an unparsable one aside to
.manifest.json.bad, and strips the legacy per-page `sources` map and absolute
`vault_path` from an old one, keeping `private_paths`. Idempotent: a second run
changes nothing (`updated` moves only when the content does). --dry-run previews.
"""
import argparse
import os
import re
import json
import datetime
import pathlib
import sys
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
_ARGS.add_argument("--json", action="store_true",
                   help="Print what was (or would be) done as JSON.")
_ns = _ARGS.parse_args()

VAULT = resolve_vault(_ns.vault)
DRY = _ns.dry_run or os.environ.get("DRY_RUN") == "1"






def load_manifest(path: pathlib.Path, dry: bool):
    """Parsed .manifest.json dict, or None when missing or unparsable.

    The repair tools must not crash on the file they repair: an unparsable
    manifest is treated as missing and moved aside to .manifest.json.bad (left
    in place under --dry-run), with a warning on stderr."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return data
        problem = "top level is not a JSON object"
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        problem = str(e)
    bad = path.with_name(path.name + ".bad")
    if dry:
        print(f"WARNING: {path.name} is unparsable ({problem}); treating it as missing "
              f"(a real run moves it to {bad.name})", file=sys.stderr)
    else:
        os.replace(path, bad)
        print(f"WARNING: {path.name} is unparsable ({problem}); moved it to {bad.name} "
              "and treating the manifest as missing", file=sys.stderr)
    return None


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    manifest_path = VAULT / ".manifest.json"
    prev = load_manifest(manifest_path, DRY)
    existed = prev is not None
    prev = prev or {}
    now = now_iso()

    dropped = len(prev.get("sources") or {})
    marker = {k: v for k, v in prev.items() if k not in ("sources", "vault_path", "updated")}
    marker.setdefault("version", 1)
    marker.setdefault("created", now)
    marker.setdefault("private_paths", prev.get("private_paths", []))
    unchanged = existed and {k: v for k, v in prev.items() if k != "updated"} == marker
    if unchanged:
        marker["updated"] = prev.get("updated", now)
    else:
        marker["updated"] = now
    ordered = {k: marker[k] for k in ("version", "created", "updated", "private_paths")}
    ordered.update({k: v for k, v in marker.items() if k not in ordered})

    if not unchanged and not DRY:
        manifest_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    if _ns.json:
        print(json.dumps({"dry_run": DRY, "created": not existed, "changed": not unchanged,
                          "dropped_page_entries": dropped,
                          "private_paths": ordered["private_paths"]}, indent=2))
        return
    verb = "would " if DRY else ""
    if not existed:
        print(f"{verb}create .manifest.json")
    elif unchanged:
        print(".manifest.json is already current")
    else:
        print(f"{verb}rewrite .manifest.json"
              + (f": drop {dropped} legacy page entries" if dropped else "")
              + ("; drop vault_path" if "vault_path" in prev else ""))
    print(f"private_paths: {ordered['private_paths']}")


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
