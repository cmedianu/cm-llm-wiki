#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Rename or move one wiki page and rewrite every wikilink to it.

  wiki-mv.py OLD NEW [--apply] [--mkdir] [--vault PATH]

OLD and NEW are vault-relative page paths, with or without .md. Dry-run by
default: prints every file and line it would change. --apply performs it:

  - rewrites every wikilink to OLD in content pages and index.md files (keeps the
    alias, #heading, ^block, ![[embed]] form, a table-escaped \\| and a .md suffix;
    leaves fenced code and inline code alone; preserves CRLF and a UTF-8 BOM). A
    full-path link gets the full new path; a bare-basename link keeps the bare
    form when the new basename is unique in the vault;
  - rewrites frontmatter values that name OLD as a bare path (superseded_by: ...);
  - moves the file (case-only renames go through a temporary name);
  - sets `category:` in the moved page to the new folder when the folder changes;
  - re-keys OLD.md in .manifest.json, keeping ingested_at (a missing or corrupt
    manifest is reported and skipped).

Refuses (exit 2) when NEW exists, NEW's file name is not kebab-case-lowercase,
NEW is not a content page, or NEW's folder does not exist (unless --mkdir).
Links to OLD in other files (log.md, hot.md, templates/) are listed, not
rewritten; _raw/, _sources/ and _archives/ are not scanned. Exit 0 on success.
"""
import argparse
import json
import os
import pathlib
import re
import sys
from typing import Optional

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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


# Link parsing copied from kebab-rename.py (scripts never import each other):
# target, then an optional rest starting at `|`, `\|` (inside a table), `#` or `^`.
WIKILINK_RE = re.compile(r"\[\[([^\[\]|#^]+?)((?:\\?\||[#^])[^\[\]]*)?\]\]")
_FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")


def norm_page(arg: str) -> str:
    rel = arg.strip().replace("\\", "/").strip("/")
    if rel.lower().endswith(".md"):
        rel = rel[:-3]
    return rel


class Linker:
    """Decides whether a link target names OLD and what it should become."""

    def __init__(self, all_md: list[str], old: str, new: str):
        self.old, self.new = old, new
        self.old_l = old.lower()
        self.old_base = old.rsplit("/", 1)[-1].lower()
        others = [p[:-3] for p in all_md if p[:-3].lower() != self.old_l]
        self.base_count = sum(1 for p in others if p.rsplit("/", 1)[-1].lower() == self.old_base)
        new_base = new.rsplit("/", 1)[-1].lower()
        self.new_base_unique = not any(p.rsplit("/", 1)[-1].lower() == new_base for p in others)
        self.others_l = [p.lower() for p in others]
        self.ambiguous: list[str] = []

    def target_for(self, target: str) -> Optional[str]:
        t = target.strip().lower()
        if t.startswith("/"):
            t = t[1:]
        if t == self.old_l:
            return self.new
        if "/" not in t:
            if t != self.old_base:
                return None
            if self.base_count:
                self.ambiguous.append(target)
                return None
            return self.new.rsplit("/", 1)[-1] if self.new_base_unique else self.new
        # partial path: Obsidian resolves a path suffix when it is unambiguous
        if self.old_l.endswith("/" + t):
            if any(o == t or o.endswith("/" + t) for o in self.others_l):
                self.ambiguous.append(target)
                return None
            return self.new
        return None


def rewrite_line(line: str, linker: Linker) -> str:
    def repl(m):
        target, rest = m.group(1), m.group(2) or ""
        md = ""
        if target.strip().lower().endswith(".md"):
            md, target = target.strip()[-3:], target.strip()[:-3]
        new = linker.target_for(target)
        if new is None:
            return m.group(0)
        return f"[[{new}{md}{rest}]]"

    out, pos = [], 0
    for cm in _INLINE_CODE_RE.finditer(line):
        out.append(WIKILINK_RE.sub(repl, line[pos:cm.start()]))
        out.append(cm.group(0))
        pos = cm.end()
    out.append(WIKILINK_RE.sub(repl, line[pos:]))
    return "".join(out)


def rewrite_text(text: str, linker: Linker) -> tuple[str, list[tuple[int, str, str]]]:
    """Return (new_text, [(lineno, old_line, new_line)]). Skips fenced code."""
    lines = text.split("\n")
    changes = []
    in_fm = bool(lines) and lines[0].rstrip("\r").strip() == "---"
    fm_val = re.compile(
        r"^(\s*(?:-\s+|[\w-]+:\s+))([\"']?)(" + re.escape(linker.old) + r")(\.md)?\2(\s*\r?)$",
        re.IGNORECASE)
    fence = None
    for i, line in enumerate(lines):
        new = line
        if in_fm and i > 0:
            if line.rstrip("\r").strip() == "---":
                in_fm = False
            else:
                m = fm_val.match(line)
                if m:
                    new = f"{m.group(1)}{m.group(2)}{linker.new}{m.group(4) or ''}{m.group(2)}{m.group(5)}"
                else:
                    new = rewrite_line(line, linker)
        elif in_fm:
            pass  # opening ---
        else:
            fm = _FENCE_OPEN_RE.match(line)
            if fence is None:
                if fm:
                    fence = fm.group(1)
                else:
                    new = rewrite_line(line, linker)
            elif fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
        if new != line:
            lines[i] = new
            changes.append((i + 1, line.rstrip("\r"), new.rstrip("\r")))
    return "\n".join(lines), changes


def set_category(text: str, folder: str) -> tuple[str, Optional[tuple[str, str]]]:
    """Set the top-level `category:` frontmatter key. Returns (text, (old, new)|None)."""
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r").strip() != "---":
        return text, None
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r").strip() == "---"), None)
    if end is None:
        return text, None
    eol = "\r" if lines[0].endswith("\r") else ""
    for i in range(1, end):
        m = re.match(r"category:(.*)$", lines[i].rstrip("\r"))
        if m:
            old = m.group(1).strip()
            if old.strip("\"'") == folder:
                return text, None
            lines[i] = f"category: {folder}{eol}"
            return "\n".join(lines), (old, folder)
    lines.insert(end, f"category: {folder}{eol}")
    return "\n".join(lines), ("(none)", folder)


def read_page(p: pathlib.Path) -> tuple[bool, str]:
    raw = p.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return bom, (raw[3:] if bom else raw).decode("utf-8", errors="surrogateescape")


def encode_page(bom: bool, text: str) -> bytes:
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8", errors="surrogateescape")


def rekey_manifest(vault: pathlib.Path, old: str, new: str, apply: bool) -> None:
    path = vault / ".manifest.json"
    if not path.is_file():
        print("manifest: none (skipped)")
        return
    try:
        m = json.loads(path.read_text(encoding="utf-8-sig"))
        if not m.get("sources"):
            return  # current manifests are a vault marker with no per-page entries
        sources = m["sources"]
        if not isinstance(sources, dict):
            raise TypeError("sources is not an object")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"manifest: unreadable ({e}); skipped, run regen-manifest.py --dry-run to repair",
              file=sys.stderr)
        return
    old_k, new_k = f"{old}.md", f"{new}.md"
    touched = 0
    rebuilt = {}
    for k, entry in sources.items():
        key = new_k if k == old_k else k
        if isinstance(entry, dict):
            if entry.get("source_path") == old_k:
                entry["source_path"] = new_k
            pages = entry.get("pages")
            if isinstance(pages, list) and old_k in pages:
                entry["pages"] = [new_k if p == old_k else p for p in pages]
                touched += 1
        if key in rebuilt:
            print(f"manifest: {new_k} already present; left {k} as is", file=sys.stderr)
            key = k
        rebuilt[key] = entry
    if old_k not in sources and not touched:
        print(f"manifest: {old_k} not tracked (nothing to re-key)")
        return
    print(f"manifest: {old_k} -> {new_k}" + (f" ({touched} pages list(s) updated)" if touched else ""))
    if apply:
        m["sources"] = rebuilt
        path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rename/move one wiki page and rewrite links to it.")
    ap.add_argument("old", help="current vault-relative page path (with or without .md)")
    ap.add_argument("new", help="new vault-relative page path (with or without .md)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--mkdir", action="store_true", help="create NEW's folder if missing")
    ap.add_argument("--vault", default=None, help="vault root; auto-detected if omitted")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # keep stdout/stderr lines in order

    vault = resolve_vault(args.vault)
    old, new = norm_page(args.old), norm_page(args.new)
    old_path, new_path = vault / f"{old}.md", vault / f"{new}.md"
    if not old_path.is_file():
        ap.error(f"{old}.md not found in {vault}")
    if old == new:
        ap.error("OLD and NEW are the same page")
    if not KEBAB_RE.fullmatch(new.rsplit("/", 1)[-1]):
        ap.error(f"not kebab-case-lowercase: {new.rsplit('/', 1)[-1]}")
    if not is_content_page(f"{new}.md"):
        ap.error(f"{new}.md would not be a content page (scaffolding name, _ or . folder, templates/)")
    case_only = old.lower() == new.lower()
    if new_path.exists() and not (case_only and new_path.samefile(old_path)):
        ap.error(f"{new}.md already exists")
    new_folder = new.rsplit("/", 1)[0] if "/" in new else ""
    folder_path = vault / new_folder if new_folder else vault
    missing = not folder_path.is_dir()
    if missing:
        if not args.mkdir:
            ap.error(f"folder {new_folder}/ does not exist (pass --mkdir to create it)")
        parts = new_folder.split("/")
        bad = [p for i, p in enumerate(parts) if not KEBAB_RE.fullmatch(p)
               and not vault.joinpath(*parts[:i + 1]).is_dir()]
        if bad:
            ap.error(f"new folder name not kebab-case-lowercase: {', '.join(bad)}")

    # _raw/, _sources/, _archives/ are never rewritten and can hold thousands of
    # files, so they are not even read; their links stay as historical record.
    all_md = []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        rel_root = pathlib.Path(root).relative_to(vault).as_posix()
        for f in files:
            if f.endswith(".md"):
                all_md.append(f if rel_root == "." else f"{rel_root}/{f}")
    all_md.sort()
    linker = Linker(all_md, old, new)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== {mode}: {old}.md -> {new}.md ===")

    writes: dict[pathlib.Path, bytes] = {}
    skipped: list[str] = []
    n_links = 0
    for rel in all_md:
        name = rel.rsplit("/", 1)[-1]
        rewritable = is_content_page(rel) or name == "index.md"
        p = vault / rel
        try:
            bom, text = read_page(p)
        except OSError as e:
            print(f"  ! cannot read {rel}: {e}", file=sys.stderr)
            continue
        new_text, changes = rewrite_text(text, linker)
        if not rewritable:
            if changes:
                skipped.append(f"{rel} ({len(changes)} line(s))")
            continue
        if rel[:-3] == old and old_folder(old) != new_folder:
            new_text, cat = set_category(new_text, new_folder)
            if cat:
                print(f"{rel}: category: {cat[0]} -> {cat[1]}")
        if changes:
            print(f"{rel}:")
            for ln, a, b in changes:
                print(f"  {ln}: - {a.strip()}")
                print(f"  {ln}: + {b.strip()}")
            n_links += len(changes)
        if new_text != text:
            writes[p] = encode_page(bom, new_text)

    if linker.ambiguous:
        print(f"left alone, ambiguous (another page shares the name): "
              f"{', '.join(sorted(set(linker.ambiguous)))}", file=sys.stderr)
    if skipped:
        print("links to the page in files not rewritten (log.md, hot.md, templates/, ...):")
        for s in skipped:
            print(f"  {s}")

    rekey_manifest(vault, old, new, args.apply)

    if not args.apply:
        print(f"=== DRY RUN: {n_links} link line(s); {len(writes)} file(s) would change; "
              f"pass --apply to write ===")
        return 0

    if missing:
        folder_path.mkdir(parents=True)
    moved_bytes = writes.pop(old_path, None)
    if case_only:
        tmp = old_path.with_name("_tmp_wiki_mv_" + new_path.name)
        old_path.rename(tmp)
        tmp.rename(new_path)
    else:
        old_path.rename(new_path)
    if moved_bytes is not None:
        new_path.write_bytes(moved_bytes)
    for p, data in writes.items():
        p.write_bytes(data)
    print(f"=== applied: moved {old}.md -> {new}.md; {n_links} link line(s); "
          f"{len(writes) + (moved_bytes is not None)} file(s) rewritten ===")
    return 0


def old_folder(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


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
