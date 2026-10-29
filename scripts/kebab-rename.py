#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Rename every content .md to kebab-case-lowercase and rewrite all wikilinks.

Folders keep their casing by default. To rename selected folders too, edit
the FOLDER_RENAMES constant below.

DRY_RUN=1   preview only, no fs changes
APPLY=1     actually perform the renames and rewrites

Also rewrites:
  - index.md       (every wikilink)
  - log.md         (left alone -- historical record)
  - .manifest.json (re-keyed in lockstep so ingested_at survives)
  - Body text of every .md file -- every [[...]] wikilink

See README.md in this directory for usage and knob explanations.
"""
import argparse
import os
import re
import sys
import json
import datetime
import shutil
import unicodedata
import pathlib
from typing import Optional


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


_ARGS = argparse.ArgumentParser(description="Rename content pages to kebab-case and rewrite wikilinks.")
_ARGS.add_argument("--vault", default=None, help="Path to vault root. Overrides auto-detection.")
_ARGS.add_argument("--dry-run", action="store_true", help="Preview only (same as DRY_RUN=1).")
_ARGS.add_argument("--apply", action="store_true", help="Perform the renames (same as APPLY=1).")
_ns = _ARGS.parse_args()

VAULT = resolve_vault(_ns.vault)
LOG_FILE = "log.md"                          # left as-is (historical record)
DRY = _ns.dry_run or os.environ.get("DRY_RUN") == "1"
APPLY = _ns.apply or os.environ.get("APPLY") == "1"

# Optional folder renames applied alongside the file renames.
#   Example: {"Notes/MyOldFolderName": "Notes/my-new-folder-name"}
FOLDER_RENAMES: dict[str, str] = {}

# Compound brand or acronym names where internal capitalization should NOT
# introduce a word boundary. Applied as a substring replacement BEFORE the
# PascalCase splitter, so "Install FooBar" -> "install foobar" instead of
# "install-foo-bar".
#   Example: {"FooBar": "foobar", "MyBrand": "mybrand"}
BRAND_PRESERVATIONS: dict[str, str] = {}

# Per-path overrides for cases where slugify produces a bad result — typically
# because the source filename lost a word boundary somewhere along the way.
# Keys are CURRENT vault-relative paths without .md.
#   Example: {"OldFolder/MyMangledFilename": "OldFolder/my-clean-filename"}
PATH_OVERRIDES: dict[str, str] = {}

# Legacy wikilink targets to redirect to a new canonical post-rename path so
# dangling links from externally renamed files get fixed in the same pass.
# Both full vault-relative and bare-basename forms are looked up.
#   Example: {"Old Folder/Old File Name": "new-folder/new-file-name"}
LEGACY_WIKILINK_TARGETS: dict[str, str] = {}


def slugify(name: str) -> str:
    """Filename -> kebab-case-lowercase, ASCII-only."""
    s = name
    if s.endswith(".md"):
        s = s[:-3]
    # Common substitutions before stripping
    s = s.replace("&", " and ")
    s = s.replace("'", "").replace("’", "").replace("`", "").replace('"', "")
    s = s.replace("–", "-").replace("—", "-")  # en/em dash -> hyphen
    # Preserve compound brand names before the case splitter
    for brand, replacement in BRAND_PRESERVATIONS.items():
        s = s.replace(brand, replacement)
    # Split PascalCase
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    # Normalize unicode, drop diacritics and non-ascii (emoji)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if (c.isascii() and (c.isalnum() or c in " -_")))
    # Collapse whitespace and underscores into hyphens
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.lower().strip("-")
    return s


# --- content-page rule (pasted verbatim into every script; scripts never import
# each other). A vault-relative .md path is NOT a content page when any component
# starts with "." or "_" (.obsidian, _raw, _sources, _archives), its first
# component is "templates" (Obsidian templates folder), it is a root-level
# yyyy-MM-dd.md daily note, or its basename is scaffolding.
NON_PAGE_NAMES = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md", "AGENTS.md"}
_DAILY_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def is_content_page(rel) -> bool:
    """True iff the vault-relative path `rel` (str or path) is a content page."""
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
    if not parts:
        return False
    if any(p.startswith((".", "_")) for p in parts):
        return False
    if parts[0] == "templates":
        return False
    if len(parts) == 1 and _DAILY_NOTE_RE.match(parts[0]):
        return False
    return parts[-1] not in NON_PAGE_NAMES
# --- end content-page rule


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


def iter_md(vault: pathlib.Path):
    """Every *.md under the vault, sorted, never descending into dot dirs or
    symlinked directories (Path.rglob follows dir symlinks on Python <= 3.12,
    so a linked _sources/ or scripts dir would otherwise be walked)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(vault, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".md"):
                out.append(pathlib.Path(dirpath) / fn)
    return sorted(out)


def build_path_mapping():
    """{old_vault_relpath_without_md: new_vault_relpath_without_md}"""
    mapping = {}
    for p in iter_md(VAULT):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith((".", "_")) for part in rel.split("/")):
            continue  # dotdirs and _-dirs (_sources, _raw, _archives) are not wiki content
        if not is_content_page(rel):
            # scaffolding at any depth, templates/, root daily notes: keep these
            # names (links to them still resolve) — never slugify a README
            mapping[rel[:-3]] = rel[:-3]
            continue
        parent_parts = rel.split("/")[:-1]
        base_no_ext = rel.split("/")[-1][:-3]
        new_base = slugify(base_no_ext)
        new_parent_parts = []
        for part in parent_parts:
            full_so_far = "/".join(parent_parts[: len(new_parent_parts) + 1])
            mapped = FOLDER_RENAMES.get(full_so_far)
            new_parent_parts.append(mapped.split("/")[-1] if mapped else part)
        new_rel = "/".join(new_parent_parts + [new_base]) if new_parent_parts else new_base
        mapping[rel[:-3]] = new_rel
    # Apply per-path overrides
    for old, new in PATH_OVERRIDES.items():
        if old in mapping:
            mapping[old] = new
    return mapping


def build_basename_map(path_map):
    """{old_basename_no_ext: new_vault_relpath_no_ext}, only when basename is unique across map."""
    counts = {}
    pick = {}
    for old, new in path_map.items():
        base = old.split("/")[-1]
        counts[base] = counts.get(base, 0) + 1
        pick[base] = new
    return {b: pick[b] for b, c in counts.items() if c == 1}


# [[target]] plus an optional suffix starting at #heading, ^block, |alias or a
# table-escaped \|alias. The target is lazy so "a\|b" yields "a", not "a\".
WIKILINK_RE = re.compile(r"\[\[([^\[\]|#^]+?)((?:\\?\||[#^])[^\[\]]*)?\]\]")
_FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# Embeds/links to attachments ([[diagram.png]], ![[clip.mp4]]) are not pages.
_NON_MD_EXT_RE = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|bmp|avif|pdf|mp3|mp4|m4a|wav|ogg|flac|webm|mov|mkv|"
    r"canvas|base|excalidraw|csv|json|txt|zip)$", re.IGNORECASE)


def rewrite_wikilinks(text, path_map, basename_map, current_file_rel, problems):
    ci_path_map = {k.lower(): v for k, v in path_map.items()}
    ci_basename_map = {k.lower(): v for k, v in basename_map.items()}
    ci_legacy_map = {k.lower(): v for k, v in LEGACY_WIKILINK_TARGETS.items()}

    def repl(m):
        target = m.group(1).strip()
        rest = m.group(2) or ""
        if _NON_MD_EXT_RE.search(target):
            return m.group(0)  # attachment, not a page: leave it alone
        md_suffix = ""
        if target.lower().endswith(".md"):
            md_suffix, target = target[-3:], target[:-3]
        key = target.lower()
        if target in path_map:
            new = path_map[target]
        elif target in basename_map:
            new = basename_map[target]
        elif target in LEGACY_WIKILINK_TARGETS:
            new = LEGACY_WIKILINK_TARGETS[target]
        elif key in ci_path_map:
            new = ci_path_map[key]
        elif key in ci_basename_map:
            new = ci_basename_map[key]
        elif key in ci_legacy_map:
            new = ci_legacy_map[key]
        else:
            problems.append((current_file_rel, target + md_suffix))
            return m.group(0)  # leave unchanged
        return f"[[{new}{md_suffix}{rest}]]"

    # Never rewrite inside fenced code blocks (``` or ~~~): examples stay verbatim.
    out, fence = [], None
    for line in text.splitlines(keepends=True):
        fm = _FENCE_OPEN_RE.match(line)
        if fence is None:
            if fm:
                fence = fm.group(1)
                out.append(line)
            else:
                out.append(WIKILINK_RE.sub(repl, line))
        else:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            out.append(line)
    return "".join(out)


def main():
    if not DRY and not APPLY:
        print("ERROR: pass --dry-run (preview) or --apply (do it) — or set DRY_RUN=1 / APPLY=1. Refusing to proceed.", file=sys.stderr)
        sys.exit(2)

    path_map = build_path_mapping()
    basename_map = build_basename_map(path_map)

    # Print rename preview
    renamed = [(o, n) for o, n in path_map.items() if o != n]
    unchanged = [o for o, n in path_map.items() if o == n]
    print(f"=== rename preview: {len(renamed)} file paths change, {len(unchanged)} stay ===")
    for o, n in sorted(renamed):
        print(f"  {o}.md")
        print(f"    -> {n}.md")
    print()

    # Wikilink rewrite pass
    rewritten_files = []
    problems = []
    undecodable = []
    for p in iter_md(VAULT):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if rel == LOG_FILE:
            continue
        try:
            # newline="" keeps CRLF pages CRLF when rewritten.
            with open(p, encoding="utf-8", newline="") as f:
                raw = f.read()
        except UnicodeDecodeError as e:
            # A rewriter must never round-trip a file it cannot decode: skip it.
            undecodable.append(rel)
            print(f"WARNING: {rel} is not valid UTF-8 ({e.reason} at byte {e.start}); "
                  "its wikilinks were NOT rewritten — re-save it as UTF-8 and re-run",
                  file=sys.stderr)
            continue
        new_text = rewrite_wikilinks(raw, path_map, basename_map, rel, problems)
        if new_text != raw:
            rewritten_files.append(rel)
            if APPLY:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)

    print(f"=== wikilink rewrite: {len(rewritten_files)} files would have body wikilinks updated ===")
    for f in rewritten_files[:20]:
        print(f"  ~ {f}")
    if len(rewritten_files) > 20:
        print(f"  ... and {len(rewritten_files)-20} more")
    print()

    if undecodable:
        print(f"=== skipped {len(undecodable)} non-UTF-8 files (links not rewritten) ===")
        for f in undecodable:
            print(f"  ! {f}")
        print()

    if problems:
        print(f"=== unresolved wikilink targets ({len(problems)}) -- left as-is ===")
        for f, t in problems[:30]:
            print(f"  {f}: [[{t}]]")
        if len(problems) > 30:
            print(f"  ... and {len(problems)-30} more")
        print()

    # File renames
    if APPLY:
        # Rename basenames in place first. On case-insensitive filesystems
        # (Windows NTFS, macOS by default) a direct mv "Foo.md" "foo.md" is a
        # no-op; we detect that case and route via an intermediate _tmp_ name.
        for old_rel, new_rel in sorted(path_map.items(), key=lambda kv: -len(kv[0])):
            if old_rel == new_rel:
                continue
            old_path = VAULT / (old_rel + ".md")
            old_parent = old_path.parent
            old_base = old_path.name
            new_base = new_rel.split("/")[-1] + ".md"
            final_path = old_parent / new_base
            if not old_path.exists():
                continue
            if old_base.lower() == new_base.lower() and old_base != new_base:
                # Case-only rename: two-step via tmp.
                tmp_path = old_parent / ("_tmp_" + new_base)
                old_path.rename(tmp_path)
                tmp_path.rename(final_path)
            else:
                if final_path.exists() and final_path != old_path:
                    print(f"ERROR: target {final_path} already exists, skipping", file=sys.stderr)
                    continue
                old_path.rename(final_path)
        # Then rename folders
        for old_folder, new_folder in FOLDER_RENAMES.items():
            old_path = VAULT / old_folder
            new_path = VAULT / new_folder
            if old_path.exists() and not new_path.exists():
                old_path.rename(new_path)
                print(f"folder: {old_folder} -> {new_folder}")
        print(f"=== applied: {len(renamed)} file renames, {len(FOLDER_RENAMES)} folder renames ===")

        # Update the manifest in lockstep so ingested_at survives the rename.
        manifest_path = VAULT / ".manifest.json"
        m = load_manifest(manifest_path, dry=False)
        # Only legacy manifests carry per-page entries; the current marker has none.
        if m is not None and m.get("sources"):
            old_to_new_md = {f"{o}.md": f"{n}.md" for o, n in path_map.items()}
            for legacy_no_ext, new_no_ext in LEGACY_WIKILINK_TARGETS.items():
                old_to_new_md[f"{legacy_no_ext}.md"] = f"{new_no_ext}.md"
            new_sources = {}
            unresolved = []
            for old_key, entry in m.get("sources", {}).items():
                new_key = old_to_new_md.get(old_key, old_key)
                entry["source_path"] = new_key
                entry["pages"] = [new_key]
                if new_key != old_key and new_key in new_sources:
                    unresolved.append((old_key, new_key))
                new_sources[new_key] = entry
            m["sources"] = new_sources
            m["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            manifest_path.write_text(
                json.dumps(m, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"manifest: {len(new_sources)} sources rekeyed; ingested_at preserved")
            if unresolved:
                print("  collisions:")
                for o, n in unresolved:
                    print(f"    {o} -> {n} (already present)")
    else:
        print("=== DRY_RUN -- no files written, no renames performed ===")


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
