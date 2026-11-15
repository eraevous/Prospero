"""Command line: ``python3 -m prospero.packet build|decide``.

Every path is relative to the content folder (``--home`` or ``$PROSPERO_HOME``);
the tool reads and writes nothing else.

  build  ORIGINAL EDITION SPEC.json --stem NAME   write NAME.packet.json/.md under packets/
  decide PACKET.json accept|reject|revise --by WHO [--note TEXT]   append to decisions.jsonl

``build`` exits 1 when a check fails (the packet is still written, so the
problems can be read); ``decide`` exits 1 when the decision is refused.
"""

from __future__ import annotations

import argparse
import json
import sys

from .build import build_packet
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
    d = sub.add_parser("decide", help="record accept, reject or revise")
    d.add_argument("packet")
    d.add_argument("decision", choices=DECISIONS)
    d.add_argument("--by", required=True)
    d.add_argument("--note", default="")
    args = parser.parse_args(argv)

    try:
        home = content_home(args.home)
        source = FolderSource(home)
        if args.command == "build":
            spec = json.loads(source.read(args.spec))
            packet = build_packet(source, args.original, args.edition, spec)
            json_path, md_path = write_packet(packet, home / "packets", args.stem)
            print(f"wrote {json_path.name} and {md_path.name}; checks {'passed' if packet.ok else 'FAILED'}")
            for check in packet.checks:
                for problem in check.problems:
                    print(f"  {check.name}: {problem}")
            return 0 if packet.ok else 1
        packet_dict = json.loads(source.read(args.packet))
        entry = record_decision(home, packet_dict, source, args.decision, args.by, args.note)
        print(f"recorded {entry['decision']} by {entry['by']} at {entry['at']}")
        return 0
    except (SourceError, RecordError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
