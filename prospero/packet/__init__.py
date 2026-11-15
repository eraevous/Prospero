"""Editorial packets: an original, a proposed edition, and the checks between them.

See ``build.py`` for what a packet is and what it checks, ``sources.py`` for
how texts are read (the information-in socket), ``record.py`` for writing
packets and decisions into the content folder, and ``manifest.json`` for the
sockets this tool declares (DEC-177). Run ``python3 -m prospero.packet --help``.
"""

from .build import KINDS, Check, Packet, build_packet
from .record import DECISIONS, RecordError, record_decision, render_markdown, write_packet
from .sources import FolderSource, Source, SourceError, content_home

__all__ = [
    "KINDS", "Check", "Packet", "build_packet",
    "DECISIONS", "RecordError", "record_decision", "render_markdown", "write_packet",
    "FolderSource", "Source", "SourceError", "content_home",
]
