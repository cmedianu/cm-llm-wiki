#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Single-call prep tool for the start of a wiki ingest.

Replaces the 4-5 ad-hoc shell/grep round-trips a skill otherwise burns before
distilling a source: list categories, read private_paths, check whether the
source is already tracked, see how each folder index lists its pages
(index_status: base_backed = a live ```base view, nothing to edit; hybrid = a
base view plus hand bullets/rows, listed in index_hand_listed, that the base
already covers; manual = hand-curated, add the new page yourself), and surface
pages related to the source's keywords. Read-only — never writes to the vault. Emits JSON to stdout.

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

def _walk_md(vault: pathlib.Path) -> list[pathlib.Path]:
    """Every .md outside dot/underscore folders. Pruning the walk matters: _raw/,
    _sources/ and _archives/ can hold thousands of files on a slow (OneDrive) mount."""
    out = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        out.extend(pathlib.Path(root) / f for f in files if f.endswith(".md"))
    return sorted(out)


def content_pages(vault: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for f in _walk_md(vault):
        rel = pathlib.PurePosixPath(f.relative_to(vault).as_posix())
        if is_content_page(rel):
            out.append(f)
    return out


def load_frontmatter(path: pathlib.Path) -> Optional[dict]:
    """Parse a page's YAML frontmatter. Returns dict, or None on any failure."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
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
        return path.read_text(encoding="utf-8-sig", errors="replace")
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
        if p.is_dir() and not p.name.startswith((".", "_")) and p.name != "templates"
    )


_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+|^\s*\|")
_ANY_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def hand_listed_links(text: str) -> list[str]:
    """Wikilink targets on bullet, numbered or table lines, outside frontmatter and
    fenced blocks; alias, #heading, ^block and .md suffix stripped, case kept."""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    out, fence = [], None
    for line in lines[start:]:
        fm = _ANY_FENCE_RE.match(line)
        if fence is not None:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        if not _LIST_ITEM_RE.match(line):
            continue
        for m in _WIKILINK_RE.finditer(line):
            raw = m.group(1).replace("\\|", "|").split("|")[0]
            raw = re.split(r"[#^]", raw)[0].strip().lstrip("/")
            if raw.lower().endswith(".md"):
                raw = raw[:-3]
            if raw:
                out.append(raw)
    return out


def index_folders(vault: pathlib.Path, categories: list[str]) -> list[str]:
    """Top-level categories plus every content folder that has an index.md."""
    folders = set(categories)
    for idx in (f for f in _walk_md(vault) if f.name == "index.md"):
        rel = idx.parent.relative_to(vault).as_posix()
        if rel == ".":
            continue
        parts = rel.split("/")
        if any(p.startswith((".", "_")) for p in parts) or parts[0] == "templates":
            continue
        folders.add(rel)
    return sorted(folders)


def index_status(vault: pathlib.Path, folders: list[str],
                 pages: list[pathlib.Path]) -> tuple[dict, dict]:
    """(status, hand_listed). status[folder] is:
      base_backed  index.md embeds a ```base view and lists no folder pages by hand;
      hybrid       it embeds a ```base view AND a bullet/table list links pages in
                   the folder (or below it), which the base already lists;
      manual       no ```base view (or no index.md): new pages need a hand edit.
    hand_listed[folder] (hybrid only) is the vault-relative pages those hand
    bullets/rows point at — the redundant entries a base filter already covers."""
    by_path: dict[str, str] = {}
    by_base: dict[str, list[str]] = {}
    for f in pages:
        rel = f.relative_to(vault).as_posix()
        by_path[rel[:-3].lower()] = rel
        by_base.setdefault(f.stem.lower(), []).append(rel)
    status, hand = {}, {}
    for folder in folders:
        idx = vault / folder / "index.md"
        text = read_text(idx) if idx.is_file() else ""
        if not _BASE_FENCE_RE.search(text):
            status[folder] = "manual"
            continue
        prefix = folder + "/"
        covered = []
        for target in hand_listed_links(text):
            t = target.lower()
            rel = by_path.get(t)
            if rel is None and "/" not in t and len(by_base.get(t, [])) == 1:
                rel = by_base[t][0]
            if rel and rel.startswith(prefix) and rel not in covered:
                covered.append(rel)
        if covered:
            status[folder] = "hybrid"
            hand[folder] = covered
        else:
            status[folder] = "base_backed"
    return status, hand


# ---------------------------------------------------------------------------
# Prep mode
# ---------------------------------------------------------------------------

def _source_refs(fm: Optional[dict]) -> list[str]:
    raw = (fm or {}).get("sources") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip().strip("[]") for x in raw if x]


def source_status(vault: pathlib.Path, source: pathlib.Path) -> tuple[str, Optional[str]]:
    """(status, key): has this source been ingested already? status is new | modified |
    unchanged; key is the snapshot or the page that settles it.

    Decided from the vault itself, not the manifest (which no longer tracks pages):
      1. an external source with a `_sources/<basename>` snapshot: byte-compare;
      2. a page whose `sources:` frontmatter names the source (vault path or basename):
         unchanged, unless the source file is newer than that page's `updated:`;
      3. a page whose filename matches the source's stem: modified (merge, don't duplicate);
      4. otherwise new."""
    src = source.expanduser()
    base = src.name
    try:
        rel = src.resolve().relative_to(vault.resolve()).as_posix()
    except (ValueError, OSError):
        rel = None

    if rel is None:
        snap = vault / "_sources" / base
        if snap.is_file():
            try:
                same = snap.read_bytes() == src.read_bytes()
                return ("unchanged" if same else "modified", f"_sources/{base}")
            except OSError:
                pass

    wanted = {base.lower(), f"_sources/{base}".lower()} | ({rel.lower()} if rel else set())
    try:
        src_day = datetime.date.fromtimestamp(src.stat().st_mtime).isoformat()
    except OSError:
        src_day = None
    stem = src.stem.lower()
    same_name = None
    for page in content_pages(vault):
        fm = load_frontmatter(page)
        refs = {r.lower() for r in _source_refs(fm)} | {r.lower().rsplit("/", 1)[-1] for r in _source_refs(fm)}
        page_rel = page.relative_to(vault).as_posix()
        if refs & wanted:
            updated = str((fm or {}).get("updated", ""))[:10]
            if src_day and updated and src_day > updated:
                return ("modified", page_rel)
            return ("unchanged", page_rel)
        if same_name is None and page.stem.lower() == stem:
            same_name = page_rel
    if same_name:
        return ("modified", same_name)
    return ("new", None)


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
    status, key = source_status(vault, source)
    snap = vault / "_sources" / source.name
    out = {
        "vault": str(vault),
        "source": str(source),
        "categories": categories,
        "private_paths": load_private_paths(vault),
        "source_status": status,
        "source_key": key,
        # Back-compat aliases for skills written before the manifest stopped tracking pages.
        "manifest_status": status,
        "manifest_key": key,
        "snapshot": f"_sources/{source.name}" if snap.is_file() else None,
    }
    status, hand = index_status(vault, index_folders(vault, categories), content_pages(vault))
    # Back-compat: the old per-category boolean (true = a base view exists).
    out["index_base_backed"] = {c: status[c] != "manual" for c in categories}
    out["index_status"] = status
    out["index_hand_listed"] = hand
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

# --- sources mode: what is new in a source archive ------------------------------

TEXT_EXT = {".md", ".txt", ".eml", ".html", ".htm", ".csv"}
SOURCE_EXT = TEXT_EXT | {".pdf"}
EXCERPT_CHARS = 600


def last_log_date(vault: pathlib.Path) -> Optional[str]:
    """Date of the newest `- [yyyy-MM-dd...]` entry in log.md, or None."""
    import re as _re
    try:
        text = (vault / "log.md").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    dates = _re.findall(r"^- \[(\d{4}-\d{2}-\d{2})", text, _re.M)
    return max(dates) if dates else None


def pdf_text(path: pathlib.Path, rel_parts: tuple, ocr_cache: Optional[pathlib.Path]) -> tuple[str, str]:
    """(text, how): the vault's OCR cache first, then pdftotext cached under ~/.cache."""
    import hashlib
    import shutil
    import subprocess
    if ocr_cache is not None:
        for cand in ([ocr_cache / rel_parts[0] / f"{path.stem}.txt"] if len(rel_parts) > 1 else []) \
                + [ocr_cache / f"{path.stem}.txt"]:
            if cand.is_file():
                return cand.read_text(encoding="utf-8", errors="replace"), "ocr-cache"
    st = path.stat()
    key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
    cache = pathlib.Path.home() / ".cache" / "cm-llm-wiki" / "pdftext" / f"{key}.txt"
    if cache.is_file():
        return cache.read_text(encoding="utf-8", errors="replace"), "pdftotext"
    if not shutil.which("pdftotext"):
        return "", "no-pdftotext"
    r = subprocess.run(["pdftotext", "-l", "3", "-layout", str(path), "-"],
                       capture_output=True, text=True, errors="replace")
    text = r.stdout if r.returncode == 0 else ""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text, "pdftotext"


def sources_mode(vault: pathlib.Path, sources_dir: pathlib.Path, since: Optional[str],
                 ocr_cache: Optional[pathlib.Path], limit: int, fresh_folders_only: bool = False) -> dict:
    """Files in a source archive (a mail export, a drop folder) changed on or after
    `since`, newest first, each with a short text excerpt, so one call answers
    "what's new since I last looked" without ls / grep / pdftotext round-trips."""
    import datetime as _dt
    import os as _os
    from concurrent.futures import ThreadPoolExecutor
    since = since or last_log_date(vault)
    paths = []
    cutoff = None
    if since and fresh_folders_only:
        cutoff = _dt.datetime.fromisoformat(since).timestamp()
    for dirpath, dirnames, filenames in _os.walk(sources_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"
                       and (ocr_cache is None or pathlib.Path(dirpath, d) != ocr_cache)]
        if cutoff is not None and pathlib.Path(dirpath) == sources_dir:
            # Opt-in shortcut: adding a file to a folder bumps the folder's mtime, so an
            # older top-level folder holds no NEW files. It does miss files rewritten in
            # place (a mail thread.md gaining a reply), hence not the default.
            def fresh(d):
                try:
                    return (sources_dir / d).stat().st_mtime >= cutoff
                except OSError:
                    return True
            dirnames[:] = [d for d in dirnames if fresh(d)]
        paths += [pathlib.Path(dirpath) / n for n in filenames
                  if pathlib.Path(n).suffix.lower() in SOURCE_EXT]

    def stat(path):
        try:
            return path, path.stat()
        except OSError:
            return path, None

    found = []
    with ThreadPoolExecutor(max_workers=32) as pool:  # a stat costs ms on /mnt/c
        for path, st in pool.map(stat, paths):
            if st is None:
                continue
            day = _dt.date.fromtimestamp(st.st_mtime).isoformat()
            if since and day < since:
                continue
            found.append((st.st_mtime, day, st.st_size, path))
    found.sort(key=lambda t: -t[0])
    items = []
    for _mt, day, size, path in found[:limit]:
        rel = path.relative_to(sources_dir)
        if path.suffix.lower() == ".pdf":
            text, how = pdf_text(path, rel.parts, ocr_cache)
        else:
            text, how = read_text(path), "text"
            if text.startswith("---"):
                end = text.find("\n---", 3)
                text = text[end + 4:] if end != -1 else text
        excerpt = " ".join(text.split())[:EXCERPT_CHARS]
        item = {"path": rel.as_posix(), "modified": day, "size": size, "text_from": how,
                "excerpt": excerpt}
        if path.suffix.lower() == ".pdf" and not excerpt:
            item["needs_ocr"] = True
        items.append(item)
    return {"sources_dir": str(sources_dir), "since": since, "total_new": len(found),
            "shown": len(items), "files": items}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Single-call prep tool for a wiki ingest (read-only, JSON out).",
    )
    ap.add_argument("--vault", default=None, help="Path to vault root. If omitted, auto-detected.")
    ap.add_argument("--source", default=None, help="Prep mode: the source file about to be ingested.")
    ap.add_argument("--keywords", default=None, help="Prep mode: comma-separated keywords for related_pages.")
    ap.add_argument("--backlinks-for", default=None, metavar="PAGES",
                    help="Backlinks mode: comma-separated vault-relative pages.")
    ap.add_argument("--sources-dir", default=None, metavar="DIR",
                    help="Sources mode: list files in this archive changed since --since, "
                         "newest first, with a text excerpt each (PDFs via the OCR cache or pdftotext).")
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                    help="Sources mode: cut-off date (default: the newest log.md entry).")
    ap.add_argument("--ocr-cache", default=None, metavar="DIR",
                    help="Sources mode: dir of OCR'd text, <dir>/<top-folder>/<pdf-stem>.txt or <dir>/<stem>.txt.")
    ap.add_argument("--limit", type=int, default=50, help="Sources mode: max files shown (default 50).")
    ap.add_argument("--fresh-folders-only", action="store_true",
                    help="Sources mode: only descend into top-level folders modified since the cut-off "
                         "(much faster on a big archive; misses files rewritten in place).")
    args = ap.parse_args()

    if sum(map(bool, (args.source, args.backlinks_for, args.sources_dir))) != 1:
        ap.error("give exactly one of --source (prep), --backlinks-for (backlinks) or --sources-dir (sources)")

    vault = resolve_vault(args.vault)

    if args.sources_dir:
        sd = pathlib.Path(args.sources_dir).expanduser()
        if not sd.is_absolute():
            sd = vault / sd
        if not sd.is_dir():
            ap.error(f"--sources-dir: not a directory: {sd}")
        oc = pathlib.Path(args.ocr_cache).expanduser() if args.ocr_cache else None
        if oc is not None and not oc.is_absolute():
            oc = vault / oc
        out = sources_mode(vault, sd, args.since, oc, args.limit, args.fresh_folders_only)
    elif args.source:
        source = pathlib.Path(args.source).expanduser()
        keywords = [k.strip().lower() for k in (args.keywords or "").split(",") if k.strip()]
        out = prep_mode(vault, source, keywords)
    else:
        pages = [p.strip() for p in args.backlinks_for.split(",") if p.strip()]
        out = backlinks_mode(vault, pages)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


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
