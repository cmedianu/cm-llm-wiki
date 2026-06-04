#!/usr/bin/env python3
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
import os
import re
import sys
import json
import datetime
import shutil
import unicodedata
import pathlib


def find_vault() -> pathlib.Path:
    """Resolve the active vault by walking up from CWD looking for .manifest.json
    (the canonical vault marker). Falls back to the OBSIDIAN_VAULT_PATH env var
    for backward compatibility, but a default vault needs neither."""
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


VAULT = find_vault()
LOG_FILE = "log.md"                          # left as-is (historical record)
DRY = os.environ.get("DRY_RUN") == "1"
APPLY = os.environ.get("APPLY") == "1"

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


def build_path_mapping():
    """{old_vault_relpath_without_md: new_vault_relpath_without_md}"""
    mapping = {}
    for p in sorted(VAULT.rglob("*.md")):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if rel in {"index.md", "log.md"}:
            # scaffolding: keep these names
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


WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+)([#|][^\[\]]*)?\]\]")


def rewrite_wikilinks(text, path_map, basename_map, current_file_rel, problems):
    ci_path_map = {k.lower(): v for k, v in path_map.items()}
    ci_basename_map = {k.lower(): v for k, v in basename_map.items()}
    ci_legacy_map = {k.lower(): v for k, v in LEGACY_WIKILINK_TARGETS.items()}

    def repl(m):
        target = m.group(1).strip()
        rest = m.group(2) or ""
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
            problems.append((current_file_rel, target))
            return m.group(0)  # leave unchanged
        return f"[[{new}{rest}]]"
    return WIKILINK_RE.sub(repl, text)


def main():
    if not DRY and not APPLY:
        print("ERROR: set DRY_RUN=1 (preview) or APPLY=1 (do it). Refusing to proceed.", file=sys.stderr)
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
    for p in sorted(VAULT.rglob("*.md")):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if rel == LOG_FILE:
            continue
        raw = p.read_text(encoding="utf-8")
        new_text = rewrite_wikilinks(raw, path_map, basename_map, rel, problems)
        if new_text != raw:
            rewritten_files.append(rel)
            if APPLY:
                p.write_text(new_text, encoding="utf-8")

    print(f"=== wikilink rewrite: {len(rewritten_files)} files would have body wikilinks updated ===")
    for f in rewritten_files[:20]:
        print(f"  ~ {f}")
    if len(rewritten_files) > 20:
        print(f"  ... and {len(rewritten_files)-20} more")
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
        if manifest_path.exists():
            old_to_new_md = {f"{o}.md": f"{n}.md" for o, n in path_map.items()}
            for legacy_no_ext, new_no_ext in LEGACY_WIKILINK_TARGETS.items():
                old_to_new_md[f"{legacy_no_ext}.md"] = f"{new_no_ext}.md"
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
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


if __name__ == "__main__":
    main()
