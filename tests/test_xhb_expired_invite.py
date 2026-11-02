import sys
import unittest
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xhb_matching import match_expired_invite, match_template_scaled

ROOT = Path(__file__).resolve().parents[1]


class ExpiredInviteTests(unittest.TestCase):
    def setUp(self):
        self.image = cv2.imread(str(ROOT / "tests/fixtures/xhb_invite_expired.png"))

    def detect(self, image, scale=1):
        accept, _ = match_template_scaled(image, str(ROOT / "templates/xhb_accept_invite.png"), preferred_scale=scale)
        return match_expired_invite(image, accept,
                                    str(ROOT / "templates/xhb_invite_expired.png"),
                                    str(ROOT / "templates/xhb_reject_invite.png"), scale)

    def test_expired_invitation_targets_reject_instead_of_accept(self):
        for scale in (1, 1.25, 1.5):
            with self.subTest(scale=scale):
                image = cv2.resize(self.image, None, fx=scale, fy=scale)
                center, score = self.detect(image, scale)
                self.assertIsNotNone(center)
                self.assertAlmostEqual(center[0], 267 * scale, delta=3)
                self.assertAlmostEqual(center[1], 126 * scale, delta=3)
                self.assertGreaterEqual(score, .86)

    def test_unexpired_invite_must_not_be_rejected(self):
        image = self.image.copy()
        image[123:145, 434:510] = 0
        self.assertIsNone(self.detect(image)[0])

    def test_expiry_elsewhere_must_not_target_another_invitation(self):
        reject = str(ROOT / "templates/xhb_reject_invite.png")
        expired = str(ROOT / "templates/xhb_invite_expired.png")
        self.assertIsNone(match_expired_invite(self.image, (100, 20), expired, reject)[0])
        self.assertIsNone(match_expired_invite(self.image, None, expired, reject)[0])
