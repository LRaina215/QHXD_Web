"""Public token and bounded binary forwarding, without a real RK/FPGA."""
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import cloud_gateway as gateway


class MapUploadGatewayTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(gateway.app)
        self.headers = {"Authorization": "Bearer test-token", "Content-Type": "application/octet-stream"}
        for name, value in {"PUBLIC_API_TOKEN": "test-token", "PUBLIC_CONTROL_ENABLED": False}.items():
            p = patch.object(gateway, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(gateway, "_operation_log"); p.start(); self.addCleanup(p.stop)
        gateway.rate_buckets.clear()

    def forward(self, handler):
        original = httpx.AsyncClient
        return patch.object(gateway.httpx, "AsyncClient", side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs))

    def test_upload_requires_token_and_does_not_bypass_motion_policy(self):
        with self.forward(lambda _: self.fail("unauthorized body reached RK")):
            self.assertEqual(self.client.post("/api/navigation/map/upload", content=b"nvmp").status_code, 401)
        def handler(req):
            self.assertEqual(req.content, b"nvmp")
            self.assertEqual(req.headers["content-type"], "application/octet-stream")
            self.assertEqual(req.url.params["filename"], "field.nvmp")
            return httpx.Response(409, json={"detail": "FPGA需要空闲状态"})
        with self.forward(handler):
            r = self.client.post("/api/navigation/map/upload?filename=field.nvmp", headers=self.headers, content=b"nvmp")
        self.assertEqual(r.status_code, 409)
        self.assertIn("空闲", r.json()["detail"])

    def test_oversize_header_and_actual_stream_never_reach_RK(self):
        with self.forward(lambda _: self.fail("oversize body reached RK")):
            for declared, suffix in (("999999", ""), ("1", "/")):
                r = self.client.post("/api/navigation/map/upload" + suffix, headers={**self.headers, "Content-Length": declared},
                                     content=b"x" * (gateway.MAX_MAP_UPLOAD_BYTES + 1))
                self.assertEqual(r.status_code, 413)

    def test_progress_read_is_read_only_and_preserves_terminal_state(self):
        with self.forward(lambda req: httpx.Response(200, json={"success": True, "data": {"state": "ready", "progress": 100}})):
            r = self.client.get("/api/navigation/map/upload")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["state"], "ready")
