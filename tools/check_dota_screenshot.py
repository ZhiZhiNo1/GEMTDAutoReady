"""Check whether a supplied screenshot matches the Dota update dialog template."""

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dota_matching import (  # noqa: E402
    DOTA_UPDATE_FALLBACK_SCALES,
    DOTA_UPDATE_MATCH_THRESHOLD,
    match_template_multiscale,
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


def main():
    parser = argparse.ArgumentParser(
        description="Check a Dota screenshot against the update-popup template."
    )
    parser.add_argument("screenshot", type=Path, help="Screenshot from another user")
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT_ROOT / "templates" / "update_popup.png",
        help="Template image (default: templates/update_popup.png)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DOTA_UPDATE_MATCH_THRESHOLD,
        help=f"Match threshold (default: {DOTA_UPDATE_MATCH_THRESHOLD:.2f})",
    )
    args = parser.parse_args()

    try:
        screen = read_image(args.screenshot)
    except ValueError as exc:
        parser.error(str(exc))

    if not args.template.is_file():
        parser.error(f"Template not found: {args.template}")

    center, score, scale = match_template_multiscale(
        screen,
        str(args.template),
        args.threshold,
        DOTA_UPDATE_FALLBACK_SCALES,
    )
    height, width = screen.shape[:2]
    print(f"Screenshot: {args.screenshot}")
    print(f"Image size: {width}x{height}")
    print(f"Template:   {args.template}")
    print(f"Score:      {score:.3f} (threshold {args.threshold:.2f})")
    print(f"Scale:      {scale:.3f}")
    print(f"Center:     {center if center else 'not detected'}")
    print(f"Result:     {'MATCH' if center else 'NO MATCH'}")
    return 0 if center else 1


if __name__ == "__main__":
    raise SystemExit(main())
