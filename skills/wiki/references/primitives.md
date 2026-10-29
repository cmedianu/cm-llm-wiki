# Retrieval Primitives

Reading the vault is the dominant cost of every read-side skill. Use the cheapest primitive that answers the question — escalate only when insufficient.

| Need | Primitive | Cost |
|---|---|---|
| Does a page exist? title/category/tags? | `.claude/wiki-scripts/wiki.query --all --paths <keyword>`; `Grep` frontmatter blocks (a base-backed `index.md` lists nothing as raw text) | **Cheapest** |
| 1–2 sentence preview of a page | Read its `summary:` frontmatter field | **Cheap** |
| A specific claim or section inside a page | `Grep -A <n> -B <n> "<term>" <file>` | **Medium** |
| Whole-page content | `Read <file>` | **Expensive** — last resort |
| Relationships across pages | `Grep "\[\[.*?\]\]"` across vault, or walk wikilinks | Case-by-case |

The rule: if `summary:` fields answer it, don't read page bodies. If a grepped section with `-A 10 -B 2` gives the claim, don't read the whole page. A 500-line page opened to read 15 lines is 485 lines of wasted tokens.

This is how the framework scales to large vaults without a database.
