"""Shared CLI and image-loading helpers for per-recognition screenshot checks."""

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dota_matching import (  # noqa: E402
    DOTA_START_GAME_MATCH_THRESHOLD,
    DOTA_UPDATE_FALLBACK_SCALES,
    DOTA_UPDATE_MATCH_THRESHOLD,
    match_template_multiscale,
)
from xhb_matching import (  # noqa: E402
    XHB_MATCH_THRESHOLD,
    match_template_scaled,
)


def read_image(path):
    """Read image paths including non-ASCII Windows paths."""
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"Cannot read image: {path} ({exc})") from exc

    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unsupported or invalid image: {path}")
    return image


def run_check(recognition_name, template_name, is_dota=False, default_threshold=None):
    parser = argparse.ArgumentParser(
        description=f"Check a screenshot for {recognition_name}."
    )
    parser.add_argument("screenshot", type=Path, help="Screenshot to check")
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT_ROOT / "templates" / template_name,
        help=f"Template image (default: templates/{template_name})",
    )
    if is_dota:
        threshold = default_threshold or DOTA_UPDATE_MATCH_THRESHOLD
        parser.add_argument(
            "--threshold",
            type=float,
            default=threshold,
            help=f"Match threshold (default: {threshold:.2f})",
        )
    else:
        parser.add_argument(
            "--threshold",
            type=float,
            default=XHB_MATCH_THRESHOLD,
            help=f"Match threshold (default: {XHB_MATCH_THRESHOLD:.2f})",
        )
        parser.add_argument(
            "--scale",
            type=float,
            default=1.0,
            help="Preferred DPI scale for the screenshot (default: 1.0)",
        )

    args = parser.parse_args()
    try:
        screen = read_image(args.screenshot)
    except ValueError as exc:
        parser.error(str(exc))

    if not args.template.is_file():
        parser.error(f"Template not found: {args.template}")

    if is_dota:
        center, score, scale = match_template_multiscale(
            screen,
            str(args.template),
            args.threshold,
            DOTA_UPDATE_FALLBACK_SCALES,
        )
    else:
        center, score = match_template_scaled(
            screen,
            str(args.template),
            threshold=args.threshold,
            preferred_scale=args.scale,
        )
        scale = args.scale

    height, width = screen.shape[:2]
    print(f"Recognition: {recognition_name}")
    print(f"Screenshot:  {args.screenshot}")
    print(f"Image size:  {width}x{height}")
    print(f"Template:    {args.template}")
    print(f"Score:       {score:.3f} (threshold {args.threshold:.2f})")
    print(f"Scale:       {scale:.3f}")
    print(f"Center:      {center if center else 'not detected'}")
    print(f"Result:      {'MATCH' if center else 'NO MATCH'}")
    return 0 if center else 1
