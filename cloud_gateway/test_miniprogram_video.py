"""Local HLS contract checks. No robot, camera, public network or real tokens."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import cloud_gateway as gateway


class MiniVideoTest(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(gateway, "PUBLIC_API_TOKEN", "test-public-token"),
            patch.object(gateway, "VIDEO_SESSION_SECRET", "test-video-secret"),
            patch.object(gateway, "VIDEO_SESSION_TTL_SECONDS", 600),
            patch.object(gateway, "MEDIA_STREAM_PATH", "robot/front"),
            patch.object(gateway, "_operation_log"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        gateway.rate_buckets.clear()
        self.client = TestClient(gateway.app)
        self.auth = {"Authorization": "Bearer test-public-token"}

    def session(self, client=None):
        response = (client or self.client).post("/api/video/miniprogram/session", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", response.headers)
        data = response.json()["data"]
        self.assertEqual(data["protocol"], "hls")
        self.assertEqual(data["expires_in"], 600)
        self.assertNotIn("test-public-token", data["playback_url"])
        return data["playback_url"]

    def transport(self, handler):
        original = httpx.AsyncClient
        return patch.object(gateway.httpx, "AsyncClient", side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs))

    def test_session_requires_token_and_keeps_browser_cookie_contract(self):
        self.assertEqual(self.client.post("/api/video/miniprogram/session").status_code, 401)
        self.session()
        browser = self.client.post("/api/video/session", headers=self.auth)
        self.assertEqual(browser.status_code, 200)
        self.assertIn("HttpOnly", browser.headers["set-cookie"])
        self.assertIn("Path=/video/", browser.headers["set-cookie"])
        with patch.object(gateway, "_check_rate_limit", return_value=False):
            self.assertEqual(self.client.post("/api/video/miniprogram/session", headers=self.auth).status_code, 429)

    def test_lease_expires_is_tamper_resistant_and_scoped_to_stream(self):
        lease = gateway._mini_video_lease(now=1000)
        self.assertTrue(gateway._mini_video_lease_valid(lease, now=1599))
        self.assertFalse(gateway._mini_video_lease_valid(lease, now=1600))
        self.assertFalse(gateway._mini_video_lease_valid(lease + "a", now=1100))
        self.assertFalse(gateway._mini_video_lease_valid(gateway._video_session_value(now=1000), now=1100))
        with patch.object(gateway, "MEDIA_STREAM_PATH", "robot/other"):
            self.assertFalse(gateway._mini_video_lease_valid(lease, now=1100))

    def test_playlist_rewrites_all_child_playlists_initialization_and_parts(self):
        text = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXT-X-PART:DURATION=0.2,URI="/robot/front/part0.mp4"\nmain_stream.m3u8?session=12345678-1234-1234-1234-123456789abc\nseg0.mp4\n'
        lease = gateway._mini_video_lease()
        result = gateway._mini_video_playlist(text, "robot/front/index.m3u8", lease)
        prefix = gateway.MINIPROGRAM_VIDEO_PREFIX + lease + "/robot/front/"
        for file in ("init.mp4", "part0.mp4", "main_stream.m3u8", "seg0.mp4"):
            self.assertIn(prefix + file, result)
        for invalid in ("https://other.invalid/x.mp4", "//other.invalid/x.mp4", "../../other/seg.mp4", "%2e%2e/x.mp4"):
            with self.assertRaises(ValueError):
                gateway._mini_video_playlist("#EXTM3U\n" + invalid, "robot/front/index.m3u8", lease)

    def test_independent_clients_read_same_source_without_cookies(self):
        other = TestClient(gateway.app)
        first, second = self.session(), self.session(other)
        calls = []

        def serve(request):
            calls.append(request.url.path)
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)
            if request.url.path.endswith(".m3u8"):
                return httpx.Response(200, text="#EXTM3U\nseg0.mp4\n")
            return httpx.Response(206, content=b"media", headers={"Content-Range": "bytes 0-4/5"})

        with self.transport(serve):
            a, b = self.client.get(first), other.get(second)
            self.assertEqual(a.status_code, 200)
            self.assertEqual(b.status_code, 200)
            self.assertEqual(b.headers["access-control-allow-origin"], "*")
            chunk = next(line for line in b.text.splitlines() if not line.startswith("#"))
            media = other.get(chunk, headers={"Range": "bytes=0-4"})
            self.assertEqual(media.content, b"media")
            self.assertEqual(media.status_code, 206)
            self.assertEqual(media.headers["content-range"], "bytes 0-4/5")
        self.assertEqual(calls, ["/robot/front/index.m3u8", "/robot/front/index.m3u8", "/robot/front/seg0.mp4"])

    def test_expired_chunks_unknown_paths_and_query_are_rejected_before_proxy(self):
        url = self.session()
        with self.transport(lambda _: self.fail("invalid request reached media server")):
            invalid = gateway.MINIPROGRAM_VIDEO_PREFIX + "invalid/robot/front/seg0.mp4"
            self.assertEqual(self.client.get(invalid).status_code, 401)
            self.assertEqual(self.client.get(url.replace("robot/front/", "robot/other/")).status_code, 404)
            self.assertEqual(self.client.get(url + "?redirect=http://other.invalid").status_code, 404)
        self.assertTrue(gateway._mini_video_query("_HLS_msn=3&_HLS_part=1&_HLS_skip=YES"))
        self.assertTrue(gateway._mini_video_query("session=12345678-1234-1234-1234-123456789abc"))
        self.assertFalse(gateway._mini_video_query("_HLS_msn=1&_HLS_msn=2"))

    def test_mediamtx_same_playlist_session_redirect_is_supported(self):
        url = self.session()
        calls = []

        def serve(request):
            calls.append(request.url.path)
            if "cookieCheck" not in request.url.params:
                return httpx.Response(302, headers={"Location": "/robot/front/index.m3u8?cookieCheck=1", "Set-Cookie": "cookieCheck=1; Secure"})
            return httpx.Response(200, text="#EXTM3U\nseg0.mp4\n")

        with self.transport(serve):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["/robot/front/index.m3u8"] * 2)

    def test_upstream_failures_do_not_expose_redirects_or_diagnostics(self):
        url = self.session()
        with self.transport(lambda _: httpx.Response(302, headers={"Location": "http://internal.invalid"}, text="private diagnostics")):
            result = self.client.get(url)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("location", result.headers)
        self.assertNotIn("private", result.text)
        with self.transport(lambda _: httpx.Response(200, text="#EXTM3U\nhttps://other.invalid/a.mp4")):
            self.assertEqual(self.client.get(url).status_code, 502)


if __name__ == "__main__":
    unittest.main()
