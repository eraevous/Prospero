#!/bin/sh
# Arm B: Markdown -> Pandoc -> HTML with the house CSS (HO-PRO-20261118-FMYG, DEC-253).
# Usage: arm_b/build.sh <input.md> <out_dir>
# Pinned: the experiment ran pandoc 3.1.3; the script refuses another version so results stay comparable.
# `-smart` turns off pandoc's typographic rewriting of quotes, dashes and ellipses: the words stay as written.
set -eu
want="pandoc 3.1.3"
have=$(pandoc --version | head -n 1)
[ "$have" = "$want" ] || { echo "arm_b: need $want, found $have" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
in=$1; out=$2; name=$(basename "$in" .md)
mkdir -p "$out"
# Full page for the web essay, CSS embedded so the page is one self-contained file.
pandoc --from=markdown-smart --to=html5 --standalone --embed-resources \
  --css="$here/house.css" --resource-path="$(dirname "$in")" \
  --output="$out/$name.html" "$in"
# Body only, no CSS, for pasting into Substack's editor (Substack applies its own typography).
pandoc --from=markdown-smart --to=html5 --output="$out/$name.substack.html" "$in"
