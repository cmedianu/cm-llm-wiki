#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Compute the wikilink-graph structure of an Obsidian vault.

Replaces ad-hoc LLM-driven graph analytics with a deterministic, correct
graph analysis — especially the articulation-point (bridge) detection, which
an LLM cannot do reliably by reading files by hand.

Usage:
  uv run .claude/wiki-scripts/wiki-graph.py [VAULT] [--format json|md]

  VAULT     Optional path to the vault root.  Defaults to the vault found by
            walking up from CWD looking for .manifest.json, then
            OBSIDIAN_VAULT_PATH as a fallback.
  --format  json (default) or md (human-readable summary).

Snapshot:
  A graph snapshot is written to
    ~/.obsidian-wiki/state/<id>/graph-snapshot.json
  where <id> is the first 8 hex chars of the md5 of the absolute vault path.
  The snapshot is used on the next run to produce a graph delta (new/removed
  nodes and edges, nodes that gained or lost all incoming links).  Copying the
  vault to a new path gives a fresh snapshot — correct, because the topology
  may have changed independently.

Content pages:
  Any *.md passing the shared is_content_page() rule: no path part starts with
  '.' or '_', not under templates/, not a root yyyy-MM-dd.md daily note, and
  basename not in {index.md, log.md, hot.md, README.md, CLAUDE.md, AGENTS.md}.

Graph nodes:
  Keyed by vault-relative path WITHOUT the .md extension
  (e.g. 'concepts/transformers').

Edges:
  Directed wikilinks [[target]] / [[target|display]] parsed from each page body
  (not frontmatter, not inside fenced code blocks).  #heading / ^block suffixes
  are stripped.  Targets are resolved by (a) exact node-key match or (b) unique
  basename match.  Unresolved → ignored.

Exit 0 on success.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from collections import defaultdict
from typing import Any, Optional

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


def walk_md(vault):
    """Every *.md under the vault, sorted, pruning dot- and _-dirs while walking (a
    `_` mail archive can hold thousands of files; rglob would visit them all)."""
    import os as _os
    out = []
    for dirpath, dirnames, filenames in _os.walk(vault):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        out.extend(pathlib.Path(dirpath) / f for f in filenames if f.endswith(".md"))
    return sorted(out)

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
# Snapshot path
# ---------------------------------------------------------------------------

def snapshot_path(vault: pathlib.Path) -> pathlib.Path:
    """Return the snapshot file path scoped to this vault (never inside the vault)."""
    vault_id = hashlib.md5(str(vault.resolve()).encode()).hexdigest()[:8]
    state_dir = pathlib.Path.home() / ".obsidian-wiki" / "state" / vault_id
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "graph-snapshot.json"


# ---------------------------------------------------------------------------
# Content-page discovery
# ---------------------------------------------------------------------------

def discover_pages(vault: pathlib.Path) -> dict[str, pathlib.Path]:
    """Return {node_key: absolute_path} for every content page.

    node_key = vault-relative path without .md extension, with forward slashes.
    """
    pages: dict[str, pathlib.Path] = {}
    for f in walk_md(vault):
        rel = f.relative_to(vault)
        if not is_content_page(rel.as_posix()):
            continue
        key = rel.with_suffix("").as_posix()
        pages[key] = f
    return pages


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict:
    """Return the parsed YAML frontmatter dict, or {} on failure/absence."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass
    return {}


def body_without_frontmatter(text: str) -> str:
    """Strip the leading --- … --- frontmatter block, return the rest."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[i + 1:])
    return text  # unclosed frontmatter — return everything


# ---------------------------------------------------------------------------
# Wikilink extraction
# ---------------------------------------------------------------------------

_FENCED_RE = re.compile(r"```.*?```", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#^]+?)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")


def extract_wikilinks(body: str) -> list[str]:
    """Return raw wikilink targets from body (fenced code blocks stripped)."""
    cleaned = _FENCED_RE.sub("", body)
    return _WIKILINK_RE.findall(cleaned)


# ---------------------------------------------------------------------------
# Link resolution
# ---------------------------------------------------------------------------

def build_basename_index(pages: dict[str, pathlib.Path]) -> dict[str, list[str]]:
    """Map lowercase basename (no extension) → [node_keys] for ambiguity detection."""
    idx: dict[str, list[str]] = defaultdict(list)
    for key in pages:
        basename = key.split("/")[-1].lower()
        idx[basename].append(key)
    return dict(idx)


def resolve_target(raw: str, pages: dict[str, pathlib.Path],
                   basename_idx: dict[str, list[str]]) -> str | None:
    """Resolve a raw wikilink target to a node key, or None if unresolvable."""
    # Normalise: strip whitespace, convert backslash to forward slash
    raw = raw.strip().replace("\\", "/")

    # (a) Exact match (case-sensitive then case-insensitive)
    if raw in pages:
        return raw
    raw_lower = raw.lower()
    # Try with and without .md extension stripped already handled by node key
    # Try exact lowercase match
    for key in pages:
        if key.lower() == raw_lower:
            return key

    # (b) Unique basename match
    target_basename = raw_lower.split("/")[-1]
    candidates = basename_idx.get(target_basename, [])
    if len(candidates) == 1:
        return candidates[0]

    return None


# ---------------------------------------------------------------------------
# Articulation-point detection — iterative Tarjan DFS
# ---------------------------------------------------------------------------

def find_articulation_points(adj: dict[str, set[str]]) -> dict[str, int]:
    """Return {node: child_subtree_count} for every articulation point.

    Uses an iterative DFS with the standard lowlink/disc algorithm.
    child_subtree_count = number of independent DFS subtrees that hang below
    this node in the DFS tree (≥2 means removing it disconnects the graph).

    For root nodes in the DFS tree: it's an AP iff it has ≥2 DFS children.
    For non-root nodes: it's an AP iff any DFS child u satisfies low[u] ≥ disc[v].
    """
    nodes = list(adj.keys())
    if not nodes:
        return {}

    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    ap: dict[str, int] = {}  # node → child subtree count
    timer = [0]

    for start in nodes:
        if start in disc:
            continue
        # Iterative DFS using an explicit stack.
        # Each stack frame: (node, iterator-over-neighbours, is_first_visit)
        stack: list[tuple[str, Any, bool]] = [(start, iter(adj.get(start, set())), True)]
        parent[start] = None
        while stack:
            v, neighbours, first = stack[-1]
            if first:
                disc[v] = low[v] = timer[0]
                timer[0] += 1
                stack[-1] = (v, neighbours, False)
            # Advance to the next unvisited neighbour
            found_child = False
            for u in neighbours:
                if u not in disc:
                    parent[u] = v
                    stack.append((u, iter(adj.get(u, set())), True))
                    found_child = True
                    break
                elif u != parent[v]:
                    low[v] = min(low[v], disc[u])
            if not found_child:
                # All neighbours exhausted — backtrack
                stack.pop()
                if stack:
                    p = parent[v]
                    low[p] = min(low[p], low[v])
                    if parent[p] is None:
                        # p is DFS root: count DFS children
                        ap[p] = ap.get(p, 0) + 1
                    else:
                        if low[v] >= disc[p]:
                            ap[p] = ap.get(p, 0) + 1

    # Root nodes are APs only if they have ≥2 DFS children
    result = {}
    for node, children in ap.items():
        if parent[node] is None:
            if children >= 2:
                result[node] = children
        else:
            result[node] = children
    return result


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(vault: pathlib.Path) -> dict:
    """Walk the vault and build the full graph data structure."""
    pages = discover_pages(vault)
    if not pages:
        return {"pages": {}, "edges": [], "frontmatter": {}}

    basename_idx = build_basename_index(pages)

    # Parse each page
    frontmatter: dict[str, dict] = {}
    raw_links: dict[str, list[str]] = {}  # node_key → [raw targets]

    for key, path in pages.items():
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            text = ""
        fm = parse_frontmatter(text)
        frontmatter[key] = fm
        body = body_without_frontmatter(text)
        raw_links[key] = extract_wikilinks(body)

    # Resolve links → directed edges (deduplicated per source)
    edges: list[tuple[str, str]] = []  # (src, dst)
    for src, targets in raw_links.items():
        seen: set[str] = set()
        for raw in targets:
            dst = resolve_target(raw, pages, basename_idx)
            if dst and dst != src and dst not in seen:
                seen.add(dst)
                edges.append((src, dst))

    return {"pages": pages, "edges": edges, "frontmatter": frontmatter}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def compute_hubs(nodes: list[str], edges: list[tuple[str, str]]) -> list[dict]:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for src, dst in edges:
        outgoing[src] += 1
        incoming[dst] += 1
    for n in nodes:
        incoming.setdefault(n, 0)
        outgoing.setdefault(n, 0)

    ranked = sorted(nodes, key=lambda n: incoming[n], reverse=True)
    top = ranked[:10]
    result = []
    for n in top:
        inc = incoming[n]
        out = outgoing[n]
        kind = "connector" if inc > 0 and out > 0 else "sink"
        result.append({"page": n, "incoming": inc, "outgoing": out, "kind": kind})
    return result


def compute_tag_cohesion(nodes: list[str], edges: list[tuple[str, str]],
                         frontmatter: dict[str, dict]) -> list[dict]:
    # Collect tags per page
    page_tags: dict[str, set[str]] = {}
    for node in nodes:
        fm = frontmatter.get(node, {})
        tags_raw = fm.get("tags", [])
        if isinstance(tags_raw, str):
            tags_raw = [tags_raw]
        if not isinstance(tags_raw, list):
            tags_raw = []
        page_tags[node] = {str(t).strip().lower() for t in tags_raw if t}

    # Index: tag → set of nodes
    tag_nodes: dict[str, set[str]] = defaultdict(set)
    for node, tags in page_tags.items():
        for tag in tags:
            tag_nodes[tag].add(node)

    # Build undirected adjacency set for quick pair lookup
    undirected_pairs: set[frozenset] = set()
    for src, dst in edges:
        undirected_pairs.add(frozenset({src, dst}))

    result = []
    for tag, members in tag_nodes.items():
        n = len(members)
        if n < 5:
            continue
        member_list = list(members)
        possible = n * (n - 1) // 2
        actual = 0
        for i in range(len(member_list)):
            for j in range(i + 1, len(member_list)):
                if frozenset({member_list[i], member_list[j]}) in undirected_pairs:
                    actual += 1
        cohesion = actual / possible if possible > 0 else 0.0
        result.append({
            "tag": tag,
            "n": n,
            "cohesion": round(cohesion, 4),
            "fragmented": cohesion < 0.15,
        })
    result.sort(key=lambda x: x["cohesion"], reverse=True)
    return result


def compute_orphans(nodes: list[str], edges: list[tuple[str, str]],
                    hubs: list[dict]) -> tuple[list[str], list[str]]:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for src, dst in edges:
        incoming[dst] += 1
        outgoing[src] += 1
    for n in nodes:
        incoming.setdefault(n, 0)
        outgoing.setdefault(n, 0)

    top10_pages = {h["page"] for h in hubs}
    # Which nodes are linked FROM a top-10 hub?
    hub_targets: set[str] = set()
    for src, dst in edges:
        if src in top10_pages:
            hub_targets.add(dst)

    orphans = [n for n in nodes if incoming[n] == 0]
    # Orphan-adjacent: 0 outgoing AND linked from a top hub
    orphan_adjacent = [n for n in nodes
                       if outgoing[n] == 0 and n in hub_targets and n not in top10_pages]
    return sorted(orphans), sorted(orphan_adjacent)


def build_undirected_adj(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for src, dst in edges:
        if src != dst:
            adj[src].add(dst)
            adj[dst].add(src)
    return adj


def compute_bridges(nodes: list[str], edges: list[tuple[str, str]]) -> list[dict]:
    adj = build_undirected_adj(nodes, edges)
    ap_map = find_articulation_points(adj)
    result = []
    for node, count in sorted(ap_map.items(), key=lambda x: x[1], reverse=True):
        result.append({"page": node, "separates": count})
    return result


def compute_cross_category(edges: list[tuple[str, str]], limit: int = 100) -> tuple[list[dict], bool]:
    def category(node: str) -> str:
        parts = node.split("/")
        return parts[0] if len(parts) > 1 else ""

    cross = []
    for src, dst in edges:
        if category(src) != category(dst):
            cross.append({"from": src, "to": dst})
    truncated = len(cross) > limit
    return cross[:limit], truncated


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def compute_delta(current_nodes: set[str], current_edges: set[tuple[str, str]],
                  snapshot: dict | None) -> dict:
    if snapshot is None:
        return {"no_previous_snapshot": True}

    prev_nodes = set(snapshot.get("nodes", []))
    prev_edges_raw = snapshot.get("edges", [])
    prev_edges: set[tuple[str, str]] = {(e[0], e[1]) for e in prev_edges_raw}

    prev_incoming: dict[str, int] = defaultdict(int)
    for src, dst in prev_edges:
        prev_incoming[dst] += 1
    curr_incoming: dict[str, int] = defaultdict(int)
    for src, dst in current_edges:
        curr_incoming[dst] += 1

    new_pages = sorted(current_nodes - prev_nodes)
    removed_pages = sorted(prev_nodes - current_nodes)
    new_edges = len(current_edges - prev_edges)
    removed_edges_count = len(prev_edges - current_edges)

    # Nodes that went from 0 incoming to >0
    newly_connected = sorted(
        n for n in current_nodes
        if curr_incoming.get(n, 0) > 0 and prev_incoming.get(n, 0) == 0
    )
    # Nodes that went from >0 incoming to 0 (and still exist)
    lost_incoming = sorted(
        n for n in current_nodes
        if curr_incoming.get(n, 0) == 0 and prev_incoming.get(n, 0) > 0
    )

    return {
        "new_pages": new_pages,
        "removed_pages": removed_pages,
        "new_edges": new_edges,
        "removed_edges": removed_edges_count,
        "newly_connected": newly_connected,
        "lost_incoming": lost_incoming,
    }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_json(vault: pathlib.Path, graph_data: dict, analytics: dict) -> str:
    pages = graph_data["pages"]
    edges = graph_data["edges"]
    cross, truncated = analytics["cross_category"]
    payload = {
        "vault": str(vault),
        "pages": len(pages),
        "edges": len(edges),
        "hubs": analytics["hubs"],
        "tag_cohesion": analytics["tag_cohesion"],
        "orphans": analytics["orphans"],
        "orphan_adjacent": analytics["orphan_adjacent"],
        "bridges": analytics["bridges"],
        "cross_category_edges": cross,
        "cross_category_truncated": truncated,
        "delta": analytics["delta"],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def format_md(vault: pathlib.Path, graph_data: dict, analytics: dict) -> str:
    pages = graph_data["pages"]
    edges = graph_data["edges"]
    lines: list[str] = []

    lines.append("# Wiki Graph")
    lines.append("")
    lines.append(f"Vault: `{vault}`  ")
    lines.append(f"Pages: {len(pages)}  |  Edges: {len(edges)}")
    lines.append("")

    # --- Hubs ---
    lines.append("## Hubs (top 10 by incoming links)")
    lines.append("")
    lines.append("| Page | Incoming | Outgoing | Kind |")
    lines.append("|---|---|---|---|")
    for h in analytics["hubs"]:
        lines.append(f"| `{h['page']}` | {h['incoming']} | {h['outgoing']} | {h['kind']} |")
    lines.append("")

    # --- Tag cohesion ---
    lines.append("## Tag Cohesion (tags on ≥5 pages)")
    lines.append("")
    tc = analytics["tag_cohesion"]
    if not tc:
        lines.append("_No tags appear on ≥5 content pages._")
    else:
        lines.append("| Tag | Pages | Cohesion | Status |")
        lines.append("|---|---|---|---|")
        for t in tc:
            status = "fragmented" if t["fragmented"] else "OK"
            lines.append(f"| `{t['tag']}` | {t['n']} | {t['cohesion']:.3f} | {status} |")
    lines.append("")

    # --- Orphans ---
    lines.append("## Orphans (0 incoming links)")
    lines.append("")
    orphans = analytics["orphans"]
    if orphans:
        for o in orphans:
            lines.append(f"- `{o}`")
    else:
        lines.append("_None._")
    lines.append("")

    # --- Orphan-adjacent ---
    lines.append("## Orphan-Adjacent (0 outgoing, linked from a top hub)")
    lines.append("")
    oa = analytics["orphan_adjacent"]
    if oa:
        for o in oa:
            lines.append(f"- `{o}`")
    else:
        lines.append("_None._")
    lines.append("")

    # --- Bridges ---
    lines.append("## Bridges (articulation points)")
    lines.append("")
    bridges = analytics["bridges"]
    if bridges:
        lines.append("Removing any of these would disconnect the graph.")
        lines.append("")
        lines.append("| Page | DFS child subtrees |")
        lines.append("|---|---|")
        for b in bridges:
            lines.append(f"| `{b['page']}` | {b['separates']} |")
    else:
        lines.append("_No articulation points (graph is biconnected or has <2 connected pages)._")
    lines.append("")

    # --- Cross-category edges ---
    cross, truncated = analytics["cross_category"]
    lines.append("## Cross-Category Connections")
    lines.append("")
    if cross:
        if truncated:
            lines.append("_(first 100 shown)_")
            lines.append("")
        lines.append("| From | To |")
        lines.append("|---|---|")
        for e in cross:
            lines.append(f"| `{e['from']}` | `{e['to']}` |")
    else:
        lines.append("_None._")
    lines.append("")

    # --- Delta ---
    lines.append("## Graph Delta (vs previous snapshot)")
    lines.append("")
    delta = analytics["delta"]
    if delta.get("no_previous_snapshot"):
        lines.append("_No previous snapshot — this is the first run._")
    else:
        lines.append(f"- New pages: {len(delta['new_pages'])}")
        for p in delta["new_pages"]:
            lines.append(f"  - `{p}`")
        lines.append(f"- Removed pages: {len(delta['removed_pages'])}")
        for p in delta["removed_pages"]:
            lines.append(f"  - `{p}`")
        lines.append(f"- New edges: {delta['new_edges']}")
        lines.append(f"- Removed edges: {delta['removed_edges']}")
        lines.append(f"- Newly connected (0→>0 incoming): {len(delta['newly_connected'])}")
        for p in delta["newly_connected"]:
            lines.append(f"  - `{p}`")
        lines.append(f"- Lost all incoming (>0→0): {len(delta['lost_incoming'])}")
        for p in delta["lost_incoming"]:
            lines.append(f"  - `{p}`")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the wikilink-graph structure of an Obsidian vault.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        help="Output format: json (default) or md (human-readable summary)",
    )
    args = parser.parse_args()

    vault = resolve_vault(args.vault_flag or args.vault)

    # Load previous snapshot
    snap_path = snapshot_path(vault)
    prev_snapshot: dict | None = None
    if snap_path.exists():
        try:
            prev_snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev_snapshot = None

    # Build graph
    graph_data = build_graph(vault)
    pages = graph_data["pages"]
    edges = graph_data["edges"]
    frontmatter = graph_data["frontmatter"]
    nodes = list(pages.keys())
    edge_set: set[tuple[str, str]] = set(edges)

    # Analytics
    hubs = compute_hubs(nodes, edges)
    tag_cohesion = compute_tag_cohesion(nodes, edges, frontmatter)
    orphans, orphan_adjacent = compute_orphans(nodes, edges, hubs)
    bridges = compute_bridges(nodes, edges)
    cross_category = compute_cross_category(edges)
    delta = compute_delta(set(nodes), edge_set, prev_snapshot)

    analytics = {
        "hubs": hubs,
        "tag_cohesion": tag_cohesion,
        "orphans": orphans,
        "orphan_adjacent": orphan_adjacent,
        "bridges": bridges,
        "cross_category": cross_category,
        "delta": delta,
    }

    # Write snapshot (overwrite)
    snapshot = {
        "vault": str(vault),
        "nodes": nodes,
        "edges": [[s, d] for s, d in edges],
    }
    snap_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Output
    if args.format == "json":
        print(format_json(vault, graph_data, analytics))
    else:
        print(format_md(vault, graph_data, analytics))

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
