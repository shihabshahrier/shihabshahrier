#!/usr/bin/env python3
"""Turn the typeset header (pdftocairo's SVG) into one themed, self-typesetting SVG.

In:  paper/.build/title.svg   glyph outlines placed by TeX, three flat colours
Out: assets/title.svg         the same glyphs, with
  * colours as CSS classes, so one file serves the light and the dark theme;
  * each glyph set in reading order, the way a compositor lays type: the name first and slowly,
    the rest of the block faster, then the rule, then the margin stamp;
  * a caret left blinking at the end of the last line.

Nothing moves for a reader who asked for reduced motion, and a renderer that ignores CSS animation
draws the finished block: the hidden state exists only inside the keyframes.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / ".build" / "title.svg"
OUT = HERE.parent / "assets" / "title.svg"

INK, MUTED, ACCENT = "ink", "muted", "accent"


def colour_class(fill: str) -> str:
    r, g, b = (float(v) for v in re.findall(r"([\d.]+)%", fill))
    if b > 60 and r < 60:
        return ACCENT
    return INK if r < 25 else MUTED


def main() -> None:
    svg = SRC.read_text(encoding="utf-8")
    head, body = svg.split("</defs>", 1)
    body = body.rsplit("</svg>", 1)[0]

    # Every glyph: (group colour, href, x, y), in document order.
    glyphs = []
    rules = []
    for group in re.finditer(r'<g fill="([^"]+)"[^>]*>(.*?)</g>', body, re.S):
        cls = colour_class(group.group(1))
        for use in re.finditer(r'<use xlink:href="(#[^"]+)" x="([-\d.]+)" y="([-\d.]+)"/>', group.group(2)):
            glyphs.append([cls, use.group(1), float(use.group(2)), float(use.group(3))])
    for path in re.finditer(r'<path[^>]*?fill="(rgb[^"]+)"[^>]*?d="([^"]+)"[^>]*/>', body, re.S):
        rules.append((colour_class(path.group(1)), path.group(2)))
    if not rules:  # cairo may write the rule as a stroked line
        for path in re.finditer(r'<path[^>]*?stroke="(rgb[^"]+)"[^>]*?d="([^"]+)"[^>]*/>', body, re.S):
            rules.append(("rule-stroke " + colour_class(path.group(1)), path.group(2), path.group(0)))

    stamp_x = min(g[2] for g in glyphs)
    stamp = [g for g in glyphs if abs(g[2] - stamp_x) < 0.01]
    block = [g for g in glyphs if abs(g[2] - stamp_x) >= 0.01]

    # Lines of the block: baselines closer than 2pt are one line (small caps and TeX's logo shift a little).
    block.sort(key=lambda g: (g[3], g[2]))
    lines, current = [], [block[0]]
    for g in block[1:]:
        if g[3] - current[-1][3] > 2.0:
            lines.append(current)
            current = [g]
        else:
            current.append(g)
    lines.append(current)
    for line in lines:
        line.sort(key=lambda g: g[2])

    # The schedule, in milliseconds.
    t = 250.0
    out = []
    for n, line in enumerate(lines):
        step = 42.0 if n == 0 else 7.0  # the name is set letter by letter, the rest runs
        for g in line:
            out.append((g, t))
            t += step
        t += 260.0 if n == 0 else 60.0
    typeset_end = t
    rule_at = 250.0 + len(lines[0]) * 42.0 + 120.0
    stamp_step = 16.0
    stamp_sorted = sorted(stamp, key=lambda g: -g[3])  # reads upward
    for i, g in enumerate(stamp_sorted):
        out.append((g, typeset_end + 150.0 + i * stamp_step))
    total = typeset_end + 150.0 + len(stamp_sorted) * stamp_step

    last = lines[-1][-1]
    caret_x, caret_y = last[2] + 5.6, last[3]

    width, height = re.search(r'width="([\d.]+)pt" height="([\d.]+)pt"', head).groups()
    css = f"""
.ink{{fill:#1F2328}}.muted{{fill:#59636E}}.accent{{fill:#6D28D9}}.line{{stroke:#6D28D9}}
@media (prefers-color-scheme:dark){{.ink{{fill:#E6EDF3}}.muted{{fill:#9198A1}}.accent{{fill:#A78BFA}}.line{{stroke:#A78BFA}}}}
use{{animation:set .32s cubic-bezier(.2,.8,.2,1) both}}
.rule{{transform-box:fill-box;transform-origin:center;animation:rule .7s cubic-bezier(.2,.8,.2,1) {rule_at:.0f}ms both}}
.caret{{animation:show .01s linear {total + 200:.0f}ms both,blink 1.1s steps(1,end) {total + 200:.0f}ms infinite}}
@keyframes set{{from{{opacity:0;transform:translateY(2.4px)}}}}
@keyframes rule{{from{{transform:scaleX(0)}}}}
@keyframes show{{from{{opacity:0}}}}
@keyframes blink{{50%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{use,.rule,.caret{{animation:none}}}}
"""
    parts = [head.replace(f'width="{width}pt" height="{height}pt"', f'width="{width}pt" height="{height}pt" role="img" aria-label="Shihab Shahriar Antor, AI Engineer and Founder, Shahriar Labs, Dhaka, Bangladesh"')]
    parts.append("<style>" + css.strip().replace("\n", "") + "</style>\n</defs>\n")
    for g, at in out:
        parts.append(f'<use class="{g[0]}" xlink:href="{g[1]}" x="{g[2]:g}" y="{g[3]:g}" style="animation-delay:{at:.0f}ms"/>\n')
    for rule in rules:
        if len(rule) == 2:
            parts.append(f'<path class="rule {rule[0]}" d="{rule[1]}"/>\n')
        else:
            # A stroked line carries its own transform attribute, so the animation goes on a wrapper.
            parts.append('<g class="rule">' + re.sub(r'stroke="rgb[^"]+"', 'class="line"', rule[2]) + "</g>\n")
    parts.append(f'<rect class="caret accent" x="{caret_x:.2f}" y="{caret_y - 7.4:.2f}" width="0.9" height="9.2"/>\n')
    parts.append("</svg>\n")
    OUT.write_text("".join(parts), encoding="utf-8")
    print(f"{OUT.name}: {len(out)} glyphs in {len(lines)} lines, {len(rules)} rule(s), typeset in {total / 1000:.1f} s, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
