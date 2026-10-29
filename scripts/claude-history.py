#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Search and summarize Claude Code session transcripts for a vault (or any project).

Claude Code keeps one JSONL transcript per session under
~/.claude/projects/<project-path-with-non-alphanumerics-as-dashes>/. This streams
them line by line, so a few hundred MB costs seconds and never enters an agent's
context.

  sessions   list sessions: id, start date, prompt and tool-call counts, first prompt
  search     find the session(s) about something: every TERM must appear in a user
             prompt (--all also searches assistant text and tool inputs)
  runs       timings from ~/.obsidian-wiki/runs.tsv, the log every wiki script appends
             to (median, p90, total per script; hook stamps and failures)
  stats      usage summary: skills invoked, wiki scripts run (count, flags, median
             and total seconds), git commits, --no-verify, pre-commit failures,
             tool calls per session. The quick way to see where a vault's time goes.

Usage:
  uv run claude-history.py sessions [--project PATH] [--limit 20]
  uv run claude-history.py search TERM [TERM ...] [--project PATH] [--all] [--limit 10]
  uv run claude-history.py stats [--project PATH] [--since 2026-09-01] [--format md|json]

--project defaults to the current directory; pass a vault path, or a raw
~/.claude/projects/<dir> name. Read-only. Stdlib only.
"""
import argparse
import json
import os
import pathlib
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime

PROJECTS = pathlib.Path.home() / ".claude" / "projects"
SCRIPT_RE = re.compile(r"(?:wiki-scripts|cm-llm-wiki/scripts)/([\w.-]+\.py|wiki\.query)((?:\s+--?[\w-]+)*)")
FLAG_RE = re.compile(r"\s(--[\w-]+)")


def project_dir(arg: str | None) -> pathlib.Path:
    if arg and "/" not in arg and (PROJECTS / arg).is_dir():
        return PROJECTS / arg
    path = os.path.realpath(os.path.expanduser(arg or os.getcwd()))
    d = PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", path)
    if not d.is_dir():
        raise SystemExit(f"no transcripts for {path} (looked for {d})")
    return d


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    out.append(text_of(b.get("content")))
        return "\n".join(out)
    return ""


def is_human_prompt(rec: dict) -> bool:
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
        return False
    c = rec.get("message", {}).get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return False
    t = text_of(c).strip()
    return bool(t) and not t.startswith(("<local-command", "<command-name>", "Caveat:", "<system-reminder>"))


def ts(rec: dict):
    t = rec.get("timestamp")
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
    except ValueError:
        return None


def records(path: pathlib.Path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def files(d: pathlib.Path, since: str | None):
    for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        if since and datetime.fromtimestamp(f.stat().st_mtime).date().isoformat() < since:
            continue
        yield f


def one_line(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_sessions(d, args):
    rows = []
    for f in files(d, args.since):
        first, start, prompts, tools = None, None, 0, 0
        for r in records(f):
            start = start or ts(r)
            if is_human_prompt(r):
                prompts += 1
                first = first or text_of(r["message"]["content"])
            elif r.get("type") == "assistant":
                c = r.get("message", {}).get("content")
                if isinstance(c, list):
                    tools += sum(1 for b in c if isinstance(b, dict) and b.get("type") == "tool_use")
        if prompts:
            rows.append((start, f.stem, prompts, tools, first or ""))
    for start, sid, p, t, first in rows[-args.limit:]:
        when = start.astimezone().strftime("%Y-%m-%d %H:%M") if start else "?"
        print(f"{when}  {sid}  {p:3}p {t:4}t  {one_line(first, 90)}")


def cmd_search(d, args):
    terms = [t.lower() for t in args.terms]
    hits = []
    for f in files(d, args.since):
        first, start, matches = None, None, []
        for r in records(f):
            start = start or ts(r)
            human = is_human_prompt(r)
            if human:
                first = first or text_of(r["message"]["content"])
            if not (human or args.all):
                continue
            c = r.get("message", {}).get("content")
            t = text_of(c)
            if args.all and isinstance(c, list):
                t += " ".join(json.dumps(b.get("input", "")) for b in c
                              if isinstance(b, dict) and b.get("type") == "tool_use")
            low = t.lower()
            if all(term in low for term in terms):
                i = low.find(terms[0])
                matches.append(one_line(t[max(0, i - 60): i + 120], 160))
        if matches:
            hits.append((start, f.stem, first or "", matches))
    for start, sid, first, matches in hits[-args.limit:]:
        when = start.astimezone().strftime("%Y-%m-%d %H:%M") if start else "?"
        print(f"{when}  {sid}  ({len(matches)} matches)  first prompt: {one_line(first, 80)}")
        for m in matches[:3]:
            print(f"    … {m}")
    if not hits:
        print("no matches")
    else:
        print(f"\nresume with: claude --resume <session-id>")


def cmd_stats(d, args):
    skills, scripts, flags, durations = Counter(), Counter(), defaultdict(Counter), defaultdict(list)
    sessions = commits = no_verify = gate_fail = 0
    calls_per_session = []
    for f in files(d, args.since):
        pending, calls, human = {}, 0, 0
        for r in records(f):
            c = r.get("message", {}).get("content")
            if r.get("type") == "assistant" and isinstance(c, list):
                for b in c:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    calls += 1
                    name, inp = b.get("name"), b.get("input") or {}
                    if name == "Skill":
                        skills[inp.get("skill", "?")] += 1
                    if name != "Bash":
                        continue
                    cmd = inp.get("command", "")
                    found = []
                    for m in SCRIPT_RE.finditer(cmd):
                        scripts[m.group(1)] += 1
                        found.append(m.group(1))
                        for fl in FLAG_RE.findall(" " + m.group(2)):
                            flags[m.group(1)][fl] += 1
                    if re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
                        commits += 1
                        no_verify += "--no-verify" in cmd
                        found.append("git commit")
                    if found:
                        pending[b.get("id")] = (found, ts(r))
            elif r.get("type") == "user":
                if is_human_prompt(r):
                    human += 1
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                            found, t0 = pending.pop(b["tool_use_id"])
                            t1 = ts(r)
                            if "git commit" in found and "pre-commit:" in text_of(b.get("content")):
                                gate_fail += 1
                            if t0 and t1:
                                for name in found:
                                    durations[name].append((t1 - t0).total_seconds())
        if human:
            sessions += 1
            calls_per_session.append(calls)
    out = {
        "project": d.name, "sessions": sessions,
        "tool_calls_per_session_median": statistics.median(calls_per_session) if calls_per_session else 0,
        "skills": dict(skills.most_common()),
        "scripts": {s: {"runs": n, "flags": dict(flags[s].most_common(6)),
                        "median_s": round(statistics.median(durations[s]), 1) if durations[s] else None,
                        "total_min": round(sum(durations[s]) / 60, 1)}
                    for s, n in scripts.most_common()},
        "git_commits": commits, "no_verify": no_verify, "pre_commit_failures": gate_fail,
        "git_commit_median_s": round(statistics.median(durations["git commit"]), 1) if durations["git commit"] else None,
    }
    if args.format == "json":
        print(json.dumps(out, indent=2))
        return
    print(f"## {d.name}: {sessions} sessions, median {out['tool_calls_per_session_median']} tool calls each\n")
    print("Skills: " + (", ".join(f"{k} {v}" for k, v in skills.most_common()) or "none"))
    print(f"\nCommits: {commits}, --no-verify {no_verify}, pre-commit failures {gate_fail}, "
          f"median {out['git_commit_median_s']} s\n")
    print("| script | runs | median s | total min | top flags |\n|---|---|---|---|---|")
    for s, v in out["scripts"].items():
        fl = " ".join(f"{k}×{n}" for k, n in v["flags"].items())
        print(f"| {s} | {v['runs']} | {v['median_s']} | {v['total_min']} | {fl} |")


def cmd_runs(args):
    """Summarize ~/.obsidian-wiki/runs.tsv, the per-run log the wiki scripts append."""
    path = pathlib.Path.home() / ".obsidian-wiki" / "runs.tsv"
    if not path.is_file():
        raise SystemExit(f"no run log yet at {path}")
    secs, fails, stamps, last = defaultdict(list), Counter(), Counter(), {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        f = line.split("\t")
        if len(f) < 6 or (args.since and f[0][:10] < args.since):
            continue
        when, script, _cwd, sec, rc = f[:5]
        if script == "update-timestamp.py":
            stamps[rc] += 1  # rc column holds stamped / failed for the hook
            if rc == "failed":
                last["update-timestamp.py failed"] = f"{when} {f[5]}"
            continue
        try:
            secs[script].append(float(sec))
        except ValueError:
            continue
        if rc not in ("0", "None"):
            fails[script] += 1
    print("| script | runs | median s | p90 s | total min | nonzero exits |\n|---|---|---|---|---|---|")
    for script, xs in sorted(secs.items(), key=lambda kv: -sum(kv[1])):
        xs.sort()
        p90 = xs[min(len(xs) - 1, int(len(xs) * 0.9))]
        print(f"| {script} | {len(xs)} | {statistics.median(xs):.1f} | {p90:.1f} | "
              f"{sum(xs) / 60:.1f} | {fails[script]} |")
    if stamps:
        print(f"\nupdate-timestamp hook: " + ", ".join(f"{k} {v}" for k, v in stamps.items()))
    for k, v in last.items():
        print(f"last {k}: {v}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Search and summarize Claude Code transcripts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runs = sub.add_parser("runs", help="summarize ~/.obsidian-wiki/runs.tsv (script timings)")
    runs.add_argument("--since", help="only runs on or after yyyy-MM-dd")
    for name in ("sessions", "search", "stats"):
        p = sub.add_parser(name)
        p.add_argument("--project", help="project or vault path (default: cwd), or a ~/.claude/projects dir name")
        p.add_argument("--since", help="only transcripts modified on or after yyyy-MM-dd")
        if name == "search":
            p.add_argument("terms", nargs="+")
            p.add_argument("--all", action="store_true", help="also search assistant text and tool inputs")
        if name in ("sessions", "search"):
            p.add_argument("--limit", type=int, default=20 if name == "sessions" else 10)
        if name == "stats":
            p.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()
    if args.cmd == "runs":
        cmd_runs(args)
        return 0
    d = project_dir(args.project)
    {"sessions": cmd_sessions, "search": cmd_search, "stats": cmd_stats}[args.cmd](d, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
