from __future__ import annotations

import unittest
from unittest.mock import patch

from cloud_gateway import _media_auth_allowed, _video_session_valid, _video_session_value


class MediaAuthTest(unittest.TestCase):
    def test_publish_requires_separate_credentials_and_loopback_caller(self) -> None:
        payload = {
            "action": "publish",
            "path": "robot/front",
            "user": "robot-publisher",
            "password": "publish-secret",
        }
        with patch("cloud_gateway.MEDIA_PUBLISH_PASSWORD", "publish-secret"):
            self.assertTrue(_media_auth_allowed(payload, "127.0.0.1"))
            self.assertFalse(_media_auth_allowed(payload, "203.0.113.5"))

    def test_read_accepts_existing_public_token(self) -> None:
        payload = {"action": "read", "path": "robot/front", "token": "public-token"}
        with patch("cloud_gateway.PUBLIC_API_TOKEN", "public-token"):
            self.assertTrue(_media_auth_allowed(payload, "::1"))

    def test_rejects_unknown_path_and_action(self) -> None:
        with patch("cloud_gateway.PUBLIC_API_TOKEN", "public-token"):
            self.assertFalse(
                _media_auth_allowed(
                    {"action": "read", "path": "robot/other", "token": "public-token"},
                    "127.0.0.1",
                )
            )
            self.assertFalse(
                _media_auth_allowed(
                    {"action": "api", "path": "robot/front", "token": "public-token"},
                    "127.0.0.1",
                )
            )

    def test_video_session_is_signed_and_expires(self) -> None:
        with patch("cloud_gateway.VIDEO_SESSION_SECRET", "video-secret"), patch(
            "cloud_gateway.VIDEO_SESSION_TTL_SECONDS", 600
        ):
            value = _video_session_value(now=1_000)
            self.assertTrue(_video_session_valid(value, now=1_100))
            self.assertFalse(_video_session_valid(value, now=1_601))
            self.assertFalse(_video_session_valid(value + "tampered", now=1_100))


if __name__ == "__main__":
    unittest.main()
