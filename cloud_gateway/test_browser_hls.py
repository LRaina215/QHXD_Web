"""Browser HLS route and cookie isolation; no camera or real credentials."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import cloud_gateway as gateway


class BrowserHLSTest(unittest.TestCase):
    def setUp(self):
        for name, value in {
            "PUBLIC_API_TOKEN": "test-public-token",
            "VIDEO_SESSION_SECRET": "test-video-secret",
            "VIDEO_SESSION_TTL_SECONDS": 600,
            "MEDIA_STREAM_PATH": "robot/front",
        }.items():
            p = patch.object(gateway, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(gateway, "_operation_log")
        p.start()
        self.addCleanup(p.stop)
        gateway.rate_buckets.clear()
        self.client = TestClient(gateway.app, base_url="https://site.test")

    def session(self):
        response = self.client.post("/api/video/session", headers={
            "Authorization": "Bearer test-public-token",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        return response.json()["data"]["hls_url"]

    def transport(self, handler):
        original = httpx.AsyncClient
        return patch.object(gateway.httpx, "AsyncClient", side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs))

    def test_each_playlist_and_chunk_requires_valid_browser_cookie(self):
        with self.transport(lambda _: self.fail("invalid session reached upstream")):
            for suffix in ("index.m3u8", "seg0.ts"):
                self.assertEqual(self.client.get("/video/hls/robot/front/" + suffix).status_code, 401)
            self.client.cookies.set(gateway.VIDEO_SESSION_COOKIE, "tampered")
            self.assertEqual(self.client.get("/video/hls/robot/front/seg0.ts").status_code, 401)
            self.client.cookies.clear()
            with patch.object(gateway.time, "time", return_value=1700):
                self.client.cookies.set(gateway.VIDEO_SESSION_COOKIE, gateway._video_session_value(now=1000))
                self.assertEqual(self.client.get("/video/hls/robot/front/seg0.ts").status_code, 401)

    def test_authorized_playlist_redirect_and_chunks_keep_cookie_scoped_urls(self):
        url = self.session()
        calls = []

        def serve(request):
            calls.append(request)
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)
            if request.url.path.endswith(".m3u8"):
                if "cookieCheck" not in request.url.params:
                    return httpx.Response(302, headers={"Location": "/robot/front/index.m3u8?cookieCheck=1"})
                return httpx.Response(200, text='#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\nseg0.ts\n')
            return httpx.Response(206, content=b"media", headers={"Content-Range": "bytes 0-4/5"})

        with self.transport(serve):
            result = self.client.get(url)
            self.assertEqual(result.status_code, 200)
            self.assertIn('URI="/video/hls/robot/front/init.mp4"', result.text)
            self.assertIn("/video/hls/robot/front/seg0.ts", result.text)
            self.assertNotIn(gateway.MINIPROGRAM_VIDEO_PREFIX, result.text)
            self.assertEqual(result.headers["cache-control"], "no-store")
            chunk = self.client.get("/video/hls/robot/front/seg0.ts", headers={"Range": "bytes=0-4"})
            self.assertEqual(chunk.status_code, 206)
            self.assertEqual(chunk.content, b"media")
            self.assertEqual(chunk.headers["content-range"], "bytes 0-4/5")
            head = self.client.head("/video/hls/robot/front/seg0.ts")
            self.assertEqual(head.status_code, 206)
            self.assertEqual(head.content, b"")
        self.assertEqual(calls[2].headers["range"], "bytes=0-4")

    def test_authenticated_unknown_stream_and_query_do_not_reach_upstream(self):
        self.session()
        with self.transport(lambda _: self.fail("invalid path reached upstream")):
            self.assertEqual(self.client.get("/video/hls/robot/other/index.m3u8").status_code, 404)
            self.assertEqual(self.client.get("/video/hls/robot/front/index.m3u8?redirect=elsewhere").status_code, 404)

    def test_redirect_escape_and_playlist_external_uri_remain_rejected(self):
        url = self.session()
        with self.transport(lambda _: httpx.Response(302, headers={"Location": "http://private.invalid/"})):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("location", response.headers)
        with self.transport(lambda _: httpx.Response(200, text="#EXTM3U\nhttps://other.invalid/seg0.ts")):
            self.assertEqual(self.client.get(url).status_code, 502)


if __name__ == "__main__":
    unittest.main()
