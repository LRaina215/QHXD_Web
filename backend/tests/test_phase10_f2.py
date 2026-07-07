import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.main as main_module
from app.schemas import DetectionObject, DetectionStatus, PerceptionDetectionStatusRequest, SmartCommandRequest
from app.services.mock_state import MockStateService
from app.services.mode_manager import mode_manager
from app.services.persistence import persistence
from app.services.state_store import state_store
from app.services.tts_service import tts_service
from app.services.visual_event_service import visual_event_service


class Phase10F2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_db = persistence._db_path
        self._old_tts_backend = os.environ.get("TTS_BACKEND")
        self._old_tts_cooldown = os.environ.get("TTS_NORMAL_COOLDOWN_SECONDS")
        persistence._db_path = Path(self._temp_dir.name) / "phase10-f2.db"
        persistence.initialize()
        service = MockStateService()
        service.initialize()
        state_store.initialize(service.get_latest_state())
        mode_manager.initialize(state_store.get_latest_state())
        visual_event_service._camera_offline = False
        tts_service._recent_event_keys.clear()
        tts_service._last_normal_at = None
        os.environ["TTS_BACKEND"] = "mock"
        os.environ["TTS_NORMAL_COOLDOWN_SECONDS"] = "0"

    def tearDown(self) -> None:
        persistence._db_path = self._old_db
        self._restore("TTS_BACKEND", self._old_tts_backend)
        self._restore("TTS_NORMAL_COOLDOWN_SECONDS", self._old_tts_cooldown)
        self._temp_dir.cleanup()

    async def test_visual_event_is_persisted_and_front_query_uses_it(self) -> None:
        timestamp = datetime.now(timezone.utc)
        await main_module.ingest_detection_status(
            PerceptionDetectionStatusRequest(
                detection_status=DetectionStatus(
                    enabled=True,
                    source="test-yolo",
                    model_name="test.rknn",
                    frame_id="camera_front",
                    timestamp=timestamp,
                    objects=[
                        DetectionObject(
                            class_name="person",
                            confidence=0.88,
                            bbox_xyxy=[10, 20, 120, 220],
                        )
                    ],
                    events=[],
                )
            )
        )

        events = persistence.list_visual_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "person_detected")
        self.assertEqual(events[0].class_name, "person")

        result, _ = main_module.smart_voice_service.handle(
            SmartCommandRequest(text="前面有什么", source="test", generate_tts=False)
        )
        self.assertEqual(result.intent, "query_front_status")
        self.assertIsNone(result.mission_candidate)
        self.assertIn("前方视觉", result.reply_text)
        self.assertIn("人员", result.reply_text)

    async def test_visual_event_deduplicates_within_time_window(self) -> None:
        base = datetime.now(timezone.utc)
        for offset in (0, 2):
            await main_module.ingest_detection_status(
                PerceptionDetectionStatusRequest(
                    detection_status=DetectionStatus(
                        enabled=True,
                        source="test-yolo",
                        model_name="test.rknn",
                        frame_id="camera_front",
                        timestamp=base + timedelta(seconds=offset),
                        objects=[
                            DetectionObject(
                                class_name="person",
                                confidence=0.7 + offset / 100,
                                bbox_xyxy=[0, 0, 20, 40],
                            )
                        ],
                        events=[],
                    )
                )
            )

        events = persistence.list_visual_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].count, 2)
        self.assertGreaterEqual(events[0].duration_s, 2.0)

    def test_tts_event_policy_deduplicates_repeat_events(self) -> None:
        first = tts_service.speak_with_policy("到达一号点", event_key="task-1:arrived:wp_001")
        second = tts_service.speak_with_policy("到达一号点", event_key="task-1:arrived:wp_001")
        self.assertEqual(first.status, "generated")
        self.assertEqual(second.status, "skipped")

    @staticmethod
    def _restore(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
