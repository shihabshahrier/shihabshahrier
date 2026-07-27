#!/usr/bin/env python3
"""Turn the GitHub avatar into a background-free monochrome pixel grid.

The output is a grid of *brightness levels*, not colors — the phosphor palette
lives in gen_cards.py so the card can be re-themed without re-running this.
Cells outside the subject are null, so the portrait floats on the screen.

Run this only when the profile picture changes:

    pip install pillow opencv-python-headless numpy
    python scripts/gen_avatar.py

It writes assets/avatar-grid.json, which gen_cards.py reads. Keeping the grid
checked in means the nightly card refresh needs no image libraries at all.
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
GAMMA = 0.86        # <1 lifts midtones so faces don't sink into the dark end


def fetch(login):
    url = f"https://github.com/{login}.png?size=460"
    req = urllib.request.Request(url, headers={"User-Agent": "profile-card-generator"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


def foreground_mask(img):
    """GrabCut with an explicit mask: ring of background, head + torso as subject.

    A plain rect init clips the shoulders on this portrait, which leaves a
    floating head — seeding the torso as probable foreground keeps the bust.
    """
    arr = np.array(img)[:, :, ::-1].copy()  # PIL RGB -> OpenCV BGR
    h, w = arr.shape[:2]

    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    mask[: int(h * 0.03), :] = cv2.GC_BGD
    mask[:, : int(w * 0.06)] = cv2.GC_BGD
    mask[:, int(w * 0.94) :] = cv2.GC_BGD
    cv2.rectangle(mask, (int(w * 0.18), int(h * 0.60)), (int(w * 0.82), h - 1),
                  cv2.GC_PR_FGD, -1)
    cv2.rectangle(mask, (int(w * 0.30), int(h * 0.72)), (int(w * 0.70), h - 1),
                  cv2.GC_FGD, -1)
    cv2.ellipse(mask, (int(w * 0.52), int(h * 0.34)),
                (int(w * 0.17), int(h * 0.22)), 0, 0, 360, cv2.GC_FGD, -1)
    cv2.ellipse(mask, (int(w * 0.52), int(h * 0.36)),
                (int(w * 0.26), int(h * 0.32)), 0, 0, 360, cv2.GC_PR_FGD, -1)

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(arr, mask, None, bgd, fgd, 8, cv2.GC_INIT_WITH_MASK)

    fg = np.where((mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD), 0, 1).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if count > 1:  # drop stray blobs, keep the person
        fg = (labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return fg


def build(login, cells, levels):
    img = fetch(login)
    mask = foreground_mask(img)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise SystemExit("Background removal found no subject.")

    # square crop centred on the subject so the bust fills the grid
    cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
    half = int(max(xs.max() - xs.min(), ys.max() - ys.min()) * 0.56)
    w, h = img.size
    box = (max(0, cx - half), max(0, cy - half), min(w, cx + half), min(h, cy + half))

    # Sharpen before downsampling — at this resolution soft edges become mush,
    # and a monochrome ramp has no color left to carry the features.
    src = ImageEnhance.Contrast(img).enhance(1.15)
    src = src.filter(ImageFilter.UnsharpMask(radius=3, percent=115, threshold=2))

    grey = src.crop(box).convert("L")
    grey = grey.resize((cells, cells), Image.LANCZOS)
    grey = ImageOps.autocontrast(grey, cutoff=(1, 2))  # use the whole ramp

    lum = np.asarray(grey, dtype=np.float32) / 255.0
    lum = np.power(lum, GAMMA)
    quant = np.clip((lum * (levels - 1)).round().astype(int), 0, levels - 1)

    alpha = np.array(
        Image.fromarray(mask * 255).crop(box).resize((cells, cells), Image.LANCZOS)
    )

    grid = [
        [None if alpha[y, x] < ALPHA_CUT else int(quant[y, x]) for x in range(cells)]
        for y in range(cells)
    ]
    return grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=USER)
    ap.add_argument("--cells", type=int, default=CELLS)
    ap.add_argument("--levels", type=int, default=LEVELS)
    ap.add_argument("--out", default="assets/avatar-grid.json")
    args = ap.parse_args()

    grid = build(args.user, args.cells, args.levels)
    lit = sum(1 for row in grid for cell in row if cell is not None)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"cells": args.cells, "levels": args.levels, "grid": grid}, fh)
    print(f"wrote {args.out} — {args.cells}x{args.cells}, "
          f"{lit} subject cells, {args.levels} brightness levels")


if __name__ == "__main__":
    main()
