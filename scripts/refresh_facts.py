#!/usr/bin/env python3
"""Refresh the LetX figures in README.md from LetX's own public statistics.

README.md keeps each figure between a pair of HTML comments, for example
    <!--letx:users-->11,300+<!--/letx:users-->
This script reads https://api.letx.app/api/v1/public/stats, rounds each count DOWN the way
letx.app/stats does (users to 100, institutions to 10, countries to 5, templates to 100) and
rewrites what is between the comments. Standard library only, no token.

Three rules, the same ones LetX's own build follows:
  * a figure never goes down: a lower count means the count went wrong, not that people left;
  * a failed or malformed read changes nothing and exits 0, so a bad night never blanks the page;
  * the date in the footnote moves only when a figure moved.
"""
import datetime
import json
import pathlib
import re
import sys
import urllib.request

API = "https://api.letx.app/api/v1/public/stats"
README = pathlib.Path(__file__).resolve().parent.parent / "README.md"
STEPS = {"users": 100, "institutions": 10, "countries": 5, "templates": 100}


def marker(key: str) -> re.Pattern:
    return re.compile(rf"(<!--letx:{key}-->)(.*?)(<!--/letx:{key}-->)", re.S)


def as_int(text: str) -> int:
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else 0


def main() -> int:
    try:
        req = urllib.request.Request(API, headers={"User-Agent": "profile-readme-refresh"})
        with urllib.request.urlopen(req, timeout=20) as res:
            stats = json.load(res)
        counts = {k: int(stats[k]) for k in STEPS}
    except Exception as err:  # network, JSON, a missing key: leave the page as it is
        print(f"could not read the statistics ({type(err).__name__}); README left unchanged")
        return 0

    text = README.read_text(encoding="utf-8")
    changed = False
    for key, step in STEPS.items():
        pat = marker(key)
        found = pat.search(text)
        if not found:
            print(f"no marker for {key}; skipped")
            continue
        old = as_int(found.group(2))
        new = (counts[key] // step) * step
        if new > old:
            text = pat.sub(lambda m, n=new: f"{m.group(1)}{n:,}+{m.group(3)}", text)
            print(f"{key}: {old:,}+ -> {new:,}+")
            changed = True
        elif new < old:
            print(f"{key}: live floor {new:,} is below the published {old:,}; kept {old:,}")

    if changed:
        today = datetime.datetime.now(datetime.timezone.utc)
        stamp = f"{today.day} {today.strftime('%B %Y')}"
        text = marker("date").sub(lambda m: f"{m.group(1)}{stamp}{m.group(3)}", text)
        README.write_text(text, encoding="utf-8")
        print(f"README updated, dated {stamp}")
    else:
        print("no figure moved; README unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
