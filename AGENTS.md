# AGENTS.md: rules for agents (and people) working in this repository

## Who decides

- **Product direction, scope and purpose come from Zach** (the project's owner). Agents build what has been agreed
  with him and recorded in a handoff (the task record one agent hands to another) or a decision (an entry in Kairos's
  decision log, cited as DEC-n, which works like an architecture decision record, ADR). Anything else an agent suggests is a **proposal, not direction**:
  write it up (pull request description, issue, or a proposed decision) and let Zach decide.
- The purpose record `P0` in `.aec/records.jsonl` is a stub until Zach states the purpose in his own words.
  Do not fill it in for him.
- Never merge, never force-push. A pull request stays a draft only while it is being worked on; mark it ready
  for review once the work is done and CI is green (DEC-220).

## How code is written

- **Standard library first.** Do not add a third-party dependency without a recorded decision.
- **Parsimony and modularity.** Small modules with one job each; no new subsystem without a dissent review
  (an effective-challenge review of the plan: what purpose it might violate, the evidence for and against, what follows, what to test).
- **Commented for human readers.** Explain why, not only what. A reader who is not a programmer should be able
  to follow what each module is for.
- Every change keeps `python3 -m unittest discover -s tests` passing and `aec check` clean.

## What never enters this repository

- **Nothing personal or employer-related**: no personal details, no private conversations, no work material.
- **None of Zach's own works or corpora** (DEC-183, clarified by DEC-184): no writing, drafts, manuscripts,
  articles, books, notes, or personal or writing corpora of his. They are not public yet. They live outside the
  repository and reach Prospero through sockets (DEC-177: an adapter or MCP information-in resource onto storage
  such as the content folder), never by being committed, used as fixtures or quoted here.
- **Public-domain works are allowed** (DEC-184), for example as fixtures, examples or test text. Say where the
  text comes from and why it is in the public domain.
- **Third-party works still under copyright stay out by default** (Zach has not addressed them; ask first).
- Tests and examples otherwise use invented synthetic text written for the test.
- No secrets, tokens or credentials.

## Purpose records (Telosmith, requirements traceability)

`.aec/records.jsonl` is append-only: add a new version of a record instead of editing a line. Before you finish
a change:

```bash
python3 -m aec edges . -o .aec/edges.jsonl
python3 -m aec check .aec/records.jsonl --edges .aec/edges.jsonl
```

`.claude/settings.json` runs the same check after every edit made by Claude Code. In CI the shared `kairos`
workflow (`.github/workflows/kairos.yml`, from eraevous/Lydian; DEC-256) runs it on every pull request and every
push to `main`.
