# Multimodal Sources (images)

Images (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) are first-class sources — screenshots, whiteboard
photos, diagrams, slide captures. **A vision-capable model is required.** Read them with the Read
tool, which renders the image into context; if your model doesn't support vision, skip image sources
and tell the user which files were skipped so they can re-run with a vision-capable model.

When the source is an image, your extraction job is interpretive — you're reading visual content, not
text. Walk the image methodically:

1. **Transcribe** any visible text verbatim (UI labels, slide bullets, whiteboard handwriting, code
   snippets in screenshots). This is the only *extracted* content from an image.
2. **Describe structure** — for diagrams, list the boxes/nodes and the arrows/edges. For screenshots,
   name the app or context if recognizable.
3. **Extract concepts** — what is the image *about*? What ideas, entities, or relationships does it
   convey? Most of this is `^[inferred]`.
4. **Note ambiguity** — handwriting you can't read, arrows whose direction is unclear, cropped
   content. Use `^[ambiguous]` and call it out.

Vision is interpretive by nature, so image-derived pages will skew heavily toward `^[inferred]`.
That's expected — the provenance markers exist precisely to surface this. Don't pretend an image's
"meaning" was extracted when you really inferred it.

For PDFs that are mostly images (scanned docs, slide decks exported to PDF), use `Read pages: "N"` to
pull specific pages and treat each page as an image source.
