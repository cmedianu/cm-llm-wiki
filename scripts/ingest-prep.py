#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Single-call prep tool for the start of a wiki ingest.

Replaces the 4-5 ad-hoc shell/grep round-trips a skill otherwise burns before
distilling a source: list categories, read private_paths, check whether the
source is already tracked, see which category indexes are base-backed (live
queries that need no manual edit), and surface pages related to the source's
keywords. Read-only — never writes to the vault. Emits JSON to stdout.

Two modes:

  # Prep mode — everything the ingest needs to know up front.
  ingest-prep.py --vault <path> --source <file> [--keywords "kw1,kw2"]

  # Backlinks mode — for each listed page, find content pages that mention it
  # by a distinctive term but don't yet link to it (link candidates).
  ingest-prep.py --vault <path> --backlinks-for "sysadmin/a.md,sysadmin/b.md"

--vault is optional; when omitted it is resolved the standard way (walk up from
CWD for .manifest.json, then ~/.obsidian-wiki/projects.json). See README.md.
"""

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
from typing import Optional

import yaml

SCAFFOLDING = {"index.md", "log.md", "hot.md", "README.md", "CLAUDE.md", "AGENTS.md"}
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_FENCE_RE = re.compile(r"^```")
_BASE_FENCE_RE = re.compile(r"(?m)^\s*`{3,}\s*base\b")
RELATED_CAP = 20

# Generic words that carry no distinguishing signal for backlink candidates.
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "over", "under",
    "your", "you", "our", "are", "was", "were", "has", "have", "had", "not",
    "how", "why", "what", "when", "where", "which", "who", "will", "can", "using",
    "use", "used", "guide", "notes", "note", "page", "pages", "index", "about",
    "onto", "than", "then", "them", "they", "its", "it's", "via", "per", "more",
    "less", "some", "any", "all", "each", "other", "also", "such", "only",
}


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
# Shared helpers
# ---------------------------------------------------------------------------

def is_content_page(rel: pathlib.PurePosixPath) -> bool:
    """True for a content page — not scaffolding, not under a dot/underscore dir."""
    if any(p.startswith(".") or p.startswith("_") for p in rel.parts):
        return False
    if rel.name in SCAFFOLDING:
        return False
    return True


def content_pages(vault: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for f in sorted(vault.rglob("*.md")):
        rel = pathlib.PurePosixPath(f.relative_to(vault).as_posix())
        if is_content_page(rel):
            out.append(f)
    return out


def load_frontmatter(path: pathlib.Path) -> Optional[dict]:
    """Parse a page's YAML frontmatter. Returns dict, or None on any failure."""
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
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract_wikilink_targets(text: str) -> list[str]:
    """Wikilink targets outside frontmatter and fenced code blocks, lowercased,
    with alias/anchor suffixes stripped."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    targets = []
    in_fence = False
    for line in lines[start:]:
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _WIKILINK_RE.finditer(line):
            raw = m.group(1).replace("\\|", "|").split("|")[0].strip()
            raw = re.split(r"[#^]", raw)[0].strip()
            if raw:
                targets.append(raw.lower())
    return targets


def load_private_paths(vault: pathlib.Path) -> list[str]:
    try:
        data = json.loads((vault / ".manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pp = data.get("private_paths")
    if not isinstance(pp, list):
        return []
    return [str(p) for p in pp if isinstance(p, str) and str(p).strip()]


def top_level_categories(vault: pathlib.Path) -> list[str]:
    return sorted(
        p.name for p in vault.iterdir()
        if p.is_dir() and not p.name.startswith(".") and not p.name.startswith("_")
    )


def category_base_backed(vault: pathlib.Path, categories: list[str]) -> dict:
    """category -> True when <category>/index.md embeds a ```base view (a live
    catalog that lists pages for you), False for hand-curated or missing index."""
    out = {}
    for cat in categories:
        idx = vault / cat / "index.md"
        out[cat] = bool(idx.is_file() and _BASE_FENCE_RE.search(read_text(idx)))
    return out


# ---------------------------------------------------------------------------
# Prep mode
# ---------------------------------------------------------------------------

def manifest_status(vault: pathlib.Path, source: pathlib.Path) -> tuple[str, Optional[str]]:
    """(status, manifest_key). status is 'new' | 'modified' | 'unchanged'.

    Match order: exact vault-relative path, then '_sources/<basename>', then any
    manifest key sharing the source's basename (covers a source that lives outside
    the vault, or a raw _sources/ file whose distilled page is tracked instead)."""
    try:
        data = json.loads((vault / ".manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("new", None)
    sources = data.get("sources", {})
    if not isinstance(sources, dict):
        return ("new", None)

    src = source.resolve()
    base = src.name
    key = None
    try:
        rel = src.relative_to(vault.resolve()).as_posix()
    except ValueError:
        rel = None
    if rel and rel in sources:
        key = rel
    elif f"_sources/{base}" in sources:
        key = f"_sources/{base}"
    else:
        by_base = [k for k in sources if k.rsplit("/", 1)[-1] == base]
        if by_base:
            key = sorted(by_base)[0]

    if key is None:
        return ("new", None)

    entry = sources[key]
    try:
        st = src.stat()
    except OSError:
        return ("unchanged", key)
    mtime = datetime.datetime.fromtimestamp(
        st.st_mtime, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if entry.get("size_bytes") != st.st_size or entry.get("mtime") != mtime:
        return ("modified", key)
    return ("unchanged", key)


def related_pages(vault: pathlib.Path, keywords: list[str]) -> list[dict]:
    """Pages matching any keyword (case-insensitive) in title, tags, summary,
    filename, or body. Ordered strongest-first (frontmatter/title/filename hit
    outranks a body-only hit), capped at RELATED_CAP."""
    scored = []
    for page in content_pages(vault):
        rel = page.relative_to(vault).as_posix()
        fm = load_frontmatter(page) or {}
        title = str(fm.get("title") or "")
        summary = fm.get("summary")
        summary = str(summary) if summary is not None else ""
        tags = fm.get("tags")
        if isinstance(tags, list):
            tags_str = " ".join(str(t) for t in tags)
        else:
            tags_str = str(tags or "")
        stem = page.stem
        strong_blob = " ".join([title, tags_str, summary, stem]).lower()
        body = read_text(page).lower()

        strong_hits = sum(1 for kw in keywords if kw in strong_blob)
        body_hits = sum(1 for kw in keywords if kw in body)
        if strong_hits == 0 and body_hits == 0:
            continue
        # sort key: strong pages first, then by hit counts; negate for descending
        scored.append((
            (0 if strong_hits > 0 else 1, -strong_hits, -body_hits, rel),
            {"path": rel, "summary": summary},
        ))
    scored.sort(key=lambda x: x[0])
    return [item for _, item in scored[:RELATED_CAP]]


def prep_mode(vault: pathlib.Path, source: pathlib.Path, keywords: list[str]) -> dict:
    categories = top_level_categories(vault)
    status, key = manifest_status(vault, source)
    out = {
        "vault": str(vault),
        "source": str(source),
        "categories": categories,
        "private_paths": load_private_paths(vault),
        "manifest_status": status,
        "manifest_key": key,
        "index_base_backed": category_base_backed(vault, categories),
    }
    if keywords:
        out["related_pages"] = related_pages(vault, keywords)
    return out


# ---------------------------------------------------------------------------
# Backlinks mode
# ---------------------------------------------------------------------------

def distinctive_terms(title: str, stem: str) -> list[str]:
    """Distinctive lowercase terms from a page's title + filename stem: tokens of
    >=4 chars that aren't stopwords. Order-preserving, de-duplicated."""
    tokens = re.split(r"[^0-9A-Za-z]+", f"{title} {stem}".lower())
    seen, terms = set(), []
    for t in tokens:
        if len(t) < 4 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        terms.append(t)
    return terms


def links_to(candidate_targets: list[str], target_rel: str) -> bool:
    """True if any wikilink in a candidate resolves to the target page."""
    stem = pathlib.PurePosixPath(target_rel).stem.lower()
    rel_noext = target_rel[:-3].lower() if target_rel.lower().endswith(".md") else target_rel.lower()
    wants = {stem, rel_noext, target_rel.lower()}
    for t in candidate_targets:
        if t in wants or t.rsplit("/", 1)[-1] == stem:
            return True
    return False


def backlinks_mode(vault: pathlib.Path, pages: list[str]) -> list[dict]:
    all_pages = content_pages(vault)
    # Pre-read each candidate's body + wikilink targets once.
    bodies = {p: read_text(p) for p in all_pages}
    links = {p: extract_wikilink_targets(bodies[p]) for p in all_pages}
    # A term that appears in a large fraction of the vault (e.g. "agent",
    # "windows") is not distinctive — it would flag every page. Cap the document
    # frequency so only genuinely topic-specific terms drive candidates.
    df_cap = max(3, int(0.15 * len(all_pages)))

    results = []
    for page_rel in pages:
        target = vault / page_rel
        fm = load_frontmatter(target) if target.is_file() else None
        title = str((fm or {}).get("title") or "")
        stem = pathlib.PurePosixPath(page_rel).stem
        kept = []  # (term, compiled_pattern), only corpus-distinctive terms
        for term in distinctive_terms(title, stem):
            pat = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
            df = sum(1 for b in bodies.values() if pat.search(b))
            if 0 < df <= df_cap:
                kept.append((term, pat))
        if not kept:
            continue
        target_resolved = target.resolve() if target.is_file() else None

        for cand in all_pages:
            if target_resolved is not None and cand.resolve() == target_resolved:
                continue
            if cand.relative_to(vault).as_posix() == page_rel:
                continue
            if links_to(links[cand], page_rel):
                continue
            body = bodies[cand]
            for term, pat in kept:
                if pat.search(body):
                    results.append({
                        "page": page_rel,
                        "candidate": cand.relative_to(vault).as_posix(),
                        "matched_term": term,
                    })
                    break
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Single-call prep tool for a wiki ingest (read-only, JSON out).",
    )
    ap.add_argument("--vault", default=None, help="Path to vault root. If omitted, auto-detected.")
    ap.add_argument("--source", default=None, help="Prep mode: the source file about to be ingested.")
    ap.add_argument("--keywords", default=None, help="Prep mode: comma-separated keywords for related_pages.")
    ap.add_argument("--backlinks-for", default=None, metavar="PAGES",
                    help="Backlinks mode: comma-separated vault-relative pages.")
    args = ap.parse_args()

    if bool(args.source) == bool(args.backlinks_for):
        ap.error("give exactly one of --source (prep mode) or --backlinks-for (backlinks mode)")

    vault = resolve_vault(args.vault)

    if args.source:
        source = pathlib.Path(args.source).expanduser()
        keywords = [k.strip().lower() for k in (args.keywords or "").split(",") if k.strip()]
        out = prep_mode(vault, source, keywords)
    else:
        pages = [p.strip() for p in args.backlinks_for.split(",") if p.strip()]
        out = backlinks_mode(vault, pages)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
