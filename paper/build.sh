#!/usr/bin/env bash
# Typesets paper/main.tex twice (light and dark ink) and writes assets/title-{light,dark}.svg.
# Needs pdflatex and pdftocairo (poppler). The README never depends on this running: the two
# SVGs are committed, and every fact on the page is also plain text in README.md.
set -euo pipefail
cd "$(dirname "$0")"
out=../assets
mkdir -p "$out" .build
build() { # name ink accent muted
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory .build -jobname "title-$1" \
    "\def\inkhex{$2}\def\accenthex{$3}\def\mutedhex{$4}\input{main.tex}" > .build/"$1".log
  pdftocairo -svg .build/"title-$1".pdf "$out/title-$1.svg"
}
build light 1F2328 6D28D9 59636E
build dark  E6EDF3 A78BFA 9198A1
ls -la "$out"/title-*.svg
