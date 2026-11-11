#!/bin/sh
# Build the VAA + Trivy scan report as Markdown and PDF.
#
#   scripts/build-security-report.sh [SCAN_DATE] [OUT_DIR]
#
# SCAN_DATE selects docs/security/scans/<SCAN_DATE> (default: the newest one).
# The PDF is rendered by pandoc in a throwaway container (a pinned tool image; it is
# not part of the stack). Set DOCKER="sudo docker" if docker needs sudo.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCANS_ROOT="$ROOT/docs/security/scans"
DATE=${1:-$(ls "$SCANS_ROOT" | sort | tail -1)}
OUT=${2:-"$ROOT/build/security"}
DOCKER=${DOCKER:-docker}
PANDOC_IMAGE="pandoc/latex@sha256:dd0dd153f681ec264094c04011e34459e8de61fe95712020ab4dfbff1117b015" # pandoc/latex:3.8

mkdir -p "$OUT"
MD="$OUT/vaa-$DATE.md"
python3 "$ROOT/scripts/security_report.py" \
    --scans "$SCANS_ROOT/$DATE" --vaa "$ROOT/docs/security/vaa" \
    --intro "$ROOT/docs/security/vaa-intro.md" --latex --out "$MD"
echo "markdown: $MD"

$DOCKER run --rm --network none --user "$(id -u):$(id -g)" \
    -v "$OUT":/data -w /data "$PANDOC_IMAGE" \
    "vaa-$DATE.md" -o "vaa-$DATE.pdf" \
    --toc --toc-depth=2 -V geometry:a4paper,margin=18mm -V fontsize=10pt \
    -V colorlinks=true -V linkcolor=blue -V urlcolor=blue
echo "pdf: $OUT/vaa-$DATE.pdf"
