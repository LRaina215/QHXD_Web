"""Stopping and localization recovery are authenticated, but do not require a healthy robot."""
import asyncio
import unittest
from unittest.mock import patch, AsyncMock

from starlette.requests import Request
import cloud_gateway as gateway


class RecoveryControlsTest(unittest.TestCase):
    def request(self, path, authorized=True):
        headers = [(b'authorization', b'Bearer test-token')] if authorized else []
        return Request({'type': 'http', 'method': 'POST', 'path': path,
                        'headers': headers, 'client': ('127.0.0.1', 1), 'scheme': 'http', 'query_string': b''})

    def setUp(self):
        for name, value in {'PUBLIC_API_TOKEN': 'test-token', 'PUBLIC_CONTROL_ENABLED': False}.items():
            patcher = patch.object(gateway, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(gateway, '_operation_log'); patcher.start(); self.addCleanup(patcher.stop)

    def test_stop_does_not_require_normal_rate_budget_or_robot_readiness(self):
        for path in ['/api/mission/pause', '/api/mission/cancel', '/api/platform/estop', '/api/mission/cancel/']:
            with self.subTest(path=path), patch.object(gateway, '_check_rate_limit', return_value=False), \
                    patch.object(gateway, '_ensure_control_allowed', AsyncMock()) as readiness:
                self.assertIsNone(asyncio.run(gateway._preflight(self.request(path), 'test')))
                readiness.assert_not_awaited()

    def test_stop_still_requires_token(self):
        for path in ['/api/mission/pause', '/api/mission/cancel', '/api/platform/estop']:
            result = asyncio.run(gateway._preflight(self.request(path, False), 'test'))
            self.assertEqual(result.status_code, 401)

    def test_pose_recovery_bypasses_motion_readiness_but_keeps_rate_limit(self):
        with patch.object(gateway, '_check_rate_limit', return_value=True), \
                patch.object(gateway, '_ensure_control_allowed', AsyncMock()) as readiness:
            self.assertIsNone(asyncio.run(gateway._preflight(self.request('/api/platform/set_pose'), 'test')))
            readiness.assert_not_awaited()
        with patch.object(gateway, '_check_rate_limit', return_value=False):
            self.assertEqual(asyncio.run(gateway._preflight(self.request('/api/platform/set_pose'), 'test')).status_code, 429)

    def test_start_and_resume_still_require_motion_readiness(self):
        with patch.object(gateway, '_check_rate_limit', return_value=True):
            for path in ['/api/mission/go_to_point', '/api/mission/resume', '/api/mission/start_patrol']:
                result = asyncio.run(gateway._preflight(self.request(path), 'test'))
                self.assertEqual(result.status_code, 403)
