#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Self-test for the wiki scripts and hooks: build throwaway vaults, check contracts.

Every check runs the real scripts as subprocesses (`uv run --script`) against fixture
vaults created in a temp dir, never a real vault, with WIKI_RUNLOG=0 so nothing lands in
~/.obsidian-wiki. One PASS/FAIL line per check; exit 1
if any check fails.

  uv run tests/selftest.py            # all checks
  uv run tests/selftest.py -k gate    # only checks whose name contains "gate"
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import datetime

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
TODAY = datetime.date.today().isoformat()
RESULTS: list[tuple[str, bool, str]] = []
ENV = dict(os.environ, WIKI_RUNLOG="0", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def run(args, cwd, stdin=None):
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=ENV)


def script(name, *args, cwd, stdin=None):
    return run(["uv", "run", "--script", str(SCRIPTS / name), *args], cwd, stdin)


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


def page(title, body="body", cat="notes", extra="", updated="2026-01-01"):
    return (f"---\ntitle: {title}\ncategory: {cat}\ntags: [t]\nsummary: s\n{extra}"
            f"created: 2026-01-01\nupdated: {updated}\n---\n{body}\n")


def make_vault(root: pathlib.Path, git=True) -> pathlib.Path:
    v = root / "vault"
    (v / "notes").mkdir(parents=True)
    (v / ".manifest.json").write_text("{}", encoding="utf-8")
    (v / "notes" / "a.md").write_text(page("a", "see [[notes/b]]"), encoding="utf-8")
    (v / "notes" / "b.md").write_text(page("b", "back to [[notes/a]]"), encoding="utf-8")
    (v / "log.md").write_text("- [2026-01-01] INIT\n", encoding="utf-8")
    (v / "hot.md").write_text("---\nupdated: 2026-01-01\n---\n# Hot\n\n## Recent Activity\n\n- x\n",
                              encoding="utf-8")
    (v / ".claude").mkdir()
    os.symlink(SCRIPTS, v / ".claude" / "wiki-scripts")
    if git:
        run(["git", "init", "-q"], v)
        (v / ".gitignore").write_text(".claude/\n", encoding="utf-8")
        shutil.copy(REPO / "hooks" / "pre-commit", v / ".git" / "hooks" / "pre-commit")
        run(["git", "add", "-A"], v)
        run(["git", "commit", "-qm", "init", "--no-verify"], v)
    return v


def lint(v, *args):
    r = script("wiki-lint.py", "--vault", str(v), *args, cwd=v)
    try:
        return r, json.loads(r.stdout)
    except json.JSONDecodeError:
        return r, None


def cats(data):
    return {(f["category"], f["file"]) for f in data["findings"]} if data else set()


# ------------------------------------------------------------------ checks

def t_lint_encodings(tmp):
    v = make_vault(tmp, git=False)
    (v / "notes" / "bom.md").write_bytes(b"\xef\xbb\xbf" + page("bom").encode())
    (v / "notes" / "crlf.md").write_bytes(page("crlf").replace("\n", "\r\n").encode())
    (v / "notes" / "latin.md").write_bytes(page("latin", "caf\xe9").encode("latin-1"))
    r, d = lint(v)
    check("lint: BOM page frontmatter detected", ("missing_frontmatter", "notes/bom.md") not in cats(d), r.stderr[-200:])
    check("lint: CRLF page parses", ("invalid_frontmatter", "notes/crlf.md") not in cats(d))
    check("lint: latin-1 page does not crash", d is not None and "Traceback" not in r.stderr, r.stderr[-200:])


def t_lint_links(tmp):
    v = make_vault(tmp, git=False)
    (v / "notes" / "code.md").write_text(page("code", "`[[nope]]` and\n~~~\n[[nope2]]\n~~~\n[[Notes/A]]"), encoding="utf-8")
    (v / "templates").mkdir()
    (v / "templates" / "t.md").write_text("<% tp.date %>\n", encoding="utf-8")
    (v / "2026-01-02.md").write_text("daily\n", encoding="utf-8")
    (v / "_raw").mkdir()
    (v / "_raw" / "x.md").write_text("no frontmatter\n", encoding="utf-8")
    r, d = lint(v)
    broken = [f for f in d["findings"] if f["category"] == "broken_link"]
    check("lint: links in inline code and ~~~ fences ignored, case-insensitive resolve", not broken, str(broken)[:200])
    files = {f["file"] for f in d["findings"]}
    check("lint: templates/, daily notes, _dirs are not pages",
          not files & {"templates/t.md", "2026-01-02.md", "_raw/x.md"}, str(files)[:200])


def t_lint_dupkey_and_events(tmp):
    v = make_vault(tmp, git=False)
    (v / "notes" / "dup.md").write_text("---\ntitle: a\ntitle: b\ncategory: notes\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nx\n", encoding="utf-8")
    for d_ in ("2026-01-01", "2026-02-01"):
        (v / "notes" / f"standup-{d_}.md").write_text(page("s"), encoding="utf-8")
        (v / "notes" / f"review-{d_}.md").write_text(page("r"), encoding="utf-8")
    r, d = lint(v)
    c = cats(d)
    check("lint: duplicate frontmatter key is invalid_frontmatter", ("invalid_frontmatter", "notes/dup.md") in c)
    check("lint: meeting/standup series not a stale snapshot", ("stale_snapshot", "notes/standup-2026-01-01.md") not in c)
    check("lint: dated snapshot family still flagged", ("stale_snapshot", "notes/review-2026-01-01.md") in c)
    script("wiki-lint.py", "--vault", str(v), "--fix", cwd=v)
    check("lint: --fix leaves snapshots alone", "superseded_by" not in (v / "notes" / "review-2026-01-01.md").read_text())
    script("wiki-lint.py", "--vault", str(v), "--fix-snapshots", cwd=v)
    check("lint: --fix-snapshots wires the older snapshot", "superseded_by" in (v / "notes" / "review-2026-01-01.md").read_text())
    check("lint: --fix-snapshots skips standups", "superseded_by" not in (v / "notes" / "standup-2026-01-01.md").read_text())


def t_gate(tmp):
    v = make_vault(tmp)
    (v / "notes" / "leftover.md").write_text("no frontmatter\n", encoding="utf-8")
    p = v / "notes" / "a.md"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n") + b"more\r\n")
    run(["git", "add", "notes/a.md"], v)
    r = run(["git", "commit", "-qm", "edit a"], v)
    check("gate: unstaged leftover does not block a commit", r.returncode == 0, (r.stdout + r.stderr)[-300:])
    raw = p.read_bytes()
    check("gate: stamp-staged sets updated: today", f"updated: {TODAY}".encode() in raw)
    check("gate: stamp-staged keeps CRLF", raw.count(b"\r\n") == raw.count(b"\n"))
    (v / "notes" / "bad.md").write_text("oops\n", encoding="utf-8")
    run(["git", "add", "notes/bad.md"], v)
    r = run(["git", "commit", "-qm", "bad"], v)
    check("gate: staged page without frontmatter blocks", r.returncode != 0)
    run(["git", "reset", "-q"], v)
    (v / "notes" / "bad.md").unlink()
    run(["git", "rm", "-q", "notes/b.md"], v)
    r = run(["git", "commit", "-qm", "drop b"], v)
    check("gate: deleting a linked page blocks (link in an unstaged page)", r.returncode != 0 and "notes/b" in r.stdout + r.stderr)
    run(["git", "reset", "-q", "--hard"], v)
    (v / "img.txt").write_text("x", encoding="utf-8")
    run(["git", "add", "img.txt"], v)
    check("gate: commit without markdown skips the checks", run(["git", "commit", "-qm", "x"], v).returncode == 0)


def t_partial_stage(tmp):
    v = make_vault(tmp)
    p = v / "notes" / "b.md"
    p.write_text(p.read_text() + "one\n", encoding="utf-8")
    run(["git", "add", "notes/b.md"], v)
    p.write_text(p.read_text() + "two\n", encoding="utf-8")
    run(["git", "commit", "-qm", "partial"], v)
    check("gate: partially staged page is not stamped", f"updated: {TODAY}" not in p.read_text())


def t_wiki_new(tmp):
    v = make_vault(tmp, git=False)
    r = script("wiki-new.py", "--vault", str(v), "notes/review-2026-03-01", "--title", "Review: Q1",
               "--summary", "s", "--supersedes", "notes/a", cwd=v)
    new = v / "notes" / "review-2026-03-01.md"
    check("wiki-new: writes a page that lints clean", new.is_file() and r.returncode == 0, r.stderr[-200:])
    _, d = lint(v, "--errors-only")
    check("wiki-new: no error findings on the new page", not any(f["file"] == "notes/review-2026-03-01.md" for f in d["findings"]))
    check("wiki-new: --supersedes wires the old page", "superseded_by: notes/review-2026-03-01" in (v / "notes" / "a.md").read_text())
    r = script("wiki-new.py", "--vault", str(v), "Notes/Bad", "--title", "t", "--summary", "s", cwd=v)
    check("wiki-new: refuses a non-kebab name", r.returncode == 2)


def t_wiki_mv(tmp):
    v = make_vault(tmp, git=False)
    (v / "notes" / "c.md").write_text(page("c", "[[notes/b|Bee]] ![[notes/b#h]] `[[notes/b]]`"), encoding="utf-8")
    (v / "archive").mkdir()
    r = script("wiki-mv.py", "--vault", str(v), "notes/b", "archive/bee", cwd=v)
    check("wiki-mv: dry run changes nothing", (v / "notes" / "b.md").is_file(), r.stderr[-200:])
    r = script("wiki-mv.py", "--vault", str(v), "notes/b", "archive/bee", "--apply", cwd=v)
    c = (v / "notes" / "c.md").read_text()
    check("wiki-mv: moves the page and sets category", (v / "archive" / "bee.md").is_file()
          and "category: archive" in (v / "archive" / "bee.md").read_text(), r.stderr[-200:])
    check("wiki-mv: keeps alias and embed heading, skips inline code",
          "[[archive/bee|Bee]]" in c and "![[archive/bee#h]]" in c and "`[[notes/b]]`" in c, c[-200:])
    _, d = lint(v, "--errors-only")
    check("wiki-mv: no broken links afterwards", not any(f["category"] == "broken_link" for f in d["findings"]))


def t_wiki_commit(tmp):
    v = make_vault(tmp)
    for n in ("a", "b"):
        p = v / "notes" / f"{n}.md"
        p.write_text(p.read_text() + "more\n", encoding="utf-8")
    (v / "stray.txt").write_text("x", encoding="utf-8")
    plan = "docs(notes): a\n  notes/a.md\ndocs(notes): b\n  notes/b.md\n"
    r = script("wiki-commit.py", "--journal", "CAPTURE page=[[notes/a]] test", cwd=v, stdin=plan)
    log = run(["git", "log", "--format=%s", "-3"], v).stdout.split("\n")
    check("wiki-commit: one commit per group", log[:2] == ["docs(notes): b", "docs(notes): a"], (r.stdout + r.stderr)[-300:])
    last = run(["git", "show", "--name-only", "--format=", "HEAD"], v).stdout.split()
    check("wiki-commit: journal and hot.md ride in the last group", {"log.md", "hot.md"} <= set(last), str(last))
    check("wiki-commit: leftovers surfaced, not committed",
          "stray.txt" in r.stdout and "stray.txt" in run(["git", "status", "--short"], v).stdout)
    r = script("wiki-commit.py", cwd=v, stdin="msg\n  .\n")
    check("wiki-commit: refuses '.'", r.returncode == 2)


def t_journal(tmp):
    v = make_vault(tmp, git=False)
    r = script("wiki-journal.py", "--vault", str(v), "--log", "x" * 300, cwd=v)
    check("journal: refuses a log entry over 240 chars", r.returncode != 0 and "x" * 300 not in (v / "log.md").read_text())
    (v / "hot.md").write_bytes((v / "hot.md").read_bytes().replace(b"\n", b"\r\n"))
    script("wiki-journal.py", "--vault", str(v), "--log", "CAPTURE ok", cwd=v)
    hot = (v / "hot.md").read_bytes()
    check("journal: --log also feeds hot.md", b"CAPTURE ok" in hot)
    check("journal: keeps CRLF in hot.md", hot.count(b"\r\n") == hot.count(b"\n"))


def t_hook(tmp):
    v = make_vault(tmp, git=False)
    p = v / "notes" / "a.md"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes().replace(b"\n", b"\r\n"))
    (v / "_raw").mkdir()
    raw = v / "_raw" / "r.md"
    raw.write_text(page("r"), encoding="utf-8")
    for f in (p, raw):
        payload = json.dumps({"cwd": str(v), "tool_input": {"file_path": str(f)}})
        run(["uv", "run", "--script", str(REPO / "hooks" / "update-timestamp.py")], v, payload)
    b = p.read_bytes()
    check("hook: stamps a BOM+CRLF page and keeps both",
          b.startswith(b"\xef\xbb\xbf") and f"updated: {TODAY}".encode() in b and b.count(b"\r\n") == b.count(b"\n"))
    check("hook: never stamps _dirs", f"updated: {TODAY}" not in raw.read_text())


def t_regen_json(tmp):
    v = make_vault(tmp, git=False)
    legacy = {"version": 1, "created": "2026-01-01T00:00:00Z", "vault_path": "/abs/path",
              "private_paths": ["me"], "sources": {"notes/a.md": {"mtime": "x"}}}
    (v / ".manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    r = script("regen-manifest.py", "--vault", str(v), cwd=v)
    m = json.loads((v / ".manifest.json").read_text())
    check("regen-manifest: strips legacy page entries and vault_path, keeps private_paths",
          "sources" not in m and "vault_path" not in m and m.get("private_paths") == ["me"]
          and m.get("created") == legacy["created"], r.stdout[-200:])
    before = (v / ".manifest.json").read_text()
    script("regen-manifest.py", "--vault", str(v), cwd=v)
    check("regen-manifest: second run changes nothing", (v / ".manifest.json").read_text() == before)
    (v / ".manifest.json").write_text("{nope", encoding="utf-8")
    r = script("regen-manifest.py", "--vault", str(v), cwd=v)
    check("regen-manifest: corrupt manifest quarantined, not a crash",
          r.returncode == 0 and (v / ".manifest.json.bad").exists()
          and json.loads((v / ".manifest.json").read_text()).get("version") == 1, r.stderr[-200:])


def t_source_status(tmp):
    v = make_vault(tmp, git=False)
    (v / "_sources").mkdir()
    (v / "_sources" / "doc.pdf").write_bytes(b"pdf")
    (v / "notes" / "doc.md").write_text(page("doc", extra="sources: [_sources/doc.pdf]\n", updated="2999-01-01"), encoding="utf-8")
    ext = tmp / "outside"
    ext.mkdir()
    (ext / "doc.pdf").write_bytes(b"pdf v2")
    (ext / "fresh.pdf").write_bytes(b"x")

    def status(src):
        r = script("ingest-prep.py", "--vault", str(v), "--source", str(src), cwd=v)
        try:
            return json.loads(r.stdout)["source_status"]
        except (json.JSONDecodeError, KeyError):
            return r.stderr[-150:]
    check("ingest-prep: in-vault source cited by a page is unchanged", status(v / "_sources" / "doc.pdf") == "unchanged")
    check("ingest-prep: external source differing from its snapshot is modified", status(ext / "doc.pdf") == "modified")
    check("ingest-prep: unknown source is new", status(ext / "fresh.pdf") == "new")


def t_query(tmp):
    v = make_vault(tmp, git=False)
    (v / "notes" / "cafe.md").write_text(page("Café ședința"), encoding="utf-8")
    r = script("wiki.query", "--vault", str(v), "--all", "--paths", "sedinta", cwd=v)
    check("wiki.query: accent-insensitive match", "notes/cafe.md" in r.stdout, (r.stdout + r.stderr)[-200:])


def t_sources(tmp):
    v = make_vault(tmp, git=False)
    arch = v / "_mail" / "t1"
    arch.mkdir(parents=True)
    (arch / "thread.md").write_text("# Thread\nnew reply about the roof", encoding="utf-8")
    old = v / "_mail" / "t0"
    old.mkdir()
    (old / "thread.md").write_text("old", encoding="utf-8")
    os.utime(old / "thread.md", (0, 0))
    r = script("ingest-prep.py", "--vault", str(v), "--sources-dir", "_mail", "--since", "2026-01-01", cwd=v)
    try:
        d = json.loads(r.stdout)
        paths = [f["path"] for f in d["files"]]
    except (json.JSONDecodeError, KeyError):
        paths = []
    check("ingest-prep: --sources-dir lists only files changed since the cut-off, with excerpt",
          paths == ["t1/thread.md"] and "roof" in d["files"][0]["excerpt"], (r.stdout + r.stderr)[-200:])


CHECKS = [t_lint_encodings, t_lint_links, t_lint_dupkey_and_events, t_gate, t_partial_stage,
          t_wiki_new, t_wiki_mv, t_wiki_commit, t_journal, t_hook, t_regen_json, t_source_status, t_query, t_sources]


def main() -> int:
    ap = argparse.ArgumentParser(description="Self-test the wiki scripts against fixture vaults.")
    ap.add_argument("-k", help="only run check functions whose name contains this")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="wiki-selftest-") as base:
        for fn in CHECKS:
            if args.k and args.k not in fn.__name__:
                continue
            tmp = pathlib.Path(base) / fn.__name__
            tmp.mkdir()
            try:
                fn(tmp)
            except Exception as e:  # a crash in a check is a failure, not an abort
                check(f"{fn.__name__}: raised", False, f"{type(e).__name__}: {e}")
    failed = 0
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))
        failed += not ok
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
