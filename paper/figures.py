#!/usr/bin/env python3
"""The three animated figures of the profile, written as plain SVG with CSS keyframes.

    assets/fig-letx.svg       two authors type in one source, the page is typeset
    assets/fig-offschool.svg  a pendulum draws its own curve: predict, run, learn
    assets/fig-callgate.svg   three tool calls meet the gate: allow, ask, deny

House rules for these files:
  * no script and no external resource, so GitHub serves them as ordinary images;
  * one file for both themes (prefers-color-scheme) on a transparent ground;
  * every loop is one timeline of T seconds, each element has its own keyframes on it;
  * a reader who asked for reduced motion gets the finished picture, standing still;
  * the mathematics is real TeX: tex() typesets it and returns the glyph outlines.
"""
import math
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "assets"
BUILD = HERE / ".build"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace"

PALETTE = """
.i{fill:#1F2328}.m{fill:#59636E}.a{fill:#6D28D9}.b{fill:#0F766E}.r{fill:#B42318}
.si{stroke:#1F2328}.sm{stroke:#8C959F}.sa{stroke:#6D28D9}.sb{stroke:#0F766E}.sr{stroke:#B42318}
.n{fill:none}.l{stroke-width:1;stroke-linecap:round;stroke-linejoin:round}
text{font-family:%s;font-size:10px}
@media (prefers-color-scheme:dark){
.i{fill:#E6EDF3}.m{fill:#9198A1}.a{fill:#A78BFA}.b{fill:#5EEAD4}.r{fill:#F97066}
.si{stroke:#E6EDF3}.sm{stroke:#6E7681}.sa{stroke:#A78BFA}.sb{stroke:#5EEAD4}.sr{stroke:#F97066}}
""" % MONO


class Timeline:
    """One loop of T seconds. Each call returns a class name carrying its own keyframes."""

    def __init__(self, seconds: float):
        self.T = seconds
        self.css = []
        self.count = 0

    def pct(self, t: float) -> str:
        return f"{max(0.0, min(100.0, 100.0 * t / self.T)):.2f}%"

    def frames(self, stops, ease="linear") -> str:
        """stops: [(time in s, 'css declarations')]. The first and last hold to the ends of the loop."""
        self.count += 1
        name = f"k{self.count}"
        body = []
        if stops[0][0] > 0:
            body.append(f"0%{{{stops[0][1]}}}")
        for t, decl in stops:
            body.append(f"{self.pct(t)}{{{decl}}}")
        if stops[-1][0] < self.T:
            body.append(f"100%{{{stops[-1][1]}}}")
        self.css.append(f"@keyframes {name}{{{''.join(body)}}}.{name}{{animation:{name} {self.T}s {ease} infinite}}")
        return name

    def show(self, on: float, off: float, fade: float = 0.18) -> str:
        """Hidden, then visible from `on` to `off`."""
        e = 0.001
        return self.frames([(max(0, on - e), "opacity:0"), (on, "opacity:1"), (off, "opacity:1"),
                            (min(self.T, off + fade), "opacity:0")])

    def style(self) -> str:
        still = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
        return "<style>" + (PALETTE + "".join(self.css) + still).replace("\n", "") + "</style>"


def tex(source: str, prefix: str, colour_class: str = "i"):
    """Typeset `source` with pdflatex; return (defs, uses, width, height) as SVG glyph outlines."""
    BUILD.mkdir(exist_ok=True)
    job = f"fig-{prefix}"
    doc = ("\\documentclass[border=0.5pt]{standalone}\\usepackage[T1]{fontenc}\\usepackage{lmodern}"
           "\\usepackage{amsmath}\\begin{document}" + source + "\\end{document}")
    (BUILD / f"{job}.tex").write_text(doc)
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{job}.tex"], cwd=BUILD,
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["pdftocairo", "-svg", f"{job}.pdf", f"{job}.svg"], cwd=BUILD, check=True)
    svg = (BUILD / f"{job}.svg").read_text()
    w, h = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    defs = re.search(r"<defs>(.*?)</defs>", svg, re.S).group(1).replace('id="glyph-', f'id="{prefix}-')
    body = svg.split("</defs>", 1)[1].rsplit("</svg>", 1)[0].replace('"#glyph-', f'"#{prefix}-')
    body = re.sub(r'fill="rgb[^"]*" fill-opacity="1"', f'class="{colour_class}"', body)
    body = re.sub(r'stroke="rgb[^"]*"', f'class="s{colour_class}"', body)
    return defs, body, w, h


def typed(tl, text, x, y, start, per_char, off, cls="i", cw=6.0):
    """A line that is typed: one <text> per character, each switched on at its own moment."""
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        k = tl.show(start + i * per_char, off)
        esc = ch.replace("&", "&amp;").replace("<", "&lt;")
        out.append(f'<text class="{cls} {k}" x="{x + i * cw:g}" y="{y}">{esc}</text>')
    return "".join(out)


def static(text, x, y, cls="m", cw=6.0, size=None):
    s = f' style="font-size:{size}px"' if size else ""
    return f'<text class="{cls}" x="{x}" y="{y}" textLength="{len(text) * cw:g}" lengthAdjust="spacingAndGlyphs"{s}>' \
           + text.replace("&", "&amp;").replace("<", "&lt;") + "</text>"


def caret(tl, x, y, start, n, per_char, off, cls, cw=6.0):
    """A caret that steps along a typed line, with a small flag so two authors can be told apart."""
    stops = [(max(0, start - 0.3), f"opacity:0;transform:translateX(0px)"), (start, "opacity:1;transform:translateX(0px)")]
    for i in range(1, n + 1):
        stops.append((start + i * per_char, f"opacity:1;transform:translateX({i * cw:g}px)"))
    stops.append((off, f"opacity:1;transform:translateX({n * cw:g}px)"))
    stops.append((off + 0.18, f"opacity:0;transform:translateX({n * cw:g}px)"))
    k = tl.frames(stops, ease="steps(1,end)")
    return (f'<g class="{k}"><rect class="{cls}" x="{x - 0.6}" y="{y - 9}" width="1.3" height="11.5"/>'
            f'<path class="{cls}" d="M{x - 0.6} {y - 9}h5.2l-1.6 2 1.6 2h-5.2z"/></g>')


def write(name, width, height, tl, defs, body, label):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{label}">'
           f"<defs>{defs}</defs>{tl.style()}{body}</svg>\n")
    (OUT / name).write_text(svg, encoding="utf-8")
    print(f"{name}: {len(svg) // 1024} KB, loop {tl.T:g} s, {tl.count} animations")


# --- Figure 1: LetX -------------------------------------------------------------------------------

def fig_letx():
    tl = Timeline(9.0)
    end = 8.2  # everything typed or typeset is wiped here, then the loop starts over
    d1, eq, ew, eh = tex(r"$\displaystyle E = mc^{2}$", "e")
    d2, pr, pw, ph = tex(r"\footnotesize Mass is energy at rest.", "p")
    d3, no, nw, nh = tex(r"\small (1)", "n")
    b = []
    # the editor
    b.append('<rect class="n si l" x="6.5" y="14.5" width="158" height="150" rx="6"/>')
    b.append('<path class="n sm l" d="M6.5 32.5h158"/>')
    b.append('<circle class="m" cx="17" cy="23.5" r="2"/><circle class="m" cx="24.5" cy="23.5" r="2"/>')
    b.append(static("main.tex", 36, 27, "m", cw=5.2, size=8.6))
    b.append(static("\\begin{equation}", 15, 52))
    b.append(static("\\end{equation}", 15, 84))
    # author one writes the equation, author two writes the sentence, at the same time
    b.append(typed(tl, "E = mc^2", 27, 68, 0.5, 0.17, end))
    b.append(caret(tl, 27, 68, 0.5, 8, 0.17, end, "a"))
    b.append(typed(tl, "Mass is energy", 15, 108, 1.1, 0.13, end))
    b.append(typed(tl, "at rest.", 15, 124, 1.1 + 15 * 0.13, 0.13, end))
    b.append(caret(tl, 15, 108, 1.1, 14, 0.13, 1.1 + 14.5 * 0.13, "b"))
    b.append(caret(tl, 15, 124, 1.1 + 15 * 0.13, 8, 0.13, end, "b"))
    # compile: the arrow fires once the source is whole
    fire = tl.frames([(4.3, "opacity:.25;transform:translateX(0px)"), (4.6, "opacity:1;transform:translateX(3px)"),
                      (5.0, "opacity:.25;transform:translateX(0px)")], ease="ease-in-out")
    b.append(f'<path class="n sa l {fire}" d="M170 89.5h10m-4-4l4 4-4 4" style="stroke-width:1.4"/>')
    # the page
    b.append('<path class="n si l" d="M188.5 14.5h78l16 16v134h-94z"/><path class="n si l" d="M266.5 14.5v16h16"/>')
    on = tl.show(4.9, end, fade=0.3)
    sx = 1.25
    b.append(f'<g class="{on}">')
    b.append('<rect class="m" x="212" y="40" width="46" height="3" rx="1.5"/><rect class="m" x="222" y="48" width="26" height="2" rx="1" style="opacity:.6"/>')
    b.append(f'<g transform="translate({235.5 - ew * sx / 2:.2f} {66}) scale({sx})">{eq}</g>')
    b.append(f'<g transform="translate({276 - nw:.2f} {69.5})">{no}</g>')
    b.append(f'<g transform="translate({235.5 - pw * 0.86 / 2:.2f} {97}) scale(0.86)">{pr}</g>')
    for i, wd in enumerate((70, 70, 70, 44)):
        b.append(f'<rect class="m" x="200.5" y="{118 + i * 8}" width="{wd}" height="2" rx="1" style="opacity:.45"/>')
    b.append("</g>")
    b.append(static("Fig. 1", 6, 176, "m", cw=5.3, size=8.8))
    write("fig-letx.svg", 290, 178, tl, d1 + d2 + d3, "".join(b),
          "Figure 1. Two authors type in one LaTeX source at the same time, and the page is typeset.")


# --- Figure 2: offSchool --------------------------------------------------------------------------

def fig_offschool():
    tl = Timeline(8.0)
    period = 2.0
    px, py, length, theta = 150.0, 22.0, 78.0, 21.0
    amp = length * math.sin(math.radians(theta))
    top, lam, bottom = 118.0, 44.0, 172.0
    d1, formula, fw, fh = tex(r"$\displaystyle T = 2\pi\sqrt{\frac{L}{g}}$", "t")
    b = []
    sine = "cubic-bezier(.37,0,.63,1)"
    extra = (f"@keyframes swing{{0%,100%{{transform:rotate({theta:g}deg)}}50%{{transform:rotate(-{theta:g}deg)}}}}"
             f".swing{{transform-origin:{px:g}px {py:g}px;animation:swing {period:g}s {sine} infinite}}"
             f"@keyframes pen{{0%,100%{{transform:translateX(-{amp:.2f}px)}}50%{{transform:translateX({amp:.2f}px)}}}}"
             f".pen{{animation:pen {period:g}s {sine} infinite}}"
             f"@keyframes roll{{from{{transform:translateY(0)}}to{{transform:translateY({lam:g}px)}}}}"
             f".roll{{animation:roll {period:g}s linear infinite}}")
    tl.css.append(extra)
    # the steps of a lesson, lit one after another
    for i, (word, t0, t1) in enumerate((("1 predict", 0.0, 2.6), ("2 run", 2.6, 5.6), ("3 learn", 5.6, 8.0))):
        lit = tl.frames([(max(0, t0 - 0.001), "opacity:.38"), (t0 + 0.001, "opacity:1"), (t1 - 0.2, "opacity:1"),
                         (t1, "opacity:.38")] if t0 > 0 else
                        [(0, "opacity:1"), (t1 - 0.2, "opacity:1"), (t1, "opacity:.38"), (7.99, "opacity:.38")])
        b.append(f'<g class="{lit}">' + static(word, 10, 26 + i * 15, "i") + "</g>")
    # the pendulum
    b.append(f'<path class="n si l" d="M{px - 16} {py}h32" style="stroke-width:1.6"/>')
    b.append(f'<g class="swing"><path class="n si l" d="M{px} {py}v{length}"/><circle class="a" cx="{px}" cy="{py + length}" r="7.5"/></g>')
    # the paper it writes on
    b.append(f'<path class="n sm l" d="M{px - 62} {top}h124" stroke-dasharray="2 3"/>')
    b.append(f'<clipPath id="win"><rect x="{px - 64}" y="{top}" width="128" height="{bottom - top}"/></clipPath>')
    pts = []
    y = top - lam
    while y <= bottom + 1:
        pts.append(f"{px - amp * math.cos(2 * math.pi * (y - top) / lam):.2f} {y:.2f}")
        y += 1.5
    guess = tl.show(0.3, 2.5, fade=0.25)
    b.append(f'<g class="{guess}"><path class="n sm l" d="M{px} {top + 4}V{bottom}" stroke-dasharray="4 4"/>'
             + static("?", px + 8, top + 30, "m", size=15) + "</g>")
    trace = tl.show(2.7, 7.6, fade=0.35)
    b.append(f'<g class="{trace}"><g clip-path="url(#win)"><path class="n sa l roll" d="M{" L".join(pts)}" style="stroke-width:1.5"/></g>'
             f'<circle class="a pen" cx="{px}" cy="{top}" r="2.4"/></g>')
    learn = tl.show(5.8, 7.6, fade=0.35)
    b.append(f'<g class="{learn}" transform="translate({284 - fw * 1.3:.2f} {30}) scale(1.3)">{formula}</g>')
    b.append(static("Fig. 2", 10, 172, "m", cw=5.3, size=8.8))
    write("fig-offschool.svg", 290, 178, tl, d1, "".join(b),
          "Figure 2. A pendulum swings and draws its own sine curve: predict, run the simulation, learn the formula.")


# --- Figure 3: callgate ---------------------------------------------------------------------------

def fig_callgate():
    tl = Timeline(10.0)
    end = 9.3
    gate_x = 150.0
    b = []
    # the agent's script
    b.append('<rect class="n si l" x="6.5" y="30.5" width="104" height="96" rx="6"/>')
    b.append(static("script", 14, 24, "m", cw=5.4, size=9))
    calls = [("list_issues()", 54), ("send_email()", 78), ("delete_repo()", 102)]
    for name, y in calls:
        b.append(static(name, 14, y + 3, "i", cw=5.6, size=9.4))
    # the gate
    b.append(f'<path class="n si l" d="M{gate_x} 22V66M{gate_x} 90V134" style="stroke-width:2.2"/>')
    b.append(static("gate", gate_x - 11, 148, "m", cw=5.4, size=9))
    # the journal
    b.append('<rect class="n si l" x="190.5" y="30.5" width="93" height="96" rx="6"/>')
    b.append(static("journal", 198, 24, "m", cw=5.4, size=9))

    def token(y0, t0, verdict):
        """A call leaves its line, runs to the gap in the gate, and meets its verdict."""
        x0, gap_y = 112.0, 78.0
        dx, dy = gate_x - x0, gap_y - y0
        arrive = t0 + 0.7
        if verdict == "allow":
            stops = [(t0 - 0.01, "opacity:0;transform:translate(0px,0px)"), (t0, "opacity:1;transform:translate(0px,0px)"),
                     (arrive, f"opacity:1;transform:translate({dx}px,{dy}px)"),
                     (arrive + 0.6, f"opacity:1;transform:translate({dx + 40}px,{dy}px)"),
                     (arrive + 0.75, f"opacity:0;transform:translate({dx + 40}px,{dy}px)")]
            leave = arrive + 0.6
        elif verdict == "ask":
            stops = [(t0 - 0.01, "opacity:0;transform:translate(0px,0px)"), (t0, "opacity:1;transform:translate(0px,0px)"),
                     (arrive, f"opacity:1;transform:translate({dx - 7}px,{dy}px)"),
                     (arrive + 1.5, f"opacity:1;transform:translate({dx - 7}px,{dy}px)"),
                     (arrive + 2.1, f"opacity:1;transform:translate({dx + 40}px,{dy}px)"),
                     (arrive + 2.25, f"opacity:0;transform:translate({dx + 40}px,{dy}px)")]
            leave = arrive + 2.1
        else:
            stops = [(t0 - 0.01, "opacity:0;transform:translate(0px,0px)"), (t0, "opacity:1;transform:translate(0px,0px)"),
                     (arrive, f"opacity:1;transform:translate({dx - 7}px,{dy}px)"),
                     (arrive + 0.25, f"opacity:1;transform:translate({dx - 22}px,{dy + 10}px)"),
                     (arrive + 0.7, f"opacity:0;transform:translate({dx - 30}px,{dy + 26}px)")]
            leave = arrive
        k = tl.frames(stops, ease="ease-in-out")
        cls = "r" if verdict == "deny" else "a"
        return f'<circle class="{cls} {k}" cx="{x0}" cy="{y0}" r="4.2"/>', arrive, leave

    rows = [("allow", "list_issues", "i"), ("approved", "send_email", "i"), ("deny", "delete_repo", "r")]
    starts = [0.6, 2.6, 6.3]
    verdicts = ["allow", "ask", "deny"]
    for i, ((name, y), t0, v) in enumerate(zip(calls, starts, verdicts)):
        dot, arrive, leave = token(y, t0, v)
        b.append(dot)
        if v == "ask":  # the gate asks a person, and waits
            ask = tl.show(arrive + 0.05, arrive + 1.45, fade=0.1)
            b.append(f'<g class="{ask}"><circle class="n sa l" cx="{gate_x}" cy="78" r="9" stroke-dasharray="3 3"/>'
                     + static("approve?", gate_x - 22, 14, "a", cw=5.4, size=9) + "</g>")
        if v == "deny":  # the gap closes
            shut = tl.show(arrive - 0.05, arrive + 1.3, fade=0.2)
            b.append(f'<path class="n sr l {shut}" d="M{gate_x} 66V90" style="stroke-width:2.2"/>')
        word, tool, cls = rows[i]
        line = tl.show(leave + 0.1, end, fade=0.3)
        mark = "x" if v == "deny" else "+"
        b.append(f'<g class="{line}">' + static(mark, 197, 54 + i * 24, cls, size=9.4)
                 + static(tool, 207, 54 + i * 24, cls, cw=5.6, size=9.4)
                 + static(word, 207, 64 + i * 24, "m" if cls == "i" else "r", cw=4.9, size=8) + "</g>")
    b.append(static("Fig. 3", 6, 170, "m", cw=5.3, size=8.8))
    b.append(static("every call is checked and written down", 62, 170, "m", cw=5.3, size=8.8))
    write("fig-callgate.svg", 290, 178, tl, "", "".join(b),
          "Figure 3. Three tool calls from an agent's script meet the gate: one is allowed, one waits for approval, one is denied. Each is written to the journal.")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fig_letx()
    fig_offschool()
    fig_callgate()
