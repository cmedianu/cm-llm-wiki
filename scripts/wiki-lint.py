#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Deterministic linter for an Obsidian LLM-wiki vault.

Replaces a pile of checks that were previously done by an LLM reading every
page by hand. Each check is self-contained and reproducible — same vault, same
output, every run.

Checks performed:
  1. Orphaned pages — content pages with zero incoming wikilinks.
  2. Broken wikilinks — wikilinks whose target does not resolve.
  3. Missing or invalid frontmatter — required fields absent, or a frontmatter
     block that fails to parse as YAML (reported separately as invalid_frontmatter).
  4. Summary field — missing or over 200 characters.
  4b. Category mirrors folder — category that is neither the page's folder nor an
      ancestor of it (drift that hides the page from its folder's base index).
  5. Index consistency — pages missing from index, bad section headings, etc.
  6. Sizes and snapshots — oversized pages, unbounded log.md, and dated snapshot
     pages that were never superseded or archived.
  7. Stale content — pages not updated in > 90 days.
  8. Lifecycle + supersession — invalid lifecycle values, broken/cyclic superseded_by.
  9. Provenance marker ratios — ^[inferred] / ^[ambiguous] density by page.
  10. Misc promotion candidates — misc/ pages with strong affinity to a project.
  11. Index privacy leak — a private page (or its summary) listed in a more-public index.
  12. Date-only date fields — created/updated/lifecycle_changed carrying a full
      ISO datetime, or a string that isn't yyyy-MM-dd.

A page can opt out of a specific warning-level check by listing its key in a
`lint_ignore:` frontmatter list (e.g. `lint_ignore: [stale_snapshot]`).
Error-level findings are never suppressible; a listed key that isn't a known
check key is itself flagged (lint_ignore_unknown), so a typo can't silently
suppress nothing.

Usage:
  uv run .claude/wiki-scripts/wiki-lint.py [VAULT] [--format json|md]
      [--errors-only] [--fix]

Exit codes:
  0  no error-level findings
  1  at least one error-level finding exists

Read-only by default — writes to the vault only under --fix, which applies two
deterministic mechanical fixes (unambiguous wikilink path completion, dated-
snapshot supersession wiring) before running the checks. See README.md in this
directory.
"""

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import date, datetime, timezone
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCAFFOLDING = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md", "AGENTS.md"}

# Root-level `yyyy-MM-dd.md` = Obsidian daily note. Per-machine journal scratch, not
# wiki content, and gitignored. Skipped at ANY age: an old daily note is stale scratch,
# not "a normal page now". Anything worth keeping gets distilled into a real page.
DAILY_NOTE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.md")

# `sources` intentionally omitted: most pages here are self-authored and have no
# external source, so requiring it produced noise instead of signal.
REQUIRED_FRONTMATTER = {"title", "category", "tags", "created", "updated"}

VALID_LIFECYCLES = {"draft", "reviewed", "living", "archived"}

# Headings in index.md that are allowed even if they don't match a real folder
INDEX_META_HEADINGS = {"Root", "Meta", "Index", "Overview"}

# Oversized-page threshold (bytes). Big pages burn agent tokens on every read;
# `living` dossiers and `archived` pages are exempt (monolithic by design / frozen).
OVERSIZED_PAGE_BYTES = 25_000

# log.md size that triggers a roll-old-entries warning (bytes)
LOG_SIZE_BYTES = 50_000

# A dated-snapshot page (YYYY-MM-DD in the filename) older than this without
# `superseded_by` or `lifecycle: archived` is flagged as a stale snapshot.
STALE_SNAPSHOT_DAYS = 90
_FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Frontmatter fields that must be date-only yyyy-MM-dd per the shared conventions
DATE_ONLY_FIELDS = ("created", "updated", "lifecycle_changed")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Regex to extract wikilinks:  [[target]]  or  [[target|display]]
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Fenced code block detector
_FENCE_RE = re.compile(r"^```")


# ---------------------------------------------------------------------------
# Vault discovery (standard resolver, replicated verbatim across scripts/)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Content-page filter
# ---------------------------------------------------------------------------

def is_content_page(rel: pathlib.PurePosixPath) -> bool:
    """True if this relative path represents a content page (not scaffolding/meta)."""
    parts = rel.parts
    if any(p.startswith(".") or p.startswith("_") for p in parts):
        return False
    if rel.name in SCAFFOLDING:
        return False
    if len(parts) == 1 and DAILY_NOTE_RE.fullmatch(rel.name):
        return False  # daily notes are per-machine scratch, never wiki content, at any age
    return True


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

# Pages whose frontmatter block exists but does not parse as a YAML mapping
# (e.g. an unquoted `: ` in a value). Populated by load_frontmatter so
# check_frontmatter_fields can report invalid_frontmatter, not missing_frontmatter.
INVALID_YAML: set[pathlib.Path] = set()

# Parse-once caches — a lint run reads each page many times across checks;
# files don't change mid-run, so memoize the two hot parsers.
_FM_CACHE: dict[pathlib.Path, Optional[dict]] = {}
_LINK_CACHE: dict[pathlib.Path, list[tuple[int, str]]] = {}


def load_frontmatter(path: pathlib.Path) -> Optional[dict]:
    """Parse YAML frontmatter from a file. Returns dict or None on any failure.

    Memoized per run. A file that HAS a frontmatter block that fails to parse
    is additionally recorded in INVALID_YAML.
    """
    if path in _FM_CACHE:
        return _FM_CACHE[path]
    result = _load_frontmatter_uncached(path)
    _FM_CACHE[path] = result
    return result


def _load_frontmatter_uncached(path: pathlib.Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        INVALID_YAML.add(path)
        return None
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        INVALID_YAML.add(path)
        return None
    if not isinstance(data, dict):
        INVALID_YAML.add(path)
        return None
    return data


# ---------------------------------------------------------------------------
# Wikilink extraction (skips fenced code blocks and frontmatter)
# ---------------------------------------------------------------------------

def extract_wikilinks(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return [(line_number, target), …] for wikilinks outside frontmatter and code blocks.

    line_number is 1-based. target has #heading / ^block suffixes stripped.
    Memoized per run.
    """
    if path in _LINK_CACHE:
        return _LINK_CACHE[path]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _LINK_CACHE[path] = []
        return []
    lines = text.splitlines()

    # Skip frontmatter
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break

    results = []
    in_fence = False
    for lineno, line in enumerate(lines[start:], start=start + 1):
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _WIKILINK_RE.finditer(line):
            raw = m.group(1)
            # strip display alias; treat a table-escaped pipe (\|) as a normal alias
            # separator so [[target\|Alias]] inside a Markdown table isn't misread as a
            # broken link to "target\".
            target = raw.replace("\\|", "|").split("|")[0].strip()
            # strip heading/block anchors
            target = re.split(r"[#^]", target)[0].strip()
            if target:
                results.append((lineno, target))
    _LINK_CACHE[path] = results
    return results


# ---------------------------------------------------------------------------
# Wikilink resolver
# ---------------------------------------------------------------------------

def build_resolver(vault: pathlib.Path, content_pages: list[pathlib.Path]):
    """Return a callable resolve(target) -> pathlib.Path | None.

    Resolves by:
      (a) vault-relative path (target + ".md")
      (b) unique bare-basename match among content pages
    """
    # basename → list of absolute paths
    by_basename: dict[str, list[pathlib.Path]] = {}
    for p in content_pages:
        by_basename.setdefault(p.name.lower(), []).append(p)
        # also index without .md suffix
        stem = p.stem.lower()
        by_basename.setdefault(stem, []).append(p)

    def resolve(target: str) -> Optional[pathlib.Path]:
        # (a) vault-relative path
        candidate = vault / (target + ".md")
        if candidate.is_file():
            return candidate
        candidate2 = vault / target
        if candidate2.is_file():
            return candidate2
        # (b) unique basename match (case-insensitive)
        key = target.lower()
        matches = by_basename.get(key, [])
        if len(matches) == 1:
            return matches[0]
        # try with .md
        key_md = (target + ".md").lower()
        matches2 = by_basename.get(key_md, [])
        if len(matches2) == 1:
            return matches2[0]
        return None

    return resolve


# ---------------------------------------------------------------------------
# Index discovery + privacy-scope config
# ---------------------------------------------------------------------------

def find_all_indexes(vault: pathlib.Path) -> list[pathlib.Path]:
    """All index.md files in the vault (root + section indexes), skipping dot/underscore dirs."""
    out = []
    for f in sorted(vault.rglob("index.md")):
        rel = f.relative_to(vault)
        if any(part.startswith(".") or part.startswith("_") for part in rel.parts):
            continue
        out.append(f)
    return out


_BASE_FENCE_RE = re.compile(r"(?m)^\s*`{3,}\s*base\b")


def index_base_dirs(vault: pathlib.Path) -> set[pathlib.Path]:
    """Directories whose index.md embeds a ```base view (a dynamically generated
    catalog). A content page under such a directory is considered catalogued by that
    index, so it should not be flagged missing-from-index or orphaned just because the
    listing is a live query instead of hand-written wikilinks."""
    dirs: set[pathlib.Path] = set()
    for idx in find_all_indexes(vault):
        try:
            text = idx.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _BASE_FENCE_RE.search(text):
            dirs.add(idx.parent)
    return dirs


def covered_by_base_index(page: pathlib.Path, base_dirs: set[pathlib.Path]) -> bool:
    """True if the page lives under a directory whose index.md is base-backed."""
    for d in base_dirs:
        try:
            page.relative_to(d)
            return True
        except ValueError:
            continue
    return False


def load_private_paths(vault: pathlib.Path) -> list[str]:
    """Vault-relative path prefixes designated private, read from .manifest.json's
    `private_paths` key. Empty list (the default) makes the privacy check a no-op,
    so this is safe for vaults that don't designate any private areas."""
    mf = vault / ".manifest.json"
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pp = data.get("private_paths")
    if not isinstance(pp, list):
        return []
    return [str(p).strip("/").lower() for p in pp if isinstance(p, str) and str(p).strip("/")]


def private_area_for(rel_posix: str, private_paths: list[str]) -> Optional[str]:
    """Longest private-area prefix containing this vault-relative posix path, or None."""
    rl = rel_posix.lower()
    best = None
    for p in private_paths:
        if rl == p or rl.startswith(p + "/"):
            if best is None or len(p) > len(best):
                best = p
    return best


# ---------------------------------------------------------------------------
# Finding dataclass (simple dict factory)
# ---------------------------------------------------------------------------

def finding(severity: str, category: str, file: str,
            message: str, line: Optional[int] = None) -> dict:
    d: dict = {"severity": severity, "category": category, "file": file, "message": message}
    if line is not None:
        d["line"] = line
    return d


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_broken_links_and_orphans(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    resolve,
) -> tuple[list[dict], dict[pathlib.Path, int]]:
    """Returns (findings, incoming_link_count_per_page).

    incoming_link_count_per_page is used for orphan detection and provenance ratio.
    Also checks index.md for broken links.
    """
    findings_out = []
    incoming: dict[pathlib.Path, int] = {p: 0 for p in content_pages}

    pages_to_check = list(content_pages)
    index_path = vault / "index.md"
    if index_path.is_file():
        pages_to_check.append(index_path)

    for page in pages_to_check:
        rel = str(page.relative_to(vault))
        links = extract_wikilinks(page)
        for lineno, target in links:
            resolved = resolve(target)
            if resolved is None:
                findings_out.append(finding(
                    "error", "broken_link", rel,
                    f"broken wikilink: [[{target}]]", lineno,
                ))
            else:
                # index.md is scaffolding: its links don't count as incoming
                # (one orphan definition, shared with wiki-graph.py)
                if resolved in incoming and page != index_path:
                    incoming[resolved] += 1

    # Orphan check. A page catalogued by a base-backed index is reachable via that
    # live query even though it has no hand-written inbound wikilink, so it is not orphaned.
    base_dirs = index_base_dirs(vault)
    for page, count in incoming.items():
        if count == 0 and not covered_by_base_index(page, base_dirs):
            rel = str(page.relative_to(vault))
            findings_out.append(finding(
                "warning", "orphaned_page", rel,
                "page has no incoming wikilinks from other content pages",
            ))

    return findings_out, incoming


def check_frontmatter_fields(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> list[dict]:
    """Check 3 + 4: required fields and summary length."""
    out = []
    for page in content_pages:
        rel = str(page.relative_to(vault))
        fm = load_frontmatter(page)
        if fm is None:
            if page in INVALID_YAML:
                # The block exists but doesn't parse — a different (worse) failure
                # than absent frontmatter: Obsidian silently drops the whole
                # Properties panel. Most common cause: an unquoted `: ` in a value.
                out.append(finding(
                    "error", "invalid_frontmatter", rel,
                    "frontmatter block does not parse as YAML (unquoted ': ' in a "
                    "value? unclosed block?) — Obsidian will not render Properties",
                ))
            else:
                out.append(finding(
                    "error", "missing_frontmatter", rel,
                    f"missing required frontmatter fields: {', '.join(sorted(REQUIRED_FRONTMATTER))}",
                ))
                out.append(finding(
                    "warning", "missing_summary", rel,
                    "summary field missing",
                ))
            continue
        # Check 3: required fields
        missing = [f for f in REQUIRED_FRONTMATTER if f not in fm]
        if missing:
            out.append(finding(
                "error", "missing_frontmatter", rel,
                f"missing required frontmatter fields: {', '.join(sorted(missing))}",
            ))
        # Check 4: summary
        summary = fm.get("summary")
        if summary is None:
            out.append(finding(
                "warning", "missing_summary", rel,
                "summary field missing",
            ))
        elif isinstance(summary, str) and len(summary) > 200:
            out.append(finding(
                "warning", "oversized_summary", rel,
                f"summary is {len(summary)} characters (max 200)",
            ))
    return out


def check_category_folder_match(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> list[dict]:
    """Check: a page's `category` must mirror the folder it lives in.

    The convention is 'categories mirror the folders'. A page's category should be
    its folder path (posix, relative to the vault) — or an ancestor of it, so a
    top-level category on a deeply-nested page (e.g. `ai` on `ai/future-of-the-firm/x`)
    is allowed. A category that is neither the folder nor an ancestor (e.g. `recipes`
    on a page in `cooking/`, `nasadmin` on `sysadmin/nas/`) is drift: it silently
    hides the page from its folder's base-backed index. Warning, not error, because
    the page still resolves — it just files itself under the wrong category.
    Root-level pages (no folder) and pages without a `category` are skipped (the
    latter is already reported by the missing-frontmatter check).
    """
    out = []
    for page in content_pages:
        rel = page.relative_to(vault).as_posix()
        folder = str(pathlib.PurePosixPath(rel).parent)
        if folder in (".", ""):
            continue  # root-level page, no folder to mirror
        fm = load_frontmatter(page)
        if fm is None:
            continue
        category = fm.get("category")
        if not isinstance(category, str) or not category:
            continue  # missing/blank category is the missing_frontmatter check's job
        if category != folder and not folder.startswith(category + "/"):
            out.append(finding(
                "warning", "category_folder_mismatch", rel,
                f"category '{category}' does not mirror its folder '{folder}' "
                f"(set category to '{folder}' or a parent path); as-is the page is "
                f"hidden from the '{folder}' base index",
            ))
    return out


def check_index_consistency(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    resolve,
) -> list[dict]:
    """Check 5: index.md consistency."""
    out = []
    index_path = vault / "index.md"
    if not index_path.is_file():
        return out

    index_text = index_path.read_text(encoding="utf-8", errors="replace")
    index_rel = "index.md"

    # Collect top-level folder names
    top_level_folders = {
        p.name for p in vault.iterdir()
        if p.is_dir() and not p.name.startswith(".") and not p.name.startswith("_")
    }

    # (a) content pages not referenced in ANY index.md (root or a section index).
    # The root index links down to section indexes; pages in a sub-area (e.g. a private
    # namespace) are catalogued in their own second-level index, so a page counts as
    # indexed if *any* index lists it — not only the root.
    index_links = extract_wikilinks(index_path)  # root index, used by (b)-(d) below
    resolved_from_any_index: set[pathlib.Path] = set()
    for idx in find_all_indexes(vault):
        for _lineno, target in extract_wikilinks(idx):
            r = resolve(target)
            if r is not None:
                resolved_from_any_index.add(r)

    base_dirs = index_base_dirs(vault)
    for page in content_pages:
        if page not in resolved_from_any_index and not covered_by_base_index(page, base_dirs):
            rel = str(page.relative_to(vault))
            out.append(finding(
                "warning", "missing_from_index", rel,
                "content page not referenced in any index.md (root or section)",
            ))

    # (b) broken wikilinks in index.md — already covered by check_broken_links_and_orphans
    # but we re-report under index category per spec
    for lineno, target in index_links:
        if resolve(target) is None:
            out.append(finding(
                "error", "index_broken_link", index_rel,
                f"index.md broken wikilink: [[{target}]]", lineno,
            ))

    # (c) ## headings that don't match a top-level folder.
    # Compare case-insensitively: index headings are conventionally Title Case
    # (e.g. "## AI") while folders are kebab-case-lowercase ("ai/"), so a case
    # difference is not a mismatch — only a genuinely different name is.
    # A base-backed root index groups pages by a live query rather than by folder, so its
    # ## headings are editorial section titles, not folder names — skip the match check.
    if not _BASE_FENCE_RE.search(index_text):
        folders_ci = {f.lower() for f in top_level_folders}
        meta_ci = {h.lower() for h in INDEX_META_HEADINGS}
        lines = index_text.splitlines()
        for lineno, line in enumerate(lines, 1):
            m = re.match(r"^##\s+(.+)$", line)
            if m:
                heading = m.group(1).strip()
                if heading.lower() not in folders_ci and heading.lower() not in meta_ci:
                    out.append(finding(
                        "warning", "index_heading_mismatch", index_rel,
                        f"index.md heading '## {heading}' doesn't match a top-level folder",
                        lineno,
                    ))

    # (d) bare-basename wikilinks for pages not at vault root
    for lineno, target in index_links:
        # bare basename: no "/" in target and target doesn't end with .md
        if "/" not in target and not target.endswith(".md"):
            r = resolve(target)
            if r is not None:
                # If the resolved page is NOT at vault root (i.e. has a parent subdir)
                rel_to_vault = r.relative_to(vault)
                if len(rel_to_vault.parts) > 1:
                    out.append(finding(
                        "warning", "index_bare_basename", index_rel,
                        f"bare-basename wikilink [[{target}]] for page not at vault root"
                        f" (should be [[{rel_to_vault.with_suffix('').as_posix()}]])",
                        lineno,
                    ))

    return out


def check_sizes_and_snapshots(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> list[dict]:
    """Check 6: oversized pages, unbounded log.md, and stale dated snapshots.

    - oversized_page: body over OVERSIZED_PAGE_BYTES burns agent tokens on every
      read; split into atomic pages or park raw material under _sources/.
      `living` and `archived` pages are exempt.
    - log_size: log.md is append-only and unbounded; past LOG_SIZE_BYTES suggest
      rolling old entries with `wiki-journal.py --log-trim N`.
    - stale_snapshot: a page whose FILENAME carries a date (a point-in-time
      snapshot) older than STALE_SNAPSHOT_DAYS that is neither archived nor
      marked `superseded_by` — likely superseded by a newer snapshot. The
      `updated:`-based stale_age check misses these because edit hooks bump
      `updated:` on every touch.
    """
    out = []
    snapshot_groups: dict[tuple, list[tuple[str, pathlib.Path]]] = {}

    for page in content_pages:
        rel = str(page.relative_to(vault))
        try:
            size = page.stat().st_size
        except OSError:
            continue
        fm = load_frontmatter(page) or {}
        lifecycle = fm.get("lifecycle")

        if size > OVERSIZED_PAGE_BYTES and lifecycle not in ("living", "archived"):
            out.append(finding(
                "warning", "oversized_page", rel,
                f"page is {size // 1024} KB; split into atomic pages or move raw "
                "material to _sources/ (mark `lifecycle: living` if monolithic by design)",
            ))

        m = _FILENAME_DATE_RE.search(page.stem)
        if m:
            stem_key = (page.parent, _FILENAME_DATE_RE.sub("<date>", page.stem))
            snapshot_groups.setdefault(stem_key, []).append((m.group(1), page))

    # stale_snapshot: within a family of dated pages sharing the same
    # date-stripped stem (planning-<date>, snapshot-<date>, ...), every page
    # that has a NEWER sibling must be wired: `superseded_by` or archived.
    # A lone dated page never fires — this detects unwired successors, not age.
    for (_, _), members in snapshot_groups.items():
        if len(members) < 2:
            continue
        newest = max(d for d, _ in members)
        for d, page in members:
            if d == newest:
                continue
            fm = load_frontmatter(page) or {}
            if fm.get("lifecycle") != "archived" and not fm.get("superseded_by"):
                rel = str(page.relative_to(vault))
                out.append(finding(
                    "warning", "stale_snapshot", rel,
                    f"a newer sibling snapshot ({newest}) exists but this page has "
                    "no `superseded_by` and is not archived — wire the supersession",
                ))

    log_path = vault / "log.md"
    if log_path.is_file():
        log_size = log_path.stat().st_size
        if log_size > LOG_SIZE_BYTES:
            out.append(finding(
                "warning", "log_size", "log.md",
                f"log.md is {log_size // 1024} KB; roll old entries into _archives/ "
                "with `wiki-journal.py --log-trim N`",
            ))

    return out


def _parse_date_leniently(val) -> Optional[date]:
    """Parse a frontmatter date/datetime value as a date. Returns None on failure."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        val = val.strip().rstrip("Z")
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


def check_stale_content(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> list[dict]:
    """Check 7: stale content (source mtime and age)."""
    out = []
    today = datetime.now(timezone.utc).date()

    for page in content_pages:
        rel = str(page.relative_to(vault))
        fm = load_frontmatter(page)
        if fm is None:
            continue
        updated_raw = fm.get("updated")
        updated_date = _parse_date_leniently(updated_raw)
        if updated_date is None:
            continue

        # Age overlay: > 90 days
        age_days = (today - updated_date).days
        if age_days > 90:
            out.append(finding(
                "warning", "stale_age", rel,
                f"stale by age ({age_days} days since last update)",
            ))

        # Local sources mtime check — DISABLED. A source file touched after the
        # page's `updated` date is not reliable staleness signal here (re-saves,
        # OneDrive mtime drift), so it produced false positives. Age check above stays.

    return out


def check_lifecycle(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    resolve,
) -> list[dict]:
    """Check 8: lifecycle values and superseded_by chains."""
    out = []

    # First pass: collect lifecycle per resolved path
    page_lifecycle: dict[pathlib.Path, str] = {}
    page_superseded_by: dict[pathlib.Path, str] = {}  # page -> raw target string

    for page in content_pages:
        fm = load_frontmatter(page)
        if fm is None:
            continue
        lc = fm.get("lifecycle")
        if lc is not None:
            if lc not in VALID_LIFECYCLES:
                rel = str(page.relative_to(vault))
                out.append(finding(
                    "error", "invalid_lifecycle", rel,
                    f"invalid lifecycle value: {lc!r} (must be one of {sorted(VALID_LIFECYCLES)})",
                ))
            else:
                page_lifecycle[page] = lc
        sb = fm.get("superseded_by")
        if sb is not None:
            page_superseded_by[page] = str(sb)

    # Second pass: validate superseded_by targets
    for page, raw_target in page_superseded_by.items():
        rel = str(page.relative_to(vault))
        # Strip wikilink brackets if present
        target = raw_target.strip()
        if target.startswith("[[") and target.endswith("]]"):
            target = target[2:-2].split("|")[0].split("#")[0].strip()

        resolved = resolve(target)
        if resolved is None:
            out.append(finding(
                "error", "broken_superseded_by", rel,
                f"superseded_by target does not resolve: {raw_target!r}",
            ))
            continue

        # Target must not be archived
        target_lc = page_lifecycle.get(resolved)
        if target_lc == "archived":
            out.append(finding(
                "error", "superseded_by_archived", rel,
                f"superseded_by target '{target}' is itself archived",
            ))

        # Inconsistent state: has superseded_by but lifecycle != archived
        own_lc = page_lifecycle.get(page)
        if own_lc != "archived":
            out.append(finding(
                "warning", "inconsistent_supersession", rel,
                f"page has superseded_by but lifecycle is {own_lc!r} (expected 'archived')",
            ))

    # Cycle detection in supersession graph
    def resolve_sb(p: pathlib.Path) -> Optional[pathlib.Path]:
        raw = page_superseded_by.get(p)
        if raw is None:
            return None
        target = raw.strip()
        if target.startswith("[[") and target.endswith("]]"):
            target = target[2:-2].split("|")[0].split("#")[0].strip()
        return resolve(target)

    for page in page_superseded_by:
        visited: set[pathlib.Path] = set()
        cursor = page
        while True:
            nxt = resolve_sb(cursor)
            if nxt is None:
                break
            if nxt in visited:
                rel = str(page.relative_to(vault))
                out.append(finding(
                    "error", "supersession_cycle", rel,
                    f"superseded_by chain contains a cycle starting at {cursor.relative_to(vault)}",
                ))
                break
            visited.add(nxt)
            cursor = nxt

    return out


def check_provenance_ratios(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    incoming: dict[pathlib.Path, int],
) -> tuple[list[dict], list[dict]]:
    """Check 9: provenance marker ratios.

    Returns (findings, provenance_records) where provenance_records go into
    the JSON output's top-level 'provenance' key.
    """
    findings_out = []
    provenance_records = []

    # Top 10 hub pages by incoming link count
    sorted_by_incoming = sorted(incoming.items(), key=lambda x: x[1], reverse=True)
    hub_pages = {p for p, _ in sorted_by_incoming[:10] if _ > 0}

    _INFERRED_RE = re.compile(r"\^\[inferred\]", re.IGNORECASE)
    _AMBIGUOUS_RE = re.compile(r"\^\[ambiguous\]", re.IGNORECASE)

    for page in content_pages:
        rel = str(page.relative_to(vault))
        fm = load_frontmatter(page)
        sources = fm.get("sources") if fm else None
        has_sources = bool(sources and isinstance(sources, list) and len(sources) > 0)

        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()

        # Skip frontmatter
        body_start = 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    body_start = i + 1
                    break

        claim_lines = 0
        inferred_count = 0
        ambiguous_count = 0
        in_fence = False

        for line in lines[body_start:]:
            stripped = line.strip()
            if _FENCE_RE.match(stripped):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            # Skip headings and blank lines
            if not stripped or stripped.startswith("#"):
                continue
            # Count as a claim line
            claim_lines += 1
            if _INFERRED_RE.search(line):
                inferred_count += 1
            if _AMBIGUOUS_RE.search(line):
                ambiguous_count += 1

        if claim_lines == 0:
            continue

        inferred_frac = inferred_count / claim_lines
        ambiguous_frac = ambiguous_count / claim_lines

        flags = []
        if ambiguous_frac > 0.15:
            flags.append(f"speculation-heavy ({ambiguous_frac:.0%} ambiguous)")
        if inferred_frac > 0.40 and not has_sources:
            flags.append(f"unsourced synthesis ({inferred_frac:.0%} inferred, no sources)")
        if page in hub_pages and inferred_frac > 0.20:
            flags.append(f"high-traffic page, questionable provenance ({inferred_frac:.0%} inferred)")

        provenance_records.append({
            "file": rel,
            "claim_lines": claim_lines,
            "inferred": round(inferred_frac, 3),
            "ambiguous": round(ambiguous_frac, 3),
            "flags": flags,
        })

        for flag in flags:
            findings_out.append(finding(
                "warning", "provenance_ratio", rel,
                flag,
            ))

    return findings_out, provenance_records


def check_misc_promotion(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    resolve,
) -> list[dict]:
    """Check 10: misc/ pages with strong project affinity."""
    out = []
    misc_dir = vault / "misc"
    if not misc_dir.is_dir():
        return out

    misc_pages = [p for p in content_pages if p.is_relative_to(misc_dir)]
    if not misc_pages:
        return out

    projects_dir = vault / "projects"
    has_projects = projects_dir.is_dir()

    def project_for_page(p: pathlib.Path) -> Optional[str]:
        """Return project name if page lives under projects/<name>/."""
        if not has_projects:
            return None
        try:
            rel = p.relative_to(projects_dir)
            if rel.parts:
                return rel.parts[0]
        except ValueError:
            pass
        return None

    def project_from_fm(p: pathlib.Path) -> Optional[str]:
        fm = load_frontmatter(p)
        if fm:
            return fm.get("project")
        return None

    # Build outgoing links map for misc pages
    for misc_page in misc_pages:
        rel = str(misc_page.relative_to(vault))
        links = extract_wikilinks(misc_page)

        # Count inbound links to this misc page from project pages
        # (build inline — small N)
        project_affinity: dict[str, int] = {}

        # Outgoing links from misc page to project pages
        for _lineno, target in links:
            r = resolve(target)
            if r is None:
                continue
            proj = project_for_page(r) or project_from_fm(r)
            if proj:
                project_affinity[proj] = project_affinity.get(proj, 0) + 1

        # Incoming links from project pages to this misc page
        for page in content_pages:
            if page == misc_page:
                continue
            proj = project_for_page(page)
            if proj is None:
                continue
            page_links = extract_wikilinks(page)
            for _lineno, target in page_links:
                r = resolve(target)
                if r == misc_page:
                    project_affinity[proj] = project_affinity.get(proj, 0) + 1

        if not project_affinity:
            continue
        top_proj, top_count = max(project_affinity.items(), key=lambda x: x[1])
        if top_count >= 3:
            out.append(finding(
                "warning", "misc_promotion_candidate", rel,
                f"consider promoting to project '{top_proj}' ({top_count} link(s) to/from it)",
            ))

    return out


def check_index_privacy_leak(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    resolve,
    private_paths: list[str],
) -> list[dict]:
    """Check 11: a private content page must not be listed in a more-public index.

    A page under a private area P may only be catalogued in index.md files that live
    inside P (its own second-level index). A more-public index (the shareable root, or
    an index in another area) must reference P only via a link to P's own section
    index — never by listing P's content pages, since the entry carries the summary.

    Index→section-index links are inherently exempt: a section index is scaffolding,
    not a content page, so it never appears in `content_pages` and is skipped below.
    No-op when the vault designates no private_paths.
    """
    out = []
    if not private_paths:
        return out
    content_set = set(content_pages)
    for idx in find_all_indexes(vault):
        idx_rel = idx.relative_to(vault).as_posix()
        for lineno, target in extract_wikilinks(idx):
            r = resolve(target)
            if r is None or r not in content_set:
                continue  # unresolved, or a section index (scaffolding) — fine
            page_area = private_area_for(r.relative_to(vault).as_posix(), private_paths)
            if page_area is None:
                continue  # linked page isn't private
            if idx_rel.startswith(page_area + "/"):
                continue  # index lives inside the page's private area — in scope
            out.append(finding(
                "error", "index_privacy_leak", idx_rel,
                f"private page [[{target}]] is listed in a more-public index — "
                f"link to the '{page_area}' section index instead", lineno,
            ))
    return out


def check_date_format(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> list[dict]:
    """Check 12: date fields must be date-only yyyy-MM-dd.

    yaml.safe_load already types unquoted values, so the value's Python type is
    the test: a datetime.date is the convention; a datetime.datetime means the
    file carries a full ISO datetime (the update-timestamp hook writes date-only,
    so these come from manual edits or old templates); a quoted value stays a
    string and must match yyyy-MM-dd exactly.
    """
    out = []
    for page in content_pages:
        fm = load_frontmatter(page)
        if fm is None:
            continue
        rel = str(page.relative_to(vault))
        for field in DATE_ONLY_FIELDS:
            val = fm.get(field)
            if val is None:
                continue
            if isinstance(val, datetime):  # test before date — datetime subclasses it
                desc = f"a full ISO datetime ({val.isoformat()})"
            elif isinstance(val, date):
                continue
            elif isinstance(val, str) and _DATE_ONLY_RE.match(val.strip()):
                continue
            else:
                desc = f"{val!r}"
            out.append(finding(
                "warning", "date_format", rel,
                f"`{field}:` is {desc} — date fields are date-only yyyy-MM-dd",
            ))
    return out


# ---------------------------------------------------------------------------
# Per-page suppression (lint_ignore)
# ---------------------------------------------------------------------------

def _lint_ignore_keys(fm: Optional[dict]) -> set[str]:
    """Check keys listed in a page's `lint_ignore:` frontmatter (list, or a bare
    string treated as a one-element list). Empty set for anything else."""
    if not fm:
        return set()
    raw = fm.get("lint_ignore")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {str(k).strip() for k in raw if str(k).strip()}


def collect_lint_ignore(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> tuple[dict[str, set[str]], list[dict]]:
    """Per-page `lint_ignore:` suppression sets, plus findings for unknown keys.

    Returns (finding-file-key → check keys to suppress, findings). Only
    warning-level findings are suppressible — errors always report. A listed key
    that is not a known check key (the _CATEGORY_SECTION keys) gets a
    lint_ignore_unknown warning: a typo would otherwise silently suppress nothing.
    """
    known = set(_CATEGORY_SECTION)
    ignore_map: dict[str, set[str]] = {}
    out = []
    for page in content_pages:
        keys = _lint_ignore_keys(load_frontmatter(page))
        if not keys:
            continue
        rel = page.relative_to(vault)
        for k in sorted(keys - known):
            out.append(finding(
                "warning", "lint_ignore_unknown", str(rel),
                f"lint_ignore lists unknown check key {k!r} — it suppresses "
                "nothing (keys are the finding categories, e.g. 'stale_snapshot')",
            ))
        good = keys & known
        if good:
            # Key by both path spellings: finding files use str() or as_posix()
            # depending on the check, and the two differ on native Windows.
            for fkey in {str(rel), rel.as_posix()}:
                ignore_map[fkey] = good
    return ignore_map, out


# ---------------------------------------------------------------------------
# Fix pass (--fix) — deterministic mechanical fixes, applied before the checks
# ---------------------------------------------------------------------------

def _split_wikilink_inner(raw: str) -> tuple[str, str]:
    """Split a wikilink's inner text into (path, suffix), where suffix is the
    #heading / ^block / |alias tail, kept verbatim (including a table-escaped \\|)."""
    for i, ch in enumerate(raw):
        if ch in "#^":
            return raw[:i], raw[i:]
        if ch == "|":
            if i > 0 and raw[i - 1] == "\\":
                return raw[:i - 1], raw[i - 1:]
            return raw[:i], raw[i:]
    return raw, ""


def build_fix_candidates(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> dict[str, list[pathlib.Path]]:
    """Lowercased basename → paths, for link completion: content pages by stem,
    non-md attachments by full filename. Dot/underscore dirs excluded — a link
    should never be rewritten to point into staging or infrastructure."""
    by_key: dict[str, list[pathlib.Path]] = {}
    for p in content_pages:
        by_key.setdefault(p.stem.lower(), []).append(p)
    for f in sorted(vault.rglob("*")):
        if not f.is_file() or f.suffix == ".md":
            continue
        rel = f.relative_to(vault)
        if any(part.startswith(".") or part.startswith("_") for part in rel.parts):
            continue
        by_key.setdefault(f.name.lower(), []).append(f)
    return by_key


def fix_link_paths(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
    resolve,
) -> int:
    """Fix class (a): complete a bare-basename wikilink to its full vault-relative
    path when the target is unambiguous.

    Two cases, mirroring the checks that would otherwise report them:
      - a broken link (resolver failed) whose basename matches exactly ONE
        candidate — a content page by stem, or a non-md attachment by filename;
      - a bare-basename link in the root index.md that resolves to a page not at
        vault root (the index_bare_basename warning).
    Zero or multiple candidates: leave the link alone and let the check report it.
    Pathed links (containing '/') are never rewritten. Returns fixes applied.
    """
    candidates = build_fix_candidates(vault, content_pages)
    fixed = 0
    index_path = vault / "index.md"
    pages = list(content_pages)
    if index_path.is_file():
        pages.append(index_path)

    for page in pages:
        rel = str(page.relative_to(vault))
        is_index = page == index_path
        try:
            # newline='' keeps CRLF intact so the rewrite stays byte-surgical
            with open(page, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except OSError:
            continue
        lines = text.split("\n")

        # Skip frontmatter (same extent logic as extract_wikilinks)
        start = 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    start = i + 1
                    break

        applied: list[tuple[str, str]] = []

        def _sub(m: re.Match) -> str:
            raw = m.group(1)
            path_part, suffix = _split_wikilink_inner(raw)
            target = path_part.strip()
            if not target or "/" in target:
                return m.group(0)
            new = None
            resolved = resolve(target)
            if resolved is None:
                matches = candidates.get(target.lower(), [])
                if len(matches) == 1:
                    trel = matches[0].relative_to(vault)
                    # .md pages link without extension; attachments keep theirs
                    new = (trel.with_suffix("").as_posix()
                           if matches[0].suffix == ".md" else trel.as_posix())
            elif is_index:
                trel = resolved.relative_to(vault)
                if len(trel.parts) > 1:
                    new = trel.with_suffix("").as_posix()
            if new is None or new == target:
                return m.group(0)
            applied.append((raw, new + suffix))
            return f"[[{new}{suffix}]]"

        in_fence = False
        for i in range(start, len(lines)):
            if _FENCE_RE.match(lines[i].strip()):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            lines[i] = _WIKILINK_RE.sub(_sub, lines[i])

        if applied:
            with open(page, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join(lines))
            _LINK_CACHE.pop(page, None)
            for old, new in applied:
                print(f"fixed    {rel} — [[{old}]] → [[{new}]]")
            fixed += len(applied)
    return fixed


def _wire_supersession(page: pathlib.Path, target_rel: str, today: str) -> bool:
    """Textually set superseded_by / lifecycle / lifecycle_changed in the page's
    frontmatter: replace existing top-level scalar lines in place, insert missing
    ones before the closing ---. Never re-dumps YAML, preserves formatting and
    line endings. Returns False (nothing written) when the block is missing or an
    existing key holds a non-scalar value we can't safely swap."""
    try:
        with open(page, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except OSError:
        return False
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return False

    updates = [
        ("superseded_by", target_rel),
        ("lifecycle", "archived"),
        ("lifecycle_changed", today),
    ]
    # Locate existing lines first and bail before touching anything: a bare
    # `key:` followed by an indented continuation is a block value, not a line
    # we can swap.
    positions: dict[str, int] = {}
    for key, _ in updates:
        for i in range(1, end):
            m = re.match(rf"{key}:(.*)$", lines[i])
            if m:
                if not m.group(1).strip() and i + 1 < end and lines[i + 1][:1] in (" ", "\t"):
                    return False
                positions[key] = i
                break
    for key, value in updates:
        if key in positions:
            i = positions[key]
            eol = "\r" if lines[i].endswith("\r") else ""
            lines[i] = f"{key}: {value}{eol}"
        else:
            eol = "\r" if lines[end - 1].endswith("\r") else ""
            lines.insert(end, f"{key}: {value}{eol}")
            end += 1
    with open(page, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines))
    _FM_CACHE.pop(page, None)
    _LINK_CACHE.pop(page, None)
    return True


def fix_snapshot_supersession(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> int:
    """Fix class (b): wire supersession on stale dated snapshots.

    Same family grouping as check_sizes_and_snapshots: dated pages sharing a
    date-stripped stem. Every non-newest member that is neither archived nor
    wired gets `superseded_by` → the newest sibling, `lifecycle: archived`, and
    `lifecycle_changed: today`. Skipped when the page suppresses stale_snapshot
    via lint_ignore, when two siblings tie for newest (ambiguous target), or when
    the newest sibling is itself archived (wiring to it would trade the warning
    for a superseded_by_archived error). Returns fixes applied.
    """
    today = date.today().isoformat()
    snapshot_groups: dict[tuple, list[tuple[str, pathlib.Path]]] = {}
    for page in content_pages:
        m = _FILENAME_DATE_RE.search(page.stem)
        if m:
            stem_key = (page.parent, _FILENAME_DATE_RE.sub("<date>", page.stem))
            snapshot_groups.setdefault(stem_key, []).append((m.group(1), page))

    fixed = 0
    for members in snapshot_groups.values():
        if len(members) < 2:
            continue
        newest = max(d for d, _ in members)
        newest_pages = [p for d, p in members if d == newest]
        if len(newest_pages) != 1:
            continue
        target_page = newest_pages[0]
        if (load_frontmatter(target_page) or {}).get("lifecycle") == "archived":
            continue
        target_rel = target_page.relative_to(vault).with_suffix("").as_posix()
        for d, page in members:
            if d == newest:
                continue
            fm = load_frontmatter(page)
            if fm is None:
                continue  # missing/unparseable frontmatter — no safe place to edit
            if fm.get("lifecycle") == "archived" or fm.get("superseded_by"):
                continue  # already wired — the check wouldn't flag it
            if "stale_snapshot" in _lint_ignore_keys(fm):
                continue  # page opted out of the check — respect that for the fix
            if _wire_supersession(page, target_rel, today):
                rel = str(page.relative_to(vault))
                print(f"fixed    {rel} — superseded_by: {target_rel}; lifecycle: archived")
                fixed += 1
    return fixed


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

_CATEGORY_SECTION = {
    "broken_link": "Broken Wikilinks",
    "index_broken_link": "Broken Wikilinks (Index)",
    "orphaned_page": "Orphaned Pages",
    "missing_frontmatter": "Missing Required Frontmatter",
    "invalid_frontmatter": "Invalid Frontmatter (YAML does not parse)",
    "missing_summary": "Missing Summary",
    "oversized_summary": "Oversized Summary",
    "category_folder_mismatch": "Category Does Not Mirror Folder",
    "missing_from_index": "Missing from Index",
    "index_heading_mismatch": "Index Heading Mismatches",
    "index_bare_basename": "Index Bare-Basename Wikilinks",
    "oversized_page": "Oversized Pages",
    "log_size": "Log Growth",
    "stale_snapshot": "Stale Dated Snapshots",
    "stale_age": "Stale Pages (Age)",
    "invalid_lifecycle": "Invalid Lifecycle",
    "broken_superseded_by": "Broken Superseded-By",
    "superseded_by_archived": "Superseded-By Points to Archived",
    "inconsistent_supersession": "Inconsistent Supersession State",
    "supersession_cycle": "Supersession Cycle",
    "provenance_ratio": "Provenance Ratio Flags",
    "misc_promotion_candidate": "Misc Promotion Candidates",
    "index_privacy_leak": "Index Privacy Leak (private page in a more-public index)",
    "date_format": "Date Fields Not Date-Only",
    "lint_ignore_unknown": "Unknown lint_ignore Keys",
}


def format_md(vault: pathlib.Path, findings: list[dict], provenance: list[dict],
              pages_checked: int, errors_only: bool = False) -> str:
    lines = ["## Wiki Health Report", ""]
    lines.append(f"Vault: `{vault}`  |  Pages checked: {pages_checked}")
    lines.append("")

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for f in findings:
        by_cat.setdefault(f["category"], []).append(f)

    if not findings:
        lines.append("_No findings. Vault is clean._")
    else:
        for cat, items in sorted(by_cat.items()):
            section = _CATEGORY_SECTION.get(cat, cat)
            lines.append(f"### {section} ({len(items)} found)")
            lines.append("")
            for item in items:
                loc = item["file"]
                if "line" in item:
                    loc += f":{item['line']}"
                sev = item["severity"].upper()
                lines.append(f"- [{sev}] `{loc}` — {item['message']}")
            lines.append("")

    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    if errors_only:
        # warnings were filtered out before formatting — don't claim a count of 0
        lines.append(f"{errors} errors across {pages_checked} pages checked (warnings suppressed).")
    else:
        lines.append(f"{errors} errors, {warnings} warnings across {pages_checked} pages checked.")
    return "\n".join(lines)


def format_json(vault: pathlib.Path, findings: list[dict], provenance: list[dict],
                pages_checked: int) -> str:
    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    out = {
        "vault": str(vault),
        "pages_checked": pages_checked,
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
        "provenance": provenance,
    }
    return json.dumps(out, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_page_globs(vault: pathlib.Path, patterns: list[str]) -> set[str]:
    """Expand --pages patterns (vault-relative paths or globs) to a set of
    vault-relative posix paths that exist. Warns on patterns matching nothing."""
    selected: set[str] = set()
    for pat in patterns:
        matched = False
        direct = vault / pat
        if direct.is_file():
            selected.add(direct.relative_to(vault).as_posix())
            matched = True
        else:
            for m in vault.glob(pat):
                if m.is_file():
                    selected.add(m.relative_to(vault).as_posix())
                    matched = True
        if not matched:
            print(f"warning: --pages pattern matched no files: {pat}", file=sys.stderr)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic linter for an Obsidian LLM-wiki vault.",
    )
    parser.add_argument(
        "vault", nargs="?", default=None,
        help="Path to vault root (positional). If omitted, auto-detected.",
    )
    parser.add_argument(
        "--vault", dest="vault_flag", default=None,
        help="Path to vault root. Overrides the positional arg and auto-detection.",
    )
    parser.add_argument(
        "--format", choices=["json", "md"], default="json",
        help="Output format: json (default) or md (markdown report).",
    )
    parser.add_argument(
        "--pages", nargs="+", metavar="PATH",
        help="One or more vault-relative paths or globs. Scopes REPORTED findings to "
             "just these pages; graph-wide checks still compute against the full vault.",
    )
    parser.add_argument(
        "--errors-only", action="store_true",
        help="Report only error-level findings (terse, for a git pre-commit gate). "
             "Warnings are neither shown nor counted; exit code semantics unchanged.",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Apply safe mechanical fixes before checking: complete unambiguous "
             "broken/bare-basename wikilinks to full vault-relative paths, and wire "
             "superseded_by + lifecycle on stale dated snapshots. One line per fix; "
             "the report then reflects the post-fix state.",
    )
    args = parser.parse_args()

    if args.fix and args.errors_only:
        parser.error("--fix cannot be combined with --errors-only")

    vault = resolve_vault(args.vault_flag or args.vault)

    # Collect all .md files, build content page list
    all_md: list[pathlib.Path] = []
    for f in sorted(vault.rglob("*.md")):
        rel = f.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts):
            continue
        all_md.append(f)

    content_pages = [
        f for f in all_md
        if is_content_page(pathlib.PurePosixPath(f.relative_to(vault).as_posix()))
    ]

    resolve = build_resolver(vault, content_pages)
    private_paths = load_private_paths(vault)

    # --fix: apply the two mechanical fix classes first, so the report below
    # reflects the post-fix state (a completed link stops being a broken_link,
    # a wired snapshot stops being a stale_snapshot).
    if args.fix:
        fix_link_paths(vault, content_pages, resolve)
        fix_snapshot_supersession(vault, content_pages)

    all_findings: list[dict] = []

    # Check 2 + 1: broken links and orphans (also covers check 5b for index)
    link_findings, incoming = check_broken_links_and_orphans(vault, content_pages, resolve)
    all_findings.extend(link_findings)

    # Check 3 + 4: frontmatter fields and summary
    all_findings.extend(check_frontmatter_fields(vault, content_pages))

    # Check 4b: category mirrors the folder (else the page hides from its folder base)
    all_findings.extend(check_category_folder_match(vault, content_pages))

    # Check 5: index consistency
    all_findings.extend(check_index_consistency(vault, content_pages, resolve))

    # Check 6: sizes and snapshots (oversized pages, log growth, stale dated snapshots)
    all_findings.extend(check_sizes_and_snapshots(vault, content_pages))

    # Check 7: stale content
    all_findings.extend(check_stale_content(vault, content_pages))

    # Check 8: lifecycle + supersession
    all_findings.extend(check_lifecycle(vault, content_pages, resolve))

    # Check 9: provenance ratios
    prov_findings, provenance_records = check_provenance_ratios(vault, content_pages, incoming)
    all_findings.extend(prov_findings)

    # Check 10: misc promotion candidates
    all_findings.extend(check_misc_promotion(vault, content_pages, resolve))

    # Check 11: index privacy leak
    all_findings.extend(check_index_privacy_leak(vault, content_pages, resolve, private_paths))

    # Check 12: date-only date fields
    all_findings.extend(check_date_format(vault, content_pages))

    # Per-page suppression: a warning whose check key is listed in its page's
    # `lint_ignore:` frontmatter is dropped before reporting, so it counts toward
    # neither the summary nor the exit code. Errors are never suppressible.
    ignore_map, ignore_findings = collect_lint_ignore(vault, content_pages)
    all_findings.extend(ignore_findings)
    all_findings = [
        f for f in all_findings
        if not (f["severity"] == "warning"
                and f["category"] in ignore_map.get(f["file"], ()))
    ]

    pages_checked = len(content_pages)

    # --pages: everything above computed against the whole vault (so graph-wide
    # checks — orphans, incoming links, index coverage — stay correct); now scope
    # what we REPORT down to the requested pages by their file key.
    if args.pages:
        page_filter = resolve_page_globs(vault, args.pages)
        all_findings = [f for f in all_findings if f["file"] in page_filter]
        provenance_records = [p for p in provenance_records if p["file"] in page_filter]
        pages_checked = len(page_filter)

    # --errors-only: warnings (and the warning-flavoured provenance records) are
    # dropped entirely — not shown, not counted. Exit code is unchanged either way.
    if args.errors_only:
        all_findings = [f for f in all_findings if f["severity"] == "error"]
        provenance_records = []

    if args.format == "md":
        print(format_md(vault, all_findings, provenance_records, pages_checked,
                        errors_only=args.errors_only))
    else:
        print(format_json(vault, all_findings, provenance_records, pages_checked))

    has_errors = any(f["severity"] == "error" for f in all_findings)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
