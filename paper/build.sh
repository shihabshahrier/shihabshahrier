#!/usr/bin/env bash
# Typesets paper/main.tex and writes assets/title.svg, the header of the profile.
# pdflatex sets the type, pdftocairo turns the page into glyph outlines, and animate.py gives the
# outlines their theme colours and the order in which they appear.
# Needs pdflatex, pdftocairo (poppler) and python3. The README never depends on this running:
# the SVG is committed, and every fact on the page is also plain text in README.md.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .build ../assets
pdflatex -interaction=nonstopmode -halt-on-error -output-directory .build -jobname title main.tex > .build/title.log
pdftocairo -svg .build/title.pdf .build/title.svg
python3 animate.py
