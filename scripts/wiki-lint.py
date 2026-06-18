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
  3. Missing required frontmatter — title, category, tags, sources, created, updated.
  4. Summary field — missing or over 200 characters.
  5. Index consistency — pages missing from index, bad section headings, etc.
  6. Hardcoded inventory counts — brittle "N pages/skills/…" phrases in prose.
  7. Stale content — source files modified after page's updated date; age > 90 days.
  8. Lifecycle + supersession — invalid lifecycle values, broken/cyclic superseded_by.
  9. Provenance marker ratios — ^[inferred] / ^[ambiguous] density by page.
  10. Misc promotion candidates — misc/ pages with strong affinity to a project.
  11. Index privacy leak — a private page (or its summary) listed in a more-public index.

Usage:
  uv run .claude/wiki-scripts/wiki-lint.py [VAULT] [--format json|md]

Exit codes:
  0  no error-level findings
  1  at least one error-level finding exists

Read-only — never writes to the vault. See README.md in this directory.
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

SCAFFOLDING = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md"}

REQUIRED_FRONTMATTER = {"title", "category", "tags", "sources", "created", "updated"}

VALID_LIFECYCLES = {"draft", "reviewed", "living", "archived"}

# Headings in index.md that are allowed even if they don't match a real folder
INDEX_META_HEADINGS = {"Root", "Meta", "Index", "Overview"}

# Regex for hardcoded inventory counts (check 6)
_COUNT_PATTERNS = [
    re.compile(r"\b\d+\s+(?:pages|skills|scripts|sources|abstracts|notes|entries|files|servers|recipes)\b", re.IGNORECASE),
    re.compile(r"\ball\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bthe\s+\d+\s+", re.IGNORECASE),
    re.compile(r"\b\d+\+\s"),
]

# Regex to extract wikilinks:  [[target]]  or  [[target|display]]
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Fenced code block detector
_FENCE_RE = re.compile(r"^```")


# ---------------------------------------------------------------------------
# Vault discovery (same logic as validate-frontmatter.py)
# ---------------------------------------------------------------------------

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
    return True


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def load_frontmatter(path: pathlib.Path) -> Optional[dict]:
    """Parse YAML frontmatter from a file. Returns dict or None on any failure."""
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
        return None
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


# ---------------------------------------------------------------------------
# Wikilink extraction (skips fenced code blocks and frontmatter)
# ---------------------------------------------------------------------------

def extract_wikilinks(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return [(line_number, target), …] for wikilinks outside frontmatter and code blocks.

    line_number is 1-based. target has #heading / ^block suffixes stripped.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
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
                if resolved in incoming:
                    incoming[resolved] += 1

    # Orphan check
    for page, count in incoming.items():
        if count == 0:
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
            # Report all required fields as missing
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

    for page in content_pages:
        if page not in resolved_from_any_index:
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


def check_hardcoded_counts(
    vault: pathlib.Path,
    content_pages: list[pathlib.Path],
) -> list[dict]:
    """Check 6: hardcoded inventory counts."""
    out = []
    # Files to check: index.md, log.md, any README.md, and content pages
    extra_paths = []
    for name in ("index.md", "log.md"):
        p = vault / name
        if p.is_file():
            extra_paths.append(p)
    for p in vault.rglob("README.md"):
        rel = p.relative_to(vault)
        if not any(part.startswith(".") for part in rel.parts):
            extra_paths.append(p)

    all_targets = list(content_pages) + extra_paths
    seen_paths: set[pathlib.Path] = set()
    deduped = []
    for p in all_targets:
        if p not in seen_paths:
            seen_paths.add(p)
            deduped.append(p)

    for page in deduped:
        rel = str(page.relative_to(vault))
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()

        # Determine body start (skip frontmatter)
        body_start = 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    body_start = i + 1
                    break

        in_fence = False
        for lineno, line in enumerate(lines[body_start:], start=body_start + 1):
            if _FENCE_RE.match(line.strip()):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for pat in _COUNT_PATTERNS:
                m = pat.search(line)
                if m:
                    out.append(finding(
                        "warning", "hardcoded_count", rel,
                        f"hardcoded inventory count: {m.group(0)!r}", lineno,
                    ))
                    break  # one finding per line

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

        # Local sources mtime check
        sources = fm.get("sources")
        if not isinstance(sources, list):
            continue
        for src in sources:
            if not isinstance(src, str):
                continue
            if src.startswith("http://") or src.startswith("https://"):
                continue
            src_path = vault / src
            if not src_path.is_file():
                continue
            src_mtime = datetime.fromtimestamp(src_path.stat().st_mtime, timezone.utc).date()
            if src_mtime > updated_date:
                out.append(finding(
                    "warning", "stale_source", rel,
                    f"source '{src}' modified ({src_mtime}) after page updated ({updated_date})",
                ))

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


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

_CATEGORY_SECTION = {
    "broken_link": "Broken Wikilinks",
    "index_broken_link": "Broken Wikilinks (Index)",
    "orphaned_page": "Orphaned Pages",
    "missing_frontmatter": "Missing Required Frontmatter",
    "missing_summary": "Missing Summary",
    "oversized_summary": "Oversized Summary",
    "missing_from_index": "Missing from Index",
    "index_heading_mismatch": "Index Heading Mismatches",
    "index_bare_basename": "Index Bare-Basename Wikilinks",
    "hardcoded_count": "Hardcoded Inventory Counts",
    "stale_age": "Stale Pages (Age)",
    "stale_source": "Stale Pages (Source Modified)",
    "invalid_lifecycle": "Invalid Lifecycle",
    "broken_superseded_by": "Broken Superseded-By",
    "superseded_by_archived": "Superseded-By Points to Archived",
    "inconsistent_supersession": "Inconsistent Supersession State",
    "supersession_cycle": "Supersession Cycle",
    "provenance_ratio": "Provenance Ratio Flags",
    "misc_promotion_candidate": "Misc Promotion Candidates",
    "index_privacy_leak": "Index Privacy Leak (private page in a more-public index)",
}


def format_md(vault: pathlib.Path, findings: list[dict], provenance: list[dict],
              pages_checked: int) -> str:
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

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic linter for an Obsidian LLM-wiki vault.",
    )
    parser.add_argument(
        "vault", nargs="?", default=None,
        help="Path to vault root. If omitted, auto-detected via .manifest.json walk-up.",
    )
    parser.add_argument(
        "--format", choices=["json", "md"], default="json",
        help="Output format: json (default) or md (markdown report).",
    )
    args = parser.parse_args()

    if args.vault:
        vault = pathlib.Path(args.vault).resolve()
        if not vault.is_dir():
            raise SystemExit(f"Vault path does not exist or is not a directory: {vault}")
    else:
        vault = find_vault()

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

    all_findings: list[dict] = []

    # Check 2 + 1: broken links and orphans (also covers check 5b for index)
    link_findings, incoming = check_broken_links_and_orphans(vault, content_pages, resolve)
    all_findings.extend(link_findings)

    # Check 3 + 4: frontmatter fields and summary
    all_findings.extend(check_frontmatter_fields(vault, content_pages))

    # Check 5: index consistency
    all_findings.extend(check_index_consistency(vault, content_pages, resolve))

    # Check 6: hardcoded counts
    all_findings.extend(check_hardcoded_counts(vault, content_pages))

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

    pages_checked = len(content_pages)

    if args.format == "md":
        print(format_md(vault, all_findings, provenance_records, pages_checked))
    else:
        print(format_json(vault, all_findings, provenance_records, pages_checked))

    has_errors = any(f["severity"] == "error" for f in all_findings)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
