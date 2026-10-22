from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from cloud_gateway import app


class GatewayHealthTest(unittest.TestCase):
    def test_api_alias_matches_root_health(self) -> None:
        client = TestClient(app)
        with patch("cloud_gateway._robot_state", AsyncMock(return_value={"mode": "real"})):
            root = client.get("/health")
            alias = client.get("/api/gateway/health")
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(alias.json(), root.json())
        self.assertTrue(alias.json()["rk_online"])
        self.assertIn("public_control_enabled", alias.json())


if __name__ == "__main__":
    unittest.main()
