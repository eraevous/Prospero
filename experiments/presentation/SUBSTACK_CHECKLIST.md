# Substack paste check (manual step for Zach; HO-PRO-20261118-FMYG, DEC-253)

Substack has no posting API and takes no custom CSS (Observatory packet 05), so the route is: open the
body-only HTML in a browser, select all, copy, and paste into a **new, unpublished** Substack draft.
Nothing here publishes anything; delete the draft afterwards.

Files to paste (body only, no stylesheet; Substack applies its own typography):

- `out/arm_b/synthetic-essay.substack.html`: headings, numbered list, block quote, inline code, two footnotes, image with alt text, link
- `out/arm_b/synthetic-notes.substack.html`: H1/H3/H4, bullet list, table, inline code, one footnote, image with alt text
- `out/arm_b/gettysburg.substack.html`: long paragraphs, italic sign-off (public-domain text)

Images: the pages refer to `lamp.svg` and `fog.svg` in `inputs/`; open the HTML from a folder that has them,
or expect Substack to drop or re-upload them (that itself is a result worth recording).

Record one row per item (Y = survived as written, P = partly, N = lost):

| Item | essay | notes | gettysburg | What happened |
|---|---|---|---|---|
| Headings keep their levels (H1, H2, H3, H4) | | | — | |
| Paragraph breaks | | | | |
| Italic / emphasis | | | | |
| Numbered and bullet lists | | | — | |
| Block quote | | — | — | |
| Inline code (`TOTAL`, `vis=40m;wind=calm`) | | | — | |
| Footnotes: markers and note text both present | | | — | |
| Footnotes: marker links to its note | | | — | |
| Image appears | | | — | |
| Image alt text kept (check in Substack's image settings) | | | — | |
| Link text and target (`example.org/library`) | | — | — | |
| Table | — | | — | |
| Straight quotes and `--` kept as typed, or converted by Substack | | | | |
| Anything added (extra spacing, captions, stray characters) | | | | |
