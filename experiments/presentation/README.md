# Presentation-first experiment (HO-PRO-20261118-FMYG, DEC-253)

Author: claude:prospero#wake-20261119-00 · Reviewer: none yet · model=claude-opus-5-5 (configured; serving model may differ)

A labelled experiment under DEC-200's build gate: presentation only, no prose changes. Quarto, Pandoc and a
browser are **external tools for the experiment**, not project dependencies (nothing here is imported by
`prospero/`).

## Layout

| Path | What |
|---|---|
| `inputs/` | 2 synthetic documents written for the test + 1 public-domain text (Lincoln, 1863), per DEC-184 |
| `arm_b/build.sh`, `arm_b/house.css` | Arm B: Markdown → pandoc 3.1.3 (`markdown-smart`) → HTML + house CSS |
| `out/arm_b/` | Arm B output: full self-contained pages and body-only `*.substack.html` |
| `render_check.py` | Fails on any character difference between the source and the rendered text (whitespace ignored) |
| `fixtures/` | A tiny invented source and the AST pandoc 3.1.3 wrote for it, so the unit tests run without pandoc |
| `screenshots/` | Arm B at phone (390 px) and desktop (1280 px), light, plus dark mode for one essay |
| `SUBSTACK_CHECKLIST.md` | The manual paste step for Zach, with a table to record what survived |

## Status

- **Arm B: done.** Render check passes on all 6 outputs (3 pages, 3 Substack bodies). Negative control:
  pandoc with smart punctuation *on* fails the check (curly quote at character 13 of the body and notes),
  so the check sees the rewriting it is meant to catch. Tests: `tests/test_presentation_render_check.py`.
- **Arm A (Quarto): not run yet.** This wake's attempt to download Quarto 1.6.42 from GitHub releases was refused
  by the session's permission check, so no Quarto output exists. Quarto is not otherwise installed here.
- **Substack: prepared, waiting on Zach** (`SUBSTACK_CHECKLIST.md`).

## Arm B results

**Output quality** (screenshots): 18 px body at default zoom; measure 62ch ≈ 71 lowercase letters per desktop
line (inside 60–75); ≈ 40 letters on a 390 px phone; no horizontal scroll at either width; dark mode follows the OS.
Footnotes are end-of-document notes with back-links (the handoff allowed this instead of sidenotes).
`text-wrap: pretty` and `hyphens: auto` are on; hyphenation is visible in the phone block quote.

**Text fidelity:** PASS, all outputs. With smart punctuation off, what the author typed is what the reader
sees: `--`, `---`, `...` and straight quotes stay as typed. That is the asked-for behaviour, and it moves a
choice onto the author: typographic dashes and quotes appear only if typed as such in the source.

**Author effort:** one command per document (`arm_b/build.sh in.md out/`); 1 pandoc invocation per output,
build script 20 lines, stylesheet ~45 lines; dependencies: the pandoc binary only (pinned, the script refuses
another version).

## Recommendation (provisional, one arm)

None yet: the comparison is the point, and Arm A is missing. Arm B meets every presentation target in the
handoff with one external binary and no template. The open question Arm A answers is whether a mature theme
looks better enough to justify Quarto's size (a bundled pandoc, Deno and Dart Sass) — attractiveness, which
determinism doesn't establish (API Kate's review: the ChatGPT API reviewer, an independent review by a different model family).
