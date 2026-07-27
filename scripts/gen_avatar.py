#!/usr/bin/env python3
"""Turn a portrait into a background-free monochrome pixel grid.

The output is a grid of *brightness levels*, not colours — the phosphor palette
lives in gen_cards.py so the card can be re-themed without re-running this.
Cells outside the subject are null, so the portrait floats on the screen.

Run this only when the profile picture changes:

    pip install pillow opencv-python-headless numpy
    python scripts/gen_avatar.py                          # current GitHub avatar
    python scripts/gen_avatar.py --source photo.jpg       # a local file
    python scripts/gen_avatar.py --source cutout.png      # already has alpha

It writes assets/avatar-grid.json, which gen_cards.py reads. Keeping the grid
checked in means the nightly card refresh needs no image libraries at all.

Tuned for a centred head-and-shoulders portrait. If a new photo is framed very
differently, the SEED_* fractions below are the knobs; --debug writes a preview
PNG so you can see what the mask actually caught.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

USER = "shihabshahrier"
CELLS = 80          # grid resolution
LEVELS = 16         # brightness steps in the phosphor ramp
ALPHA_CUT = 118     # cell belongs to the subject above this alpha

# Tone mapping. A bright shirt against a bright wall otherwise pins the top of
# the ramp and leaves the face sitting in the dark half, so the highlights get
# compressed above the knee before the ramp is applied.
KNEE = 0.82         # luminance where highlight compression starts
KNEE_SLOPE = 0.35   # how much of the range highlights keep above the knee
GAMMA = 0.90        # <1 lifts midtones so the face reads

# How far below the shoulder line to frame, as a fraction of head width. Lower
# values crop the torso out. Worth reducing when the subject wears something
# bright: on a single-colour ramp a white shirt takes the top of the range and
# pushes the face into the dark half.
CROP_EXTRA = 0.30
METRIC_WIDTH = 900  # silhouette is measured at this size, whatever the source

# GrabCut seeding, as fractions of the source. Head ellipse, torso block, and a
# background ring that stays clear of the shoulders.
SEED_HEAD = (0.49, 0.36, 0.24, 0.21)      # cx, cy, rx, ry — definite subject
SEED_HEAD_LOOSE = (0.49, 0.38, 0.37, 0.31)  # probable subject
SEED_TORSO = (0.05, 0.62, 1.00, 1.00)     # probable subject
SEED_TORSO_SURE = (0.28, 0.80, 0.72, 1.00)  # definite subject
SEED_BG_TOP = 0.06                        # top band is definitely background
SEED_BG_SIDE = 0.10                       # side margins, above SEED_BG_DEPTH
SEED_BG_DEPTH = 0.50


def load(login, source):
    if source:
        return Image.open(source).convert("RGBA")
    url = f"https://github.com/{login}.png?size=460"
    req = urllib.request.Request(url, headers={"User-Agent": "profile-card-generator"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGBA")


def supplied_alpha(img, min_transparent=0.03):
    """Use the image's own alpha channel if it carries a real cutout.

    A hand-made cutout beats anything grabCut infers, particularly around hair,
    so prefer it whenever the source actually has transparent pixels.
    """
    if "A" not in img.getbands():
        return None
    alpha = np.asarray(img.getchannel("A"))
    if (alpha < 16).mean() < min_transparent:
        return None  # opaque PNG, nothing was cut out
    fg = (alpha >= 128).astype(np.uint8)
    k = max(3, int(min(img.size) * 0.004) | 1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if count > 1:
        fg = (labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return fg


def foreground_mask(img):
    """GrabCut with an explicit mask: ring of background, head + torso as subject.

    A plain rect init clips the shoulders, which leaves a floating head, so the
    torso is seeded as foreground explicitly.
    """
    arr = np.array(img.convert("RGB"))[:, :, ::-1].copy()  # PIL RGB -> OpenCV BGR
    h, w = arr.shape[:2]

    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    mask[: int(h * SEED_BG_TOP), :] = cv2.GC_BGD
    mask[: int(h * SEED_BG_DEPTH), : int(w * SEED_BG_SIDE)] = cv2.GC_BGD
    mask[: int(h * SEED_BG_DEPTH), int(w * (1 - SEED_BG_SIDE)) :] = cv2.GC_BGD

    for (x0, y0, x1, y1), label in ((SEED_TORSO, cv2.GC_PR_FGD),
                                    (SEED_TORSO_SURE, cv2.GC_FGD)):
        cv2.rectangle(mask, (int(w * x0), int(h * y0)),
                      (min(w - 1, int(w * x1)), min(h - 1, int(h * y1))), label, -1)
    for (cx, cy, rx, ry), label in ((SEED_HEAD_LOOSE, cv2.GC_PR_FGD),
                                    (SEED_HEAD, cv2.GC_FGD)):
        cv2.ellipse(mask, (int(w * cx), int(h * cy)), (int(w * rx), int(h * ry)),
                    0, 0, 360, label, -1)

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(arr, mask, None, bgd, fgd, 9, cv2.GC_INIT_WITH_MASK)

    fg = np.where((mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD), 0, 1).astype(np.uint8)
    k = max(3, int(min(w, h) * 0.02) | 1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((max(3, k // 3) | 1,) * 2, np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if count > 1:  # drop stray blobs, keep the person
        fg = (labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return fg


def bust_crop(fg, size, extra=None):
    """Square crop framing head and shoulders.

    Cropping to the whole foreground bounding box pushes the shoulders out to
    the card edges, because they are the widest part of the subject. Instead,
    find the row where the silhouette flares out from head width to shoulder
    width, and frame relative to that.

    Metrics are measured on a canonical-size copy of the silhouette. Measuring
    on the raw mask made the framing depend on the source resolution — the same
    cutout at 2000px and at 900px picked different shoulder lines, because
    resampling softens the alpha edge and shifts where the flare test trips.
    """
    w, h = size
    scale = METRIC_WIDTH / max(fg.shape)
    small = cv2.resize(fg, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_NEAREST) if scale < 1 else fg
    k = 1.0 / scale if scale < 1 else 1.0

    ys, _ = np.where(small > 0)
    top, bottom = ys.min(), ys.max()
    widths = small.sum(axis=1)[top : bottom + 1]
    span = len(widths)

    # The neck is the narrowest row between head and shoulders. Earlier this
    # looked for where the silhouette flares past a multiple of head width,
    # which is unstable on a subject whose hair is as wide as their shoulders —
    # the test tripped on a different row for the same cutout at two sizes.
    band0, band1 = int(span * 0.30), max(int(span * 0.30) + 1, int(span * 0.85))
    neck = band0 + int(np.argmin(widths[band0:band1]))
    head_h = max(neck, 1)

    head_rows = small[top : top + max(1, int(head_h * 0.9))]
    hx = np.where(head_rows.sum(axis=0) > 0)[0]
    head_cx = (hx.min() + hx.max()) / 2

    y0 = (top - head_h * 0.12) * k
    side = head_h * (1.12 + (CROP_EXTRA if extra is None else extra)) * k
    y0, side, head_cx = int(y0), int(side), head_cx * k
    x0 = int(head_cx - side / 2)
    # Deliberately not clamped to the image. A tightly framed photo would other-
    # wise get a non-square crop, which squashes the face when it is resized to
    # the grid. build() pads instead — outside the frame is background anyway,
    # and background is transparent on the card.
    return (x0, y0, x0 + side, y0 + side)


def tone(grey, subject):
    """Stretch, compress highlights above the knee, then lift midtones.

    Every statistic is taken over `subject` pixels only. A cut-out source has
    transparent areas that read as pure black, and letting those into the
    histogram drags the stretch so far that the face blows out to the top of
    the ramp.
    """
    lum = np.asarray(grey, np.float32) / 255.0
    vals = lum[subject]
    if vals.size:
        lo, hi = np.percentile(vals, 1), np.percentile(vals, 98)
        lum = np.clip((lum - lo) / max(hi - lo, 1e-6), 0, 1)
    lum = np.where(lum <= KNEE, lum, KNEE + (lum - KNEE) * KNEE_SLOPE)
    peak = lum[subject].max() if vals.size else lum.max()
    return np.power(np.clip(lum / (peak or 1.0), 0, 1), GAMMA)


def build(img, cells, levels, extra=None):
    mask = supplied_alpha(img)
    source = "alpha channel"
    if mask is None:
        mask, source = foreground_mask(img), "grabCut"
    if not mask.any():
        raise SystemExit("Background removal found no subject.")
    print(f"subject mask from {source}")

    img = img.convert("RGB")

    x0, y0, x1, y1 = bust_crop(mask, img.size, extra)
    w, h = img.size
    pad = (max(0, -x0), max(0, -y0), max(0, x1 - w), max(0, y1 - h))
    if any(pad):
        img = ImageOps.expand(img, border=pad, fill=(0, 0, 0))
        mask = np.pad(mask, ((pad[1], pad[3]), (pad[0], pad[2])))
        x0, y0, x1, y1 = x0 + pad[0], y0 + pad[1], x1 + pad[0], y1 + pad[1]
    box = (x0, y0, x1, y1)

    # Sharpen before downsampling — at this resolution soft edges become mush,
    # and a monochrome ramp has no colour left to carry the features.
    src = ImageEnhance.Contrast(img).enhance(1.10)
    src = src.filter(ImageFilter.UnsharpMask(radius=3, percent=110, threshold=2))

    grey = src.crop(box).convert("L").resize((cells, cells), Image.LANCZOS)
    alpha = np.array(
        Image.fromarray(mask * 255).crop(box).resize((cells, cells), Image.LANCZOS)
    )
    subject = alpha >= ALPHA_CUT
    quant = np.clip((tone(grey, subject) * (levels - 1)).round().astype(int),
                    0, levels - 1)
    grid = [
        [None if alpha[y, x] < ALPHA_CUT else int(quant[y, x]) for x in range(cells)]
        for y in range(cells)
    ]
    return grid, box, mask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=USER)
    ap.add_argument("--source", help="local image file instead of the GitHub avatar")
    ap.add_argument("--cells", type=int, default=CELLS)
    ap.add_argument("--levels", type=int, default=LEVELS)
    ap.add_argument("--out", default="assets/avatar-grid.json")
    ap.add_argument("--crop-extra", type=float, default=CROP_EXTRA,
                    help="how far below the shoulders to frame (lower = tighter)")
    ap.add_argument("--debug", help="write a PNG preview of the pixel grid here")
    args = ap.parse_args()

    img = load(args.user, args.source)
    grid, box, _ = build(img, args.cells, args.levels, args.crop_extra)
    lit = sum(1 for row in grid for cell in row if cell is not None)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"cells": args.cells, "levels": args.levels, "grid": grid}, fh)
    print(f"wrote {args.out} — {args.cells}x{args.cells}, {lit} subject cells "
          f"({100 * lit / args.cells ** 2:.0f}% coverage), crop {box}")

    if args.debug:
        scale = 6
        prev = Image.new("RGB", (args.cells * scale,) * 2, (5, 8, 13))
        cell = Image.new("RGB", (args.cells, args.cells), (5, 8, 13))
        for y, row in enumerate(grid):
            for x, level in enumerate(row):
                if level is not None:
                    v = int(255 * level / (args.levels - 1))
                    cell.putpixel((x, y), (v // 4, v, v))
        prev.paste(cell.resize((args.cells * scale,) * 2, Image.NEAREST), (0, 0))
        prev.save(args.debug)
        print(f"wrote {args.debug}")


if __name__ == "__main__":
    main()
