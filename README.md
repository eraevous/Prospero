# Prospero

**Status:** activated 2026-11-09. First increment: the editorial-packet mechanics (`prospero/packet/`), tested on
invented text only. Running it on Zach's own writing (the pilot) is his call and happens outside this repository.

## What it is for

Zach has not yet stated the purpose in his own words. When he does, it becomes the purpose record `P0` in
`.aec/records.jsonl` (a stub until then). Until then, only these facts are adopted:

- Prospero is the name of the creative-collaboration tool formerly called PlayWrite (decision DEC-128, 2026-11-05).
  *Ariel* is reserved for its agent layer, if that layer is ever named separately (same decision).
- Development was activated on 2026-11-09 (DEC-182).
- This repository holds the mechanics (code, docs, tests). Zach's own works and corpora stay out; they reach the tool
  through sockets onto storage outside the repo. Public-domain works are allowed, for example as test text
  (DEC-183, clarified by DEC-184).

### Ideas on record, not requirements

Recorded in intake notes (paraphrased, not verbatim) while the idea was being explored. They are context for
discussion with Zach, not product requirements, and nothing here should be built from them alone:

- Zach: a tool to write and publish articles and books with an agent network that keeps his decisions and preferences.
- Zach: later versions remixed by professional artists (bonsai pruning, a classroom, a tutor, an exercise generator).
- Zach: the papers that define Cognitive Augmentation are to be written with it.
- Kate (an assistant in the project, not Zach): "cognitive augmentation for artists", not replacement.

## Editorial packets (first increment)

An editorial packet puts an original text beside a proposed alternate edition, so a change can be accepted,
rejected or revised without losing the original. The tool checks that:

- the original is unchanged (its SHA-256 is recorded and re-checked before any decision);
- every quotation in the edition is declared and appears word for word in its source, with a locator;
- every difference is a declared change labelled `agent addition`, `transformation` or `interpretation`, with a rationale;
- an interpretation never appears inside quotation marks.

Texts are read from a content folder outside the repository (`--home` or `$PROSPERO_HOME`; there is no default), and
packets and decisions are written there too. The tool refuses to write inside this repository.

```bash
python3 -m prospero.packet --home ~/prospero-content build original.md edition.md spec.json --stem first
python3 -m prospero.packet --home ~/prospero-content decide packets/first.packet.json reject --by zach --note "keep the original"
```

`spec.json` lists the changes and quotations; its format is described at the top of
[prospero/packet/build.py](prospero/packet/build.py), and [tests/test_packet.py](tests/test_packet.py) has worked
examples. The tool's sockets (DEC-177) are declared in [prospero/packet/manifest.json](prospero/packet/manifest.json).

## Name

PlayWrite → Prospero (DEC-128). Zach authorized renaming the repository to Prospero (DEC-183); until that is
done the repository is still called `PlayWrite`.

## Working here

- Read [AGENTS.md](AGENTS.md) before changing anything, whether you are a person or an agent.
- Tests: `python3 -m unittest discover -s tests -v` (standard library only, Python 3.10+).
- Purpose records: `.aec/` ([Telosmith](https://github.com/eraevous/Telosmith)). CI runs `aec check` on every push.

## Licence and contributions

MIT, see [LICENSE](LICENSE). Contributions are accepted under the [Contributor License Agreement](CLA.md).
