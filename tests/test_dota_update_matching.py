import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dota_matching import (DOTA_UPDATE_MATCH_THRESHOLD, DOTA_UPDATE_FALLBACK_SCALES,
                           match_template_multiscale, select_dota_template)


class UpdatePopupMatchingTests(unittest.TestCase):
    def test_fractional_scale_popup_in_window_and_client_screenshots(self):
        popup = cv2.imread(str(ROOT / "tests/fixtures/update_popup_fractional_scale.png"))
        screen = np.zeros((696, 1178, 3), dtype=np.uint8)
        screen[278:448, 426:752] = popup
        for image, expected in ((screen, (588, 309)), (screen[31:-1, 1:-1], (587, 278))):
            with self.subTest(shape=image.shape):
                center, score, _ = match_template_multiscale(
                    image, str(ROOT / "templates/dota2/1920_1080/update_popup.png"),
                    DOTA_UPDATE_MATCH_THRESHOLD, DOTA_UPDATE_FALLBACK_SCALES,
                    refine_scales=True)
                self.assertIsNotNone(center)
                self.assertGreater(score, .85)
                self.assertLessEqual(abs(center[0] - expected[0]), 2)
                self.assertLessEqual(abs(center[1] - expected[1]), 2)

    def test_blank_screen_does_not_match_or_trigger_refinement(self):
        screen = np.zeros((665, 1176, 3), dtype=np.uint8)
        with patch("dota_matching.cv2.matchTemplate", wraps=cv2.matchTemplate) as matcher:
            center, _, _ = match_template_multiscale(
                screen, str(ROOT / "templates/dota2/1920_1080/update_popup.png"),
                DOTA_UPDATE_MATCH_THRESHOLD, DOTA_UPDATE_FALLBACK_SCALES,
                refine_scales=True)
        self.assertIsNone(center)
        self.assertEqual(matcher.call_count, 5)


class ResolutionResourceTests(unittest.TestCase):
    def test_exact_group_missing_image_and_nearest_group(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            root = Path(directory) / "dota2"
            for size in ("1920_1080", "1280_720", "1024_768"):
                (root / size).mkdir(parents=True)
            base = root / "1920_1080/update_popup.png"
            base.touch()
            small = root / "1280_720/update_popup.png"
            small.touch()
            self.assertEqual(select_dota_template(base, 1280, 720), (small, (1280, 720)))
            self.assertEqual(select_dota_template(base, 1366, 768), (small, (1280, 720)))
            # A resolution directory without this image cannot shadow another group.
            self.assertEqual(select_dota_template(base, 1024, 768), (small, (1280, 720)))
            small.unlink()
            self.assertEqual(select_dota_template(base, 1280, 720), (base, (1920, 1080)))

    def test_exact_resolution_only_uses_unscaled_template(self):
        popup = cv2.imread(str(ROOT / "tests/fixtures/update_popup_fractional_scale.png"))
        screen = np.zeros((664, 1176, 3), dtype=np.uint8)
        screen[247:417, 425:751] = popup
        with patch("dota_matching.cv2.matchTemplate", wraps=cv2.matchTemplate) as matcher:
            center, score, scale = match_template_multiscale(
                screen, str(ROOT / "templates/dota2/1920_1080/update_popup.png"),
                DOTA_UPDATE_MATCH_THRESHOLD, DOTA_UPDATE_FALLBACK_SCALES,
                refine_scales=True)
        self.assertIsNotNone(center)
        self.assertGreater(score, .99)
        self.assertEqual(scale, 1.0)
        self.assertEqual(matcher.call_count, 1)

    def test_baseline_fine_scale_fallback_without_resolution_resource(self):
        popup = cv2.imread(str(ROOT / "tests/fixtures/update_popup_fractional_scale.png"))
        screen = np.zeros((696, 1178, 3), dtype=np.uint8)
        screen[278:448, 426:752] = popup
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            template = Path(directory) / "update_popup.png"
            shutil.copyfile(ROOT / "templates/dota2/1920_1080/update_popup.png", template)
            coarse = match_template_multiscale(screen, str(template),
                DOTA_UPDATE_MATCH_THRESHOLD, DOTA_UPDATE_FALLBACK_SCALES)
            fine = match_template_multiscale(screen, str(template),
                DOTA_UPDATE_MATCH_THRESHOLD, DOTA_UPDATE_FALLBACK_SCALES, refine_scales=True)
        self.assertIsNone(coarse[0])
        self.assertIsNotNone(fine[0])
        self.assertGreater(fine[1], .85)


if __name__ == "__main__":
    unittest.main()
