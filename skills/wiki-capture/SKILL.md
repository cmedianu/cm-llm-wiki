---
name: wiki-capture
description: >
  Save knowledge from wherever you are into the Obsidian wiki. Use this skill when the user says
  "save this", "/wiki-capture", "capture this", "file this conversation", "preserve this",
  "add this to my wiki", or wants to turn what was just discussed into lasting knowledge — that is
  the default conversation-capture mode. Also handles project-sync mode: run from any project when the
  user says "update wiki", "sync to wiki", "save this to my wiki", "update obsidian", or wants to
  distill what they've been working on into their knowledge base. The skill classifies the content,
  rewrites it as declarative knowledge (not a chat transcript), and places it in the correct vault
  category.
---

# Wiki Capture: Save Knowledge into the Wiki

You are preserving knowledge as a permanent wiki note. The goal is to extract the *substance*, the knowledge itself, not a summary of what was said.

## Two Modes

- **Conversation capture (default):** turn the current chat into a wiki note. This is Steps 1 to 7 below. Triggers: "save this", "capture this", "file this conversation".
- **Project sync:** run from *any* project directory to distil what you have been building (code, commits, docs) into the wiki. Triggers: "update wiki", "sync to wiki", "update obsidian". This mode has its own flow; see **Project Sync Mode** at the end. The vault resolution, Page-Writing Protocol, and tracking-file updates are shared with the default mode.

**Brief mode:** if the user wants something to send (a brief, memo or PDF for other people) rather than a page for later, follow `references/brief-mode.md` instead of Steps 3-5.

## Before You Start

1. **Resolve vault** — per the Config Resolution Protocol in `wiki/SKILL.md`: manifest walk-up, then `~/.obsidian-wiki/projects.json`, then quiz the registered vaults (persisting the choice). All paths derive from the vault root.
2. **Run `ingest-prep.py` once** with keywords from the conversation. It returns the categories (folders on disk), `private_paths`, `index_status` per folder, and `related_pages` (existing pages on the topic: your duplicate check and link targets). `--source` is required but needs no real file here; ignore `source_status`:

   ```bash
   uv run "$OBSIDIAN_VAULT_PATH/.claude/wiki-scripts/ingest-prep.py" --vault "$OBSIDIAN_VAULT_PATH" \
     --source none --keywords "kw1,kw2"
   ```

   Use this instead of globbing, grepping frontmatter or parsing `index.md`.
3. Read `$OBSIDIAN_VAULT_PATH/hot.md` if it exists — it gives context on recent activity

## Step 1: Identify What's Worth Preserving

Scan the conversation. Ask: what knowledge emerged here that would be valuable in 3 months with no memory of this chat?

Worth preserving:
- Decisions made and *why* they were made
- Analysis, frameworks, mental models developed
- Technical findings, patterns, or procedures
- Synthesized understanding of a topic
- Clear explanations of a concept that took effort to arrive at
- Key facts from an external source discussed in the conversation

Skip:
- Logistics, scheduling, pleasantries
- Exploratory back-and-forth where no conclusion was reached
- Content that's already in the wiki

If nothing material emerged, tell the user and stop.

## Step 2: Classify the Content Type

Assign one of five types — this sets the **tone and body structure** (Step 5), not a fixed destination:

| Type | Description |
|---|---|
| `synthesis` | Multi-step analysis or an answer to a specific question that required reasoning |
| `concept` | A definition, framework, or mental model (what a thing *is*) |
| `source` | Summary of an external document, article, or resource discussed |
| `decision` | A strategic, architectural, or design choice and its rationale |
| `session` | A complete discussion summary when the conversation spans multiple topics |

**Pick the target folder from disk, not from the type.** Choose from the prep JSON's `categories` and route the note into the best-fitting **existing** category; if the content clearly belongs to a project the vault tracks as its own folder, nest it there. If no folder fits, tell the user they may create one (or fall back to a general/misc folder if the vault has one). The `category:` frontmatter equals the chosen folder.

**Privacy:** if the captured knowledge is private or sensitive — or belongs in a private area listed in the prep JSON's `private_paths` — file it inside that private area and do not surface its title/summary in any more-public index. See the Privacy digest in `wiki/references/page-protocol.md`.

## Step 3: Rewrite as Declarative Knowledge

Do **not** write a summary of the conversation. Write the knowledge itself, in declarative present tense:

- Not: "The user asked about X and Claude explained that..."
- Yes: "X works by..."
- Not: "We decided to use Y because..."
- Yes: "Y is preferred over Z because [reason]. [^[inferred] if the rationale was implied, not stated explicitly]"

Apply provenance markers per the **Page-Writing Protocol** in `wiki/references/page-protocol.md` — for a conversation, a claim stated outright is extracted (no marker), one you generalized from the discussion is `^[inferred]`, and a disputed or uncertain one is `^[ambiguous]`.

**Be concise.** Distil, don't pad. Prefer tight bullets over prose paragraphs; cut hedging,
restatement, and throat-clearing. Every sentence must carry a fact the reader can't infer from the
others. A dense one-screen page beats a thorough three-screen one — if it can be said in a clause,
don't spend a sentence; if a section is empty, omit it rather than filling it. Concision is
*density* (no filler per fact), not low *coverage* (dropping facts worth keeping): capture the
high-signal knowledge, but say each thing once and tightly. Length is an emergent result of how much
signal the conversation held, never a target to hit or pad toward.

## Step 4: Generate a Slug and Title

Derive a clear, descriptive title from the content. Slugify it:
- Lowercase, words separated by hyphens
- Max 50 characters
- Avoid dates in the slug (the frontmatter has `created`)

## Step 5: Write the Wiki Note

Create the page with `wiki-new.py <folder from Step 2>/<slug>` (it writes the frontmatter and `lifecycle: draft`) and write the body **per the Page-Writing Protocol in `wiki/references/page-protocol.md`** (provenance markers, ≥2 wikilinks, journal). Pass `--sources conversation:<project>/<yyyy-MM-dd>`, where `<project>` is the basename of the directory the capture ran from, e.g. `conversation:ObsidianVault/2026-07-04`, so provenance records *where* the conversation happened.

Body structure by type:

**synthesis / decision:**
```markdown
# Title

## Context
<What prompted this — the problem or question being addressed>

## Finding / Decision
<The core knowledge or conclusion>

## Reasoning
<Why this is the case or why this choice was made>

## Implications
<What follows from this — what to watch for, next steps, trade-offs>

## Related
<[[wikilinks]] to connected pages>
```

**concept:**
```markdown
# Title

<Definition in one clear sentence.>

## What It Is
<Explanation of the concept>

## How It Works
<Mechanism or structure>

## When to Use
<Applicability, conditions, trade-offs>

## Related
<[[wikilinks]]>
```

**source:**
```markdown
# Title

> Source: <title or URL>

## What It Covers
<What the source is about>

## Key Points
<Bulleted claims with provenance markers>

## Open Questions
<What it raises but doesn't answer — omit if none>

## Related
<[[wikilinks]]>
```

**session:**
```markdown
# Title

*Session captured: <date>*

## Topics Covered
<Brief list>

## Key Takeaways
<The 3-5 most important things that emerged>

## Decisions Made
<Any explicit decisions, with rationale>

## Open Questions
<What remains unresolved>

## Related
<[[wikilinks]]>
```

The Protocol's ≥2-wikilink rule applies. Take link targets from the prep JSON's `related_pages`. If fewer than 2 related pages exist, create minimal stubs for the most important concepts referenced.

**Back-links:** run `ingest-prep.py --backlinks-for "<new page>"` and add the links from existing pages that genuinely help (judgement rules in `wiki-ingest` Step 6).

## Step 6: Update Tracking Files

**`index.md`** — per `index_status` in the prep JSON: `base_backed` or `hybrid` needs **no** edit (the base lists new pages from frontmatter; don't add a hand bullet to a hybrid either), only `manual` gets a new line under its category section.

**`log.md` and `hot.md`** — one `wiki-journal.py` line (it feeds both):

```bash
uv run .claude/wiki-scripts/wiki-journal.py --hot-trim 3 --log 'CAPTURE type=<type> [[<path>]]: one-line gist'
```

**Key Takeaways** is semantic — the script won't touch it; edit it by hand with Edit if the note flagged something worth surfacing.

## Step 7: Confirm to User

Report the saved path and title:
```
Saved to: <category>/<slug>.md
Title: <Title>
Type: synthesis
```

## Quality Checklist

- [ ] Content rewritten as declarative knowledge (not a chat transcript)
- [ ] Type classified correctly; target folder is an existing category discovered from disk
- [ ] Body follows the per-type structure
- [ ] Written per the Page-Writing Protocol (frontmatter, summary, provenance, ≥2 links, journal)
- [ ] Private/sensitive content filed in its private area, not surfaced in a public index
- [ ] Confirmed save path to user

---

## Project Sync Mode

*(Merged from the former `wiki-update` skill.)* Use this flow when the trigger is "update wiki" / "sync
to wiki" / "update obsidian" and you are sitting in an arbitrary **project** directory, not distilling a
conversation. The job is to push what you have been *building* into the wiki. Vault resolution, the
Page-Writing Protocol, and tracking-file updates are the same as the default mode; the steps below
replace Steps 1 to 6.

### PS1: Understand the project

Scan the CWD to figure out what the project is: `README.md`, `docs/`, source structure (frameworks,
languages, key abstractions), the manifest-of-record (`package.json`, `pyproject.toml`, `go.mod`,
`Cargo.toml`, and the like), the git log (decision-signalling commit messages, not "fix typo" churn),
and any `.claude/` memory files. Derive a clean project name from the directory name.

### PS2: Compute the delta

Bound the delta from disk and git:

- **First-time sync** (no existing vault pages for this project): full scan; everything is new.
- **Re-sync:** take the `updated:` date of the project overview page
  (`projects/<project-name>/<project-name>.md`) and run `git log --since="<that date>" --oneline`
  (or `git log <ref>..HEAD` if the user gave a ref). If nothing meaningful changed, tell the user and stop.

### PS3: Decide what to distil

The Karpathy question: *what would you want to know about this project if you came back in 3 months with
zero context?* **Distil:** architecture decisions and *why*; patterns discovered while building; what
tools/services/APIs it depends on and how they wire together; key abstractions and the mental model;
trade-offs evaluated and what was picked. **Skip:** file listings, boilerplate, obvious config,
individual bug fixes with no broader lesson, dependency versions, anything the code already says
plainly. Heuristic: *if reading the codebase answers the question, don't wiki it; if you'd re-derive it
from git blame across 20 commits, wiki it.*

### PS4: Distil into wiki pages

Create new pages with `wiki-new.py` and write them per the Page-Writing Protocol in `wiki/references/page-protocol.md`. Placement:

- **Project-specific** knowledge goes under `$VAULT/projects/<project-name>/`: an overview page
  `projects/<project-name>/<project-name>.md` (named after the project, **never** `_project.md`, because
  the filename is the Obsidian graph node label) plus discovered subcategories under it. Reuse subfolders
  that already exist; don't impose a fixed set.
- **Global** knowledge routes to the best-fitting existing top-level category (discovered from disk). If
  genuinely nothing fits, `mkdir` a new top-level category rather than forcing a page into the wrong
  folder.

**Provenance mapped to code:** *extracted* (no marker) covers anything visible in
code/config/docs/commit messages (structure, dependencies, signatures, what a file does); `^[inferred]`
covers *why* a decision was made, rationale, and trade-offs, unless a commit/doc/ADR states it;
`^[ambiguous]` covers a case where code and docs disagree, or an in-progress migration with two patterns
side by side. **Merge, don't duplicate:** fold into an existing page and add the new source rather than
creating a second page on the same topic. Don't copy code; distil the *knowledge* ("uses a debounced
search with 300ms delay", not the debounce function).

### PS5: Cross-link

Add `[[wikilinks]]` from new pages to related existing pages, link the project overview to its pages, and
run the back-link pass (`ingest-prep.py --backlinks-for`, as in Step 5).

### PS6: Update tracking

Same as Step 6 (default mode): update a hand-curated `index.md` only (base-backed needs none), and drive `log.md` / `hot.md` with `wiki-journal.py`, for
which you compose the conceptual one-line entry. Use a `WIKI_UPDATE` log op-code, e.g.
`--log 'WIKI_UPDATE project=<name> pages_updated=X pages_created=Y source_cwd=/path/to/project'`. Edit
the semantic **Active Threads** / **Key Takeaways** sections by hand if this sync made the project an
ongoing focus or surfaced a key decision. The project overview `<project-name>.md` is the anchor, so
make it good.
