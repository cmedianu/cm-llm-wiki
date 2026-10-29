# Brief mode

Use when the user wants something to **send** (a briefing note for a board or committee, a memo, a status
note for other people), not a wiki page for later. Triggers: "write a brief", "something I can send
to the committee", "make it a PDF", "keep it short so they read it".

## Shape

- **One page.** Executive summary first: the decision or ask in two or three sentences.
  Then point-form facts, each verifiable against a source page or document. Then the
  recommendation. Math and detail go in an appendix section, not the body.
- **Readers' voice.** Write for the audience named by the vault's CLAUDE.md (for example
  third person, roles not names). No first person unless the user asks.
- **Verified only.** Every figure and claim traces to a page, a thread or a document; cite
  them with wikilinks (the vault keeps the trail even if the PDF drops links).

## File and render

1. Write it as a normal page with `wiki-new.py <briefs folder>/<yyyy-MM-dd>-<topic> --title ... --summary ...`
   (use the vault's briefs folder; ask once if none exists).
2. Render: `md2pdf <page>.md` next to the page. Leave a blank line between a paragraph and a
   following list, and avoid em-dashes (they break the PDF toolchain's layout).
3. Check the length before showing it: `pdfinfo <page>.pdf | grep Pages`. More than one page
   (plus appendix): cut, do not shrink the font.
4. Give the user the Windows path (`wslpath -w <page>.pdf`) so they can open or attach it.
