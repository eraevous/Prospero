# .aec: purpose and justification records (Telosmith, formerly AEC: requirements traceability)

- `records.jsonl`: append-only reasoning records (purpose, requirements, claims, evidence, decisions,
  authorities). Never edit a line; append a new version. Vocabulary:
  https://github.com/eraevous/Telosmith/blob/main/docs/reasoning-vocabulary.md
- `edges.jsonl`: the structural snapshot of the code (`aec edges`). Generated, so it is git-ignored
  (`.aec/.gitignore`): regenerate it rather than committing or hand-editing it.
- `snippets/`: what Telosmith's `aec init` wrote, kept for reference. Nothing reads it, and neither file
  should be copied into place here:
  - `aec-ci.yml` is superseded. The shared `kairos` workflow (`.github/workflows/kairos.yml`, from
    eraevous/Lydian) runs the same records check and the report-only code-impact (DEC-256, Prospero#21).
  - `claude-settings.json` is an older copy of the hook already active in `.claude/settings.json`, which
    adds symlink and `PYTHONPATH` guards. Copying the snippet over it would remove them.

Start by replacing the purpose stub `P0` with a new version stating what this project is for, in your
own words (`"version": 2`, `"epistemic": "provisional"` while you are still discovering it,
`"committed"` once changes to it should need your authorization).

All Telosmith results are structural: they show what changed and what relied on it, not whether the
remaining evidence is good enough. That stays a review question.
