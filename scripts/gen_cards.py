#!/usr/bin/env python3
"""Generate the retro-CRT profile cards for the GitHub profile README.

Every card is rendered locally into a static SVG under assets/, so the README
never depends on a third-party card service. (When this was written the popular
ones were all down: github-readme-stats returned 503 DEPLOYMENT_PAUSED,
github-profile-trophy 402, pixel-profile 504.)

The cards animate on load: the portrait paints itself scanline by scanline, the
contribution grid sweeps in, the language bars fill. All of it is SMIL inside
the SVG rather than CSS keyframes, because these files are consumed as <img>
sources. See reveal() for why that distinction decides whether the card renders
at all in a viewer that doesn't animate.

Usage:
    python scripts/gen_cards.py [--out assets] [--no-private]

Only the standard library is needed — the portrait comes from
assets/avatar-grid.json, produced separately by scripts/gen_avatar.py.
Auth: GITHUB_TOKEN / GH_TOKEN, falling back to `gh auth token`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pixelfont import fit_scale, text_height, text_pixels, text_width  # noqa: E402

USER = "shihabshahrier"
API = "https://api.github.com/graphql"

# ---------------------------------------------------------------- palette ----
BG = "#05080d"
BEZEL_A = "#1c222c"
BEZEL_B = "#0b0f16"
CYAN = "#00D9FF"
CYAN_DIM = "#0a7d94"
WHITE = "#E6F7FF"
MUTED = "#4a6a78"
GRID = "#0d2530"

HERO_W, HERO_H = 880, 350
CARD_W, CARD_H = 428, 292
CONTRIB_W, CONTRIB_H = 880, 212
AVATAR_PX = 3  # SVG units per portrait cell

# Monochrome phosphor ramp for the portrait — the picture is rendered the way a
# single-colour CRT terminal would show it, in the same cyan as everything else.
# Control points are (position, RGB); levels in between are interpolated.
PHOSPHOR = [
    (0.00, (5, 22, 31)),
    (0.22, (10, 58, 76)),
    (0.45, (14, 116, 143)),
    (0.68, (0, 173, 208)),
    (0.88, (0, 209, 245)),
    (1.00, (128, 236, 255)),
]


def phosphor_ramp(levels):
    """Expand PHOSPHOR into `levels` hex colours."""
    ramp = []
    for i in range(levels):
        t = i / (levels - 1) if levels > 1 else 1.0
        for (p0, c0), (p1, c1) in zip(PHOSPHOR, PHOSPHOR[1:]):
            if p0 <= t <= p1:
                k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
                ramp.append("#%02x%02x%02x" % tuple(
                    round(a + (b - a) * k) for a, b in zip(c0, c1)))
                break
        else:
            ramp.append("#%02x%02x%02x" % PHOSPHOR[-1][1])
    return ramp

# Markup and stylesheets are mostly generated or vendored, and at these volumes
# they bury the languages actually being written. Override with --keep-markup.
NOISE_LANGS = {"HTML", "CSS", "SCSS", "Less", "Sass", "Stylus"}


# ------------------------------------------------------------------ data ----
def token():
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(env):
            return os.environ[env]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True,
                             text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    raise SystemExit("No GitHub token: set GITHUB_TOKEN or run `gh auth login`.")


def gql(query, variables, tok):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {tok}",
        "Content-Type": "application/json",
        "User-Agent": "profile-card-generator",
    })
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


PROFILE_Q = """
query($login:String!){
  user(login:$login){
    name login createdAt location
    followers{ totalCount }
    pullRequests{ totalCount }
    repositories(ownerAffiliations:OWNER){ totalCount }
  }
}
"""

YEAR_Q = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from,to:$to){
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      contributionCalendar{
        totalContributions
        weeks{ contributionDays{ date contributionCount } }
      }
    }
  }
}
"""

REPO_Q = """
query($login:String!,$cursor:String,$privacy:RepositoryPrivacy){
  user(login:$login){
    repositories(first:100, after:$cursor, ownerAffiliations:OWNER,
                 isFork:false, privacy:$privacy){
      pageInfo{ hasNextPage endCursor }
      nodes{
        stargazerCount
        languages(first:10, orderBy:{field:SIZE,direction:DESC}){
          edges{ size node{ name color } }
        }
      }
    }
  }
}
"""


def collect(tok, include_private):
    prof = gql(PROFILE_Q, {"login": USER}, tok)["user"]
    created = dt.datetime.fromisoformat(prof["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)

    days, commits, prs, year_contribs = {}, 0, 0, 0
    for year in range(created.year, now.year + 1):
        start = max(created, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        if start >= end:
            continue
        block = gql(YEAR_Q, {
            "login": USER,
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": end.isoformat().replace("+00:00", "Z"),
        }, tok)["user"]["contributionsCollection"]
        commits += block["totalCommitContributions"] + block["restrictedContributionsCount"]
        prs += block["totalPullRequestContributions"]
        for week in block["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
        if year == now.year:
            year_contribs = block["contributionCalendar"]["totalContributions"]

    langs, lang_color, stars = Counter(), {}, 0
    for privacy in ([None] if include_private else ["PUBLIC"]):
        cursor = None
        while True:
            page = gql(REPO_Q, {"login": USER, "cursor": cursor,
                                "privacy": privacy}, tok)["user"]["repositories"]
            for repo in page["nodes"]:
                stars += repo["stargazerCount"]
                for edge in repo["languages"]["edges"]:
                    name = edge["node"]["name"]
                    langs[name] += edge["size"]
                    lang_color[name] = edge["node"]["color"] or CYAN
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]

    current, best = streaks(days)
    return {
        "name": prof["name"] or prof["login"],
        "login": prof["login"],
        "location": prof["location"] or "",
        "since": created.year,
        "followers": prof["followers"]["totalCount"],
        "repos": prof["repositories"]["totalCount"],
        "prs": max(prof["pullRequests"]["totalCount"], prs),
        "stars": stars,
        "commits": commits,
        "contribs": sum(days.values()),
        "year_contribs": year_contribs,
        "streak": current,
        "best_streak": best,
        "days": days,
        "langs": dict(langs),
        "lang_color": lang_color,
        "generated": now.strftime("%Y-%m-%d"),
    }


def streaks(days):
    """Current and longest daily-contribution streak."""
    if not days:
        return 0, 0
    best = run = 0
    for date in sorted(days):
        run = run + 1 if days[date] > 0 else 0
        best = max(best, run)

    today = dt.date.today()
    cursor = today if days.get(today.isoformat(), 0) else today - dt.timedelta(days=1)
    current = 0
    while days.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= dt.timedelta(days=1)
    return current, best


# ------------------------------------------------------------------- svg ----
EASE = ".2 .8 .3 1"


def reveal(delay, dur=0.42, dy=0.0):
    """SMIL intro for one element: stay hidden, then fade (and drift) into place.

    Deliberately *not* CSS keyframes. An SVG used as <img> is rendered as an
    image document, and hiding elements with `animation-fill-mode: backwards`
    means any renderer that parses the CSS without running the animation shows a
    permanently blank card. SMIL degrades the other way: the static attributes
    on the element are already its final state, so if nothing animates, the card
    simply appears fully drawn.
    """
    if delay <= 0:
        times, splines = "0;1", EASE
        values_o, values_t = "0;1", f"0 {dy};0 0"
        total = dur
    else:
        total = delay + dur
        times = f"0;{delay / total:.4f};1"
        splines = f"0 0 1 1;{EASE}"
        values_o, values_t = "0;0;1", f"0 {dy};0 {dy};0 0"

    out = (f'<animate attributeName="opacity" values="{values_o}" keyTimes="{times}" '
           f'dur="{total:.2f}s" begin="0s" fill="freeze" calcMode="spline" '
           f'keySplines="{splines}"/>')
    if dy:
        out += (f'<animateTransform attributeName="transform" type="translate" '
                f'values="{values_t}" keyTimes="{times}" dur="{total:.2f}s" begin="0s" '
                f'fill="freeze" calcMode="spline" keySplines="{splines}"/>')
    return out


def px_text(text, x, y, scale, fill, delay=None, dy=0.0):
    rects = "".join(
        f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}"/>'
        for rx, ry, rw, rh in text_pixels(text, x, y, scale)
    )
    anim = reveal(delay, dy=dy) if delay is not None else ""
    return f'<g fill="{fill}">{anim}{rects}</g>'


def crt_defs(uid, width, height):
    return f"""<defs>
  <linearGradient id="bez{uid}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{BEZEL_A}"/><stop offset="1" stop-color="{BEZEL_B}"/>
  </linearGradient>
  <radialGradient id="vig{uid}" cx="50%" cy="45%" r="72%">
    <stop offset="55%" stop-color="#000" stop-opacity="0"/>
    <stop offset="100%" stop-color="#000" stop-opacity="0.62"/>
  </radialGradient>
  <linearGradient id="swg{uid}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{CYAN}" stop-opacity="0"/>
    <stop offset="50%" stop-color="{CYAN}" stop-opacity="0.10"/>
    <stop offset="1" stop-color="{CYAN}" stop-opacity="0"/>
  </linearGradient>
  <pattern id="scn{uid}" width="4" height="3" patternUnits="userSpaceOnUse">
    <rect width="4" height="1" fill="#000" opacity="0.34"/>
  </pattern>
  <filter id="glw{uid}" x="-35%" y="-35%" width="170%" height="170%">
    <feGaussianBlur stdDeviation="1.7" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <clipPath id="clp{uid}">
    <rect x="12" y="12" width="{width - 24}" height="{height - 24}" rx="13"/>
  </clipPath>
</defs>"""


def crt_open(uid, width, height, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
        + crt_defs(uid, width, height)
        + f'<rect width="{width}" height="{height}" rx="18" fill="url(#bez{uid})"/>'
        + f'<rect x="1.5" y="1.5" width="{width - 3}" height="{height - 3}" rx="17" '
          f'fill="none" stroke="#2b3542"/>'
        + f'<rect x="12" y="12" width="{width - 24}" height="{height - 24}" rx="13" fill="{BG}"/>'
        + f'<g clip-path="url(#clp{uid})">'
    )


def crt_close(uid, width, height):
    """Scanlines, vignette, and the phosphor sweep that loops forever.

    The sweep starts at opacity 0 so a renderer without SMIL never shows a stray
    band parked across the card.
    """
    inner = width - 24
    travel = height + 100
    return (
        f'<rect x="12" y="12" width="{inner}" height="{height - 24}" fill="url(#scn{uid})"/>'
        f'<rect x="12" y="12" width="{inner}" height="{height - 24}" fill="url(#vig{uid})"/>'
        f'<rect x="12" y="-80" width="{inner}" height="80" fill="url(#swg{uid})" opacity="0">'
        f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.02;0.98;1" '
        f'dur="7.5s" begin="2.4s" repeatCount="indefinite"/>'
        f'<animateTransform attributeName="transform" type="translate" '
        f'values="0 0;0 {travel}" dur="7.5s" begin="2.4s" repeatCount="indefinite"/>'
        f'</rect>'
        f'</g>'
        f'<rect x="12.5" y="12.5" width="{inner - 1}" height="{height - 25}" rx="13" '
        f'fill="none" stroke="{CYAN}" stroke-opacity="0.22"/>'
        f'</svg>\n'
    )


def header_bar(uid, x, y, width, label, right="", delay=0.05):
    parts = [
        reveal(delay),
        f'<rect x="{x}" y="{y}" width="{width}" height="20" fill="{GRID}" opacity="0.55"/>',
        f'<rect x="{x}" y="{y}" width="3" height="20" fill="{CYAN}"/>',
        px_text(label, x + 10, y + 7, 1, CYAN),
    ]
    if right:
        parts.append(px_text(right, x + width - 10 - text_width(right, 1), y + 7, 1, MUTED))
    return "<g>" + "".join(parts) + "</g>"


def human(n):
    return f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 10000 else str(n)


# ---------------------------------------------------------------- portrait ---
def portrait(grid, ramp, ox, oy, cell=AVATAR_PX, base_delay=0.30, per_row=0.012):
    """One <g> per scanline row, each with its own delay, so the face paints in
    top to bottom.

    Cells hold brightness levels, not colours; they are mapped through the
    phosphor ramp here. Horizontal runs of the same level merge into one rect,
    which matters more now that the grid is monochrome — far more neighbours
    share a value, so the file stays small despite the higher resolution.
    """
    out = []
    for row_index, row in enumerate(grid):
        rects = []
        col = 0
        while col < len(row):
            level = row[col]
            run = 1
            while col + run < len(row) and row[col + run] == level:
                run += 1
            if level is not None:
                rects.append(
                    f'<rect x="{ox + col * cell}" y="{oy + row_index * cell}" '
                    f'width="{run * cell}" height="{cell}" fill="{ramp[level]}"/>'
                )
            col += run
        if rects:
            out.append("<g>" + reveal(base_delay + row_index * per_row, dur=0.3)
                       + "".join(rects) + "</g>")
    return "".join(out)


# ----------------------------------------------------------------- cards ----
def hero_card(data, grid, ramp):
    uid = "H"
    cells = len(grid)
    span = cells * AVATAR_PX
    ax, ay = 34, 52
    body = [crt_open(uid, HERO_W, HERO_H, f"{data['name']} — pixel profile card")]
    body.append(header_bar(uid, 12, 12, HERO_W - 24,
                           f"{data['login'].upper()}@GITHUB:~$ WHOAMI",
                           f"BUILD {data['generated']}"))

    # portrait, corner brackets, and the scan head that rides the reveal down
    body.append(portrait(grid, ramp, ax, ay))
    for cx_, cy_ in ((ax - 8, ay - 8), (ax + span - 4, ay - 8),
                     (ax - 8, ay + span - 4), (ax + span - 4, ay + span - 4)):
        body.append(f'<g>{reveal(0.2)}<rect x="{cx_}" y="{cy_}" width="12" height="12" '
                    f'fill="{CYAN}"/></g>')
    body.append(
        f'<rect x="{ax - 8}" y="{ay}" width="{span + 16}" height="3" fill="{CYAN}" opacity="0">'
        f'<animate attributeName="opacity" values="0;0;.85;.85;0" '
        f'keyTimes="0;0.12;0.2;0.92;1" dur="1.7s" begin="0s" fill="remove"/>'
        f'<animateTransform attributeName="transform" type="translate" '
        f'values="0 0;0 0;0 {span}" keyTimes="0;0.12;1" dur="1.7s" begin="0s" fill="remove"/>'
        f'</rect>'
    )
    handle = f"@{data['login']}"
    body.append(px_text(handle, ax + (span - text_width(handle, 2)) // 2,
                        ay + span + 14, 2, CYAN_DIM, 1.35, dy=4))

    # identity column
    cx = ax + span + 40
    avail = HERO_W - 12 - cx - 12
    y = ay + 4
    scale = fit_scale(data["name"], avail, 4, 2)
    body.append(f'<g filter="url(#glw{uid})">'
                + px_text(data["name"], cx, y, scale, WHITE, 0.45, dy=6) + "</g>")
    y += text_height(scale) + 14
    body.append(f'<g>{reveal(0.58, dy=6)}<rect x="{cx}" y="{y}" '
                f'width="{min(avail, 360)}" height="2" fill="{CYAN}" opacity="0.55"/></g>')
    y += 18

    lines = [
        ("AI ENGINEER * SYSTEM ARCHITECT", CYAN, 0.70),
        ("FOUNDER -- SHAHRIAR LABS", WHITE, 0.80),
        (f"{data['location'].upper()} * BUILDING SINCE {data['since']}", MUTED, 0.90),
    ]
    for text, color, delay in lines:
        s = fit_scale(text, avail, 2, 1)
        body.append(px_text(text, cx, y, s, color, delay, dy=6))
        y += text_height(s) + 10

    y += 14
    prompt = "> BUILDING WHAT DIDNT EXIST YESTERDAY"
    ps = fit_scale(prompt, avail - 20, 2, 1)
    body.append(px_text(prompt, cx, y, ps, CYAN, 1.05, dy=6))
    body.append(
        f'<rect x="{cx + text_width(prompt, ps) + 4 * ps}" y="{y}" width="{5 * ps}" '
        f'height="{text_height(ps)}" fill="{CYAN}">'
        f'<animate attributeName="opacity" values="1;0" keyTimes="0;0.5" dur="1.1s" '
        f'begin="0s" calcMode="discrete" repeatCount="indefinite"/></rect>'
    )

    # stat chips
    chips = [("COMMITS", human(data["commits"])), ("PULL REQ", human(data["prs"])),
             ("REPOS", human(data["repos"])), ("STARS", human(data["stars"])),
             ("STREAK", f"{data['streak']}D")]
    strip_y = HERO_H - 68
    body.append(f'<g>{reveal(1.2)}<rect x="{cx}" y="{strip_y - 16}" width="{avail}" '
                f'height="1" fill="{CYAN}" opacity="0.28"/></g>')
    chip_w = avail // len(chips)
    for i, (label, value) in enumerate(chips):
        bx = cx + i * chip_w
        delay = 1.25 + i * 0.08
        body.append(px_text(value, bx, strip_y, 3, CYAN, delay, dy=8))
        body.append(px_text(label, bx, strip_y + text_height(3) + 7, 1, MUTED,
                            delay + 0.05, dy=8))

    body.append(crt_close(uid, HERO_W, HERO_H))
    return "".join(body)


def stats_card(data):
    uid = "S"
    body = [crt_open(uid, CARD_W, CARD_H, "GitHub statistics")]
    body.append(header_bar(uid, 12, 12, CARD_W - 24, "SYS.STATS", "ALL TIME"))

    pad = 26
    col_w = (CARD_W - pad * 2 - 14) // 2
    cells = [("TOTAL COMMITS", human(data["commits"])),
             ("PULL REQUESTS", human(data["prs"])),
             ("REPOSITORIES", human(data["repos"])),
             ("STARS EARNED", human(data["stars"])),
             ("CONTRIB THIS YR", human(data["year_contribs"])),
             ("LONGEST STREAK", f"{data['best_streak']}D")]

    for i, (label, value) in enumerate(cells):
        x = pad + (i % 2) * (col_w + 14)
        y = 54 + (i // 2) * 62
        delay = 0.5 + i * 0.09
        scale = fit_scale(value, col_w - 20, 4, 2)
        body.append(
            f'<g>{reveal(delay, dy=8)}'
            f'<rect x="{x}" y="{y}" width="{col_w}" height="54" rx="3" fill="{GRID}" opacity="0.4"/>'
            f'<rect x="{x}" y="{y}" width="2" height="54" fill="{CYAN}" opacity="0.75"/>'
            f'<g filter="url(#glw{uid})">{px_text(value, x + 10, y + 9, scale, CYAN)}</g>'
            f'{px_text(label, x + 10, y + 15 + text_height(scale) + 3, 1, MUTED)}'
            f'</g>'
        )

    footer = f"CURRENT STREAK {data['streak']} DAYS * {data['followers']} FOLLOWERS"
    body.append(px_text(footer, pad, CARD_H - 32, 1, CYAN_DIM, 1.05, dy=4))
    body.append(crt_close(uid, CARD_W, CARD_H))
    return "".join(body)


def langs_card(data, top=6, keep_markup=False):
    uid = "L"
    body = [crt_open(uid, CARD_W, CARD_H, "Language distribution")]
    scope = "OWNED REPOS" if keep_markup else "CODE ONLY"
    body.append(header_bar(uid, 12, 12, CARD_W - 24, "LANG.BYTES", scope))

    langs = {k: v for k, v in data["langs"].items()
             if keep_markup or k not in NOISE_LANGS}
    ranked = sorted(langs.items(), key=lambda kv: -kv[1])[:top]
    total = sum(langs.values()) or 1
    pad, seg, gap = 26, 26, 2
    bar_w = CARD_W - pad * 2
    block_w = (bar_w - (seg - 1) * gap) / seg

    y = 54
    for bar_index, (name, size) in enumerate(ranked):
        share = size / total
        filled = max(1, round(share * seg))
        color = data["lang_color"].get(name, CYAN)
        pct = f"{share * 100:.1f}%"
        row_delay = 0.5 + bar_index * 0.10
        body.append(px_text(name[:14], pad, y, 1, WHITE, row_delay, dy=4))
        body.append(px_text(pct, pad + bar_w - text_width(pct, 1), y, 1, CYAN_DIM,
                            row_delay, dy=4))
        for i in range(seg):
            bx = pad + i * (block_w + gap)
            if i < filled:
                delay = row_delay + 0.06 + i * 0.022
                body.append(
                    f'<rect x="{bx:.1f}" y="{y + 12}" width="{block_w:.1f}" height="9" '
                    f'fill="{color}" opacity="1">{reveal(delay, dur=0.22)}</rect>'
                )
            else:
                body.append(f'<rect x="{bx:.1f}" y="{y + 12}" width="{block_w:.1f}" '
                            f'height="9" fill="{GRID}" opacity="0.75"/>')
        y += 34

    rest = len(langs) - len(ranked)
    other = 100 - sum(s for _, s in ranked) / total * 100
    body.append(px_text(f"+ {rest} MORE LANGUAGES * {other:.1f}%", pad, CARD_H - 32,
                        1, MUTED, 1.25, dy=4))
    body.append(crt_close(uid, CARD_W, CARD_H))
    return "".join(body)


def contrib_card(data, weeks=52):
    uid = "C"
    body = [crt_open(uid, CONTRIB_W, CONTRIB_H, "Contribution activity")]

    today = dt.date.today()
    start = today - dt.timedelta(days=weeks * 7 + ((today.weekday() + 1) % 7))
    cells, cursor = [], start
    while cursor <= today:
        cells.append((cursor, data["days"].get(cursor.isoformat(), 0)))
        cursor += dt.timedelta(days=1)

    peak = max((c for _, c in cells), default=1) or 1
    steps = [GRID, "#0b4d5e", "#0f8ba8", "#00b8db", CYAN]
    total = sum(c for _, c in cells)
    body.append(header_bar(uid, 12, 12, CONTRIB_W - 24, "CONTRIB.GRID -- 12 MONTHS",
                           f"{total} CONTRIBUTIONS"))

    size, gap, ox, oy = 12, 3, 26, 54
    columns = {}
    for day, count in cells:
        week = (day - start).days // 7
        weekday = (day.weekday() + 1) % 7  # Sunday-first, like GitHub
        level = 0 if count == 0 else min(4, 1 + int(count / peak * 3.999))
        columns.setdefault(week, []).append(
            f'<rect x="{ox + week * (size + gap)}" y="{oy + weekday * (size + gap)}" '
            f'width="{size}" height="{size}" rx="1.5" fill="{steps[level]}" '
            f'opacity="{0.5 if level == 0 else 1}"/>'
        )
    for week in sorted(columns):
        body.append("<g>" + reveal(0.32 + week * 0.016, dur=0.3)
                    + "".join(columns[week]) + "</g>")

    legend_y = oy + 7 * (size + gap) + 14
    legend = [px_text("LESS", ox, legend_y + 3, 1, MUTED)]
    for i, color in enumerate(steps):
        legend.append(f'<rect x="{ox + 34 + i * 13}" y="{legend_y}" width="10" height="10" '
                      f'rx="1.5" fill="{color}" opacity="{0.5 if i == 0 else 1}"/>')
    legend.append(px_text("MORE", ox + 34 + len(steps) * 13 + 6, legend_y + 3, 1, MUTED))
    right = f"PEAK {peak} IN A DAY * CURRENT STREAK {data['streak']}D"
    legend.append(px_text(right, CONTRIB_W - 26 - text_width(right, 1), legend_y + 3,
                          1, CYAN_DIM))
    body.append("<g>" + reveal(1.35, dy=4) + "".join(legend) + "</g>")

    body.append(crt_close(uid, CONTRIB_W, CONTRIB_H))
    return "".join(body)


# ------------------------------------------------------------------ main ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets")
    ap.add_argument("--avatar", default="assets/avatar-grid.json")
    ap.add_argument("--no-private", action="store_true",
                    help="exclude private repositories from the language card")
    ap.add_argument("--keep-markup", action="store_true",
                    help="count HTML/CSS/SCSS bytes in the language card")
    ap.add_argument("--cache", help="reuse a saved API payload instead of calling GitHub")
    args = ap.parse_args()

    data = None
    if args.cache and os.path.exists(args.cache):
        with open(args.cache) as fh:
            data = json.load(fh)
    if data is None:
        data = collect(token(), include_private=not args.no_private)
        if args.cache:
            with open(args.cache, "w") as fh:
                json.dump(data, fh)

    with open(args.avatar) as fh:
        avatar = json.load(fh)
    ramp = phosphor_ramp(avatar.get("levels", 16))

    os.makedirs(args.out, exist_ok=True)
    for name, svg in {
        "hero-card.svg": hero_card(data, avatar["grid"], ramp),
        "stats.svg": stats_card(data),
        "langs.svg": langs_card(data, keep_markup=args.keep_markup),
        "contrib.svg": contrib_card(data),
    }.items():
        path = os.path.join(args.out, name)
        with open(path, "w") as fh:
            fh.write(svg)
        print(f"wrote {path} ({len(svg) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
