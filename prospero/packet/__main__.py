"""Command line: ``python3 -m prospero.packet build|decide|history|review``.

Every path is relative to the content folder (``--home`` or ``$PROSPERO_HOME``);
the tool reads and writes nothing else.

  build   ORIGINAL EDITION SPEC.json --stem NAME [--parent PACKET.json]
          write NAME.packet.json/.md under packets/; --parent makes it a revision
  decide  PACKET.json accept|reject|revise --by WHO [--note TEXT]   append to decisions.jsonl
  history ORIGINAL   show every packet for ORIGINAL, which revises which, and the decisions
  review  PACKET.json   write NAME.review.html beside it: both texts side by side, every
          change highlighted by label, unlabelled differences marked (decides nothing)

``build`` exits 1 when a check fails (the packet is still written, so the
problems can be read); ``decide`` exits 1 when the decision is refused;
``history`` exits 1 when anything recorded is broken (it still prints);
``review`` exits 1 when the packet failed a check or its original has changed
(the sheet is still written, so the problems can be seen).
"""

from __future__ import annotations

import argparse
import json
import sys

from .build import build_packet, sha256
from .lineage import LineageError, history, parent_ref, render_history
from .review import original_status, write_review
from .record import DECISIONS, RecordError, record_decision, write_packet
from .sources import FolderSource, SourceError, content_home


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m prospero.packet", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", help="content folder (default: $PROSPERO_HOME)")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build an editorial packet")
    b.add_argument("original")
    b.add_argument("edition")
    b.add_argument("spec")
    b.add_argument("--stem", required=True, help="file name stem for the packet")
    b.add_argument("--parent", help="the packet this one revises (path under the content folder)")
    d = sub.add_parser("decide", help="record accept, reject or revise")
    d.add_argument("packet")
    d.add_argument("decision", choices=DECISIONS)
    d.add_argument("--by", required=True)
    d.add_argument("--note", default="")
    h = sub.add_parser("history", help="packets, revisions and decisions for one original")
    h.add_argument("original")
    r = sub.add_parser("review", help="write a side-by-side HTML review sheet for a packet")
    r.add_argument("packet")
    args = parser.parse_args(argv)

    try:
        home = content_home(args.home)
        source = FolderSource(home)
        if args.command == "build":
            spec = json.loads(source.read(args.spec))
            # One spelling per original, so history finds every packet for it.
            original = source.canonical(args.original)
            parent = parent_ref(source, args.parent, original) if args.parent else None
            packet = build_packet(source, original, args.edition, spec, parent=parent)
            json_path, md_path = write_packet(packet, home / "packets", args.stem)
            print(f"wrote {json_path.name} and {md_path.name}; checks {'passed' if packet.ok else 'FAILED'}")
            for check in packet.checks:
                for problem in check.problems:
                    print(f"  {check.name}: {problem}")
            return 0 if packet.ok else 1
        if args.command == "history":
            result = history(source, args.original)
            print(render_history(result), end="")
            return 0 if result.ok else 1
        if args.command == "review":
            # The sheet lands beside the packet; path_of keeps it in the content folder.
            packet_path = source.path_of(args.packet)
            packet_text = source.read(args.packet)
            path = write_review(packet_text, source.canonical(args.packet), packet_path.parent, source)
            packet = json.loads(packet_text)
            fresh, status = original_status(packet, source)
            print(f"wrote {path.name}; checks {'passed' if packet.get('ok') else 'FAILED'}; {status}")
            return 0 if packet.get("ok") and fresh else 1
        packet_text = source.read(args.packet)
        packet_dict = json.loads(packet_text)
        entry = record_decision(home, packet_dict, source, args.decision, args.by, args.note,
                                packet_name=args.packet, packet_sha256=sha256(packet_text))
        print(f"recorded {entry['decision']} by {entry['by']} at {entry['at']}")
        return 0
    except (SourceError, RecordError, LineageError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
