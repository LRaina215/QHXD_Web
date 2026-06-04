import json
import os
import sqlite3
import tempfile
import wave
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import app.main as main_module
from app.schemas import (
    AlertEvent,
    DetectionEvent,
    DetectionObject,
    DetectionStatus,
    DeviceStatus,
    EulerDegSample,
    EnvSensor,
    GoToWaypointRequest,
    ImuSample,
    ModeSwitchRequest,
    NavStatus,
    NucImuUpdateRequest,
    NucStateUpdateRequest,
    PauseMissionRequest,
    PerceptionDetectionStatusRequest,
    QuaternionSample,
    RobotPose,
    ResumeMissionRequest,
    ReturnHomeRequest,
    TaskStatus,
    Vector3Sample,
    VoiceConfirmCommandRequest,
    VoiceRecordCommandRequest,
    SmartCommandRequest,
    SpeakRequest,
    VoiceTextCommandRequest,
)
from app.services.imu_store import imu_store
from app.services.mock_state import MockStateService
from app.services.mode_manager import mode_manager
from app.services.persistence import persistence
from app.services.state_store import state_store
from app.services.voice.llm_client import LLMClientResponse
from app.services.voice import llm_intent_parser as llm_intent_parser_module


class _FakeNucMissionServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self._server.requests = []
        self._server.current_goal = None
        self._server.task_status = {
            "task_id": "nuc-task-idle",
            "task_type": "placeholder",
            "state": "idle",
            "progress": 0,
            "source": "nuc",
        }
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict]:
        return self._server.requests

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _build_handler(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/internal/rk3588/mission":
                    self.send_response(404)
                    self.end_headers()
                    return

                raw_length = self.headers.get("Content-Length", "0")
                request_length = int(raw_length)
                body = self.rfile.read(request_length)
                payload = json.loads(body.decode("utf-8"))
                self.server.requests.append(payload)

                command = payload["command"]
                command_payload = payload["payload"]
                current_goal = self.server.current_goal
                task_status = self.server.task_status.copy()
                nav_state = "idle"
                detail = f"NUC 已受理 {command} 命令。"

                if command == "go_to_waypoint":
                    current_goal = command_payload["waypoint_id"]
                    task_status = {
                        "task_id": "nuc-task-go-to-waypoint",
                        "task_type": "go_to_waypoint",
                        "state": "running",
                        "progress": 10,
                        "source": "nuc",
                    }
                    nav_state = "running"
                elif command == "start_patrol":
                    current_goal = command_payload["patrol_id"]
                    task_status = {
                        "task_id": "nuc-task-start-patrol",
                        "task_type": "start_patrol",
                        "state": "running",
                        "progress": 5,
                        "source": "nuc",
                    }
                    nav_state = "running"
                elif command == "pause_task":
                    task_status.update({"state": "paused", "source": "nuc"})
                    nav_state = "paused"
                elif command == "resume_task":
                    task_status.update({"state": "running", "source": "nuc"})
                    nav_state = "running"
                elif command == "return_home":
                    current_goal = "home"
                    task_status = {
                        "task_id": "nuc-task-return-home",
                        "task_type": "return_home",
                        "state": "running",
                        "progress": 15,
                        "source": "nuc",
                    }
                    nav_state = "running"
                else:
                    detail = f"未知命令 {command}"

                self.server.current_goal = current_goal
                self.server.task_status = task_status
                response_body = {
                    "success": True,
                    "data": {
                        "accepted": True,
                        "command": command,
                        "task_status": task_status,
                        "current_goal": current_goal,
                        "nav_state": nav_state,
                        "received_at": datetime.now(timezone.utc).isoformat(),
                        "detail": detail,
                    },
                }
                encoded = json.dumps(response_body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        return Handler


class _FakeMultipartRequest:
    def __init__(self, *, filename: str, content: bytes, fields: dict[str, str] | None = None) -> None:
        self._boundary = f"----test-boundary-{uuid4().hex}"
        self.headers = {"content-type": f"multipart/form-data; boundary={self._boundary}"}
        self._body = self._build_body(filename, content, fields or {})

    async def body(self) -> bytes:
        return self._body

    def _build_body(self, filename: str, content: bytes, fields: dict[str, str]) -> bytes:
        chunks: list[bytes] = []
        boundary = self._boundary.encode("utf-8")
        for name, value in fields.items():
            chunks.extend([
                b"--" + boundary,
                f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                b"",
                value.encode("utf-8"),
            ])
        chunks.extend([
            b"--" + boundary,
            f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8"),
            b"Content-Type: audio/wav",
            b"",
            content,
            b"--" + boundary + b"--",
        ])
        return b"\r\n".join(chunks) + b"\r\n"


def _tiny_wav_bytes() -> bytes:
    temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_path = Path(temp.name)
    temp.close()
    try:
        with wave.open(str(temp_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 1600)
        return temp_path.read_bytes()
    finally:
        temp_path.unlink(missing_ok=True)


class Phase1BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = persistence._db_path
        self._original_service = main_module.mock_state_service
        self._original_nuc_base_url = os.environ.get("NUC_BASE_URL")
        self._original_nuc_mission_path = os.environ.get("NUC_MISSION_PATH")
        self._original_nuc_timeout = os.environ.get("NUC_TIMEOUT_SECONDS")
        self._original_real_stale_after = os.environ.get("REAL_STATE_STALE_AFTER_SECONDS")
        self._original_asr_backend = os.environ.get("ASR_BACKEND")
        self._original_voice_mock_text = os.environ.get("VOICE_MOCK_RECOGNIZED_TEXT")
        self._original_voice_max_seconds = os.environ.get("VOICE_MAX_AUDIO_SECONDS")
        self._original_voice_max_mb = os.environ.get("VOICE_MAX_UPLOAD_MB")
        self._original_llm_enable = os.environ.get("LLM_ENABLE")
        self._original_deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
        self._original_deepseek_model = os.environ.get("DEEPSEEK_MODEL")
        self._original_llm_threshold = os.environ.get("LLM_CONFIDENCE_THRESHOLD")
        self._original_voice_pending_ttl = os.environ.get("VOICE_PENDING_TTL_SECONDS")

        for key in [
            "LLM_ENABLE",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_MODEL",
            "LLM_CONFIDENCE_THRESHOLD",
            "VOICE_PENDING_TTL_SECONDS",
        ]:
            os.environ.pop(key, None)
        main_module.voice_entry_service._pending.clear()

        persistence._db_path = Path(self._temp_dir.name) / "phase1-test.db"
        main_module.mock_state_service = MockStateService()
        main_module.mock_state_service.initialize()
        state_store.initialize(main_module.mock_state_service.get_latest_state())
        imu_store.initialize()
        mode_manager.initialize(state_store.get_latest_state())

    def tearDown(self) -> None:
        main_module.mock_state_service = self._original_service
        persistence._db_path = self._original_db_path
        self._restore_env("NUC_BASE_URL", self._original_nuc_base_url)
        self._restore_env("NUC_MISSION_PATH", self._original_nuc_mission_path)
        self._restore_env("NUC_TIMEOUT_SECONDS", self._original_nuc_timeout)
        self._restore_env("REAL_STATE_STALE_AFTER_SECONDS", self._original_real_stale_after)
        self._restore_env("ASR_BACKEND", self._original_asr_backend)
        self._restore_env("VOICE_MOCK_RECOGNIZED_TEXT", self._original_voice_mock_text)
        self._restore_env("VOICE_MAX_AUDIO_SECONDS", self._original_voice_max_seconds)
        self._restore_env("VOICE_MAX_UPLOAD_MB", self._original_voice_max_mb)
        self._restore_env("LLM_ENABLE", self._original_llm_enable)
        self._restore_env("DEEPSEEK_API_KEY", self._original_deepseek_key)
        self._restore_env("DEEPSEEK_MODEL", self._original_deepseek_model)
        self._restore_env("LLM_CONFIDENCE_THRESHOLD", self._original_llm_threshold)
        self._restore_env("VOICE_PENDING_TTL_SECONDS", self._original_voice_pending_ttl)
        main_module.voice_entry_service._pending.clear()
        self._temp_dir.cleanup()

    async def test_health_endpoint_returns_ok(self) -> None:
        response = await main_module.health()

        self.assertEqual(response.status, "ok")

    async def test_go_to_waypoint_endpoint_persists_command_log(self) -> None:
        request = GoToWaypointRequest(
            waypoint_id="mock-waypoint",
            source="test",
            requested_by="unittest",
        )

        response = await main_module.go_to_waypoint(request)
        logs = persistence.list_command_logs()

        self.assertTrue(response.success)
        self.assertEqual(response.data.command, "go_to_waypoint")
        self.assertEqual(response.data.task_status.task_type, "go_to_waypoint")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].source, "test")
        self.assertEqual(logs[0].payload["waypoint_id"], "mock-waypoint")

    async def test_voice_text_motion_command_requires_confirmation_then_executes(self) -> None:
        response = await main_module.text_command(
            VoiceTextCommandRequest(
                text="去一号点",
                source="test-voice",
                requested_by="unittest",
            )
        )
        logs_before_confirm = persistence.list_command_logs()

        self.assertTrue(response.success)
        self.assertFalse(response.data.accepted)
        self.assertTrue(response.data.need_confirm)
        self.assertIsNotNone(response.data.pending_command_id)
        self.assertEqual(response.data.intent, "go_to_waypoint")
        self.assertEqual(response.data.command, "go_to_waypoint")
        self.assertEqual(response.data.payload["waypoint_id"], "wp_001")
        self.assertIsNone(response.data.task_status)
        self.assertEqual(len(logs_before_confirm), 0)

        confirm_response = await main_module.confirm_voice_command(
            VoiceConfirmCommandRequest(
                pending_command_id=response.data.pending_command_id,
                confirmed=True,
                requested_by="operator",
            )
        )
        logs_after_confirm = persistence.list_command_logs()

        self.assertTrue(confirm_response.success)
        self.assertTrue(confirm_response.data.accepted)
        self.assertEqual(confirm_response.data.command, "go_to_waypoint")
        self.assertEqual(confirm_response.data.task_status.task_type, "go_to_waypoint")
        self.assertEqual(len(logs_after_confirm), 1)
        self.assertEqual(logs_after_confirm[0].source, "test-voice")
        self.assertEqual(logs_after_confirm[0].payload["waypoint_id"], "wp_001")

    async def test_voice_text_command_unknown_does_not_trigger_mission(self) -> None:
        response = await main_module.text_command(
            VoiceTextCommandRequest(
                text="随便转两圈",
                source="test-voice",
                requested_by="unittest",
            )
        )
        logs = persistence.list_command_logs()

        self.assertTrue(response.success)
        self.assertFalse(response.data.accepted)
        self.assertTrue(response.data.need_confirm)
        self.assertIsNone(response.data.intent)
        self.assertEqual(len(logs), 0)

    async def test_asr_text_mock_reuses_text_command_flow(self) -> None:
        response = await main_module.asr_text_mock(
            VoiceTextCommandRequest(
                text="暂停任务",
                source="asr-text-mock",
                requested_by="unittest",
            )
        )

        self.assertTrue(response.data.accepted)
        self.assertEqual(response.data.intent, "pause_task")
        self.assertEqual(response.data.command, "pause_task")
        self.assertIsNotNone(response.data.task_status)
        self.assertEqual(response.data.task_status.state, "paused")


    async def test_llm_complex_motion_requires_confirmation_then_executes(self) -> None:
        os.environ["LLM_ENABLE"] = "true"
        os.environ["DEEPSEEK_API_KEY"] = "test-placeholder-key"
        os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
        original_chat_json = llm_intent_parser_module.llm_client.chat_json

        def fake_chat_json(**kwargs):
            return LLMClientResponse(
                success=True,
                content=json.dumps({
                    "intent": "go_to_waypoint",
                    "command": "go_to_waypoint",
                    "waypoint_alias": "二零一实验室",
                    "waypoint_id": "wp_201",
                    "confidence": 0.92,
                    "need_confirm": True,
                    "reason": "用户表达了将样品送往201实验室的意图",
                    "missing_slots": [],
                    "ask_text": None,
                }, ensure_ascii=False),
                model="deepseek-v4-flash",
            )

        llm_intent_parser_module.llm_client.chat_json = fake_chat_json
        try:
            response = await main_module.text_command(
                VoiceTextCommandRequest(
                    text="帮我把样品送到二零一实验室",
                    source="test-voice",
                    requested_by="unittest",
                    use_llm=True,
                )
            )
            logs_before_confirm = persistence.list_command_logs()
            self.assertFalse(response.data.accepted)
            self.assertEqual(response.data.parser, "llm")
            self.assertEqual(response.data.intent, "go_to_waypoint")
            self.assertEqual(response.data.payload["waypoint_id"], "wp_201")
            self.assertTrue(response.data.need_confirm)
            self.assertIsNotNone(response.data.pending_command_id)
            self.assertEqual(len(logs_before_confirm), 0)

            confirm_response = await main_module.confirm_voice_command(
                VoiceConfirmCommandRequest(
                    pending_command_id=response.data.pending_command_id,
                    confirmed=True,
                    requested_by="operator",
                )
            )
            logs_after_confirm = persistence.list_command_logs()
            self.assertTrue(confirm_response.data.accepted)
            self.assertEqual(confirm_response.data.command, "go_to_waypoint")
            self.assertEqual(confirm_response.data.task_status.task_type, "go_to_waypoint")
            self.assertEqual(len(logs_after_confirm), 1)
            self.assertEqual(logs_after_confirm[0].payload["waypoint_id"], "wp_201")
        finally:
            llm_intent_parser_module.llm_client.chat_json = original_chat_json

    async def test_llm_unknown_does_not_trigger_mission(self) -> None:
        os.environ["LLM_ENABLE"] = "true"
        os.environ["DEEPSEEK_API_KEY"] = "test-placeholder-key"
        original_chat_json = llm_intent_parser_module.llm_client.chat_json

        def fake_chat_json(**kwargs):
            return LLMClientResponse(
                success=True,
                content=json.dumps({
                    "intent": "unknown",
                    "command": None,
                    "waypoint_alias": None,
                    "waypoint_id": None,
                    "confidence": 0.3,
                    "need_confirm": True,
                    "reason": "无法确定用户要执行的机器人任务",
                    "missing_slots": ["target_waypoint"],
                    "ask_text": "请问你要让机器人去哪个位置？",
                }, ensure_ascii=False),
                model="deepseek-v4-flash",
            )

        llm_intent_parser_module.llm_client.chat_json = fake_chat_json
        try:
            response = await main_module.text_command(
                VoiceTextCommandRequest(
                    text="随便闲聊一句",
                    source="test-voice",
                    requested_by="unittest",
                    use_llm=True,
                )
            )
            logs = persistence.list_command_logs()
            self.assertFalse(response.data.accepted)
            self.assertEqual(response.data.parser, "llm")
            self.assertEqual(response.data.intent, "unknown")
            self.assertEqual(len(logs), 0)
        finally:
            llm_intent_parser_module.llm_client.chat_json = original_chat_json

    async def test_confirm_pending_can_cancel_without_mission(self) -> None:
        os.environ["LLM_ENABLE"] = "true"
        os.environ["DEEPSEEK_API_KEY"] = "test-placeholder-key"
        original_chat_json = llm_intent_parser_module.llm_client.chat_json

        def fake_chat_json(**kwargs):
            return LLMClientResponse(
                success=True,
                content=json.dumps({
                    "intent": "return_home",
                    "command": "return_home",
                    "waypoint_alias": "起点",
                    "waypoint_id": "home",
                    "confidence": 0.9,
                    "need_confirm": True,
                    "reason": "用户希望机器人返回起点",
                    "missing_slots": [],
                    "ask_text": None,
                }, ensure_ascii=False),
                model="deepseek-v4-flash",
            )

        llm_intent_parser_module.llm_client.chat_json = fake_chat_json
        try:
            response = await main_module.text_command(
                VoiceTextCommandRequest(
                    text="我想让机器人回装载点",
                    source="test-voice",
                    requested_by="unittest",
                    use_llm=True,
                )
            )
            self.assertFalse(response.data.accepted)
            cancel_response = await main_module.confirm_voice_command(
                VoiceConfirmCommandRequest(
                    pending_command_id=response.data.pending_command_id,
                    confirmed=False,
                    requested_by="operator",
                )
            )
            logs = persistence.list_command_logs()
            self.assertFalse(cancel_response.data.accepted)
            self.assertEqual(len(logs), 0)
        finally:
            llm_intent_parser_module.llm_client.chat_json = original_chat_json

    async def test_phase9a_smart_identity_weather_and_tts(self) -> None:
        identity = await main_module.smart_command(
            SmartCommandRequest(text="你是谁", source="test-smart", requested_by="unittest", generate_tts=True)
        )
        self.assertTrue(identity.success)
        self.assertEqual(identity.data.intent, "query_self_identity")
        self.assertEqual(identity.data.data_source, "robot_profile")
        self.assertIn("灵巡 Sentinel", identity.data.reply_text)
        self.assertIsNotNone(identity.data.tts_status)
        self.assertEqual(identity.data.tts_status.status, "generated")

        weather = await main_module.get_latest_weather()
        self.assertTrue(weather.success)
        self.assertIsNotNone(weather.data)
        self.assertEqual(weather.data.source, "weather_provider")

        weather_reply = await main_module.smart_command(
            SmartCommandRequest(text="现在天气怎么样", source="test-smart", requested_by="unittest")
        )
        self.assertEqual(weather_reply.data.intent, "query_weather")
        self.assertEqual(weather_reply.data.data_source, "weather_provider")
        self.assertIn("天气数据来自外部天气源", weather_reply.data.reply_text)

        tts = await main_module.speak(SpeakRequest(text="我是灵巡 Sentinel。", source="test"))
        self.assertTrue(tts.success)
        self.assertEqual(tts.data.status, "generated")
        latest_tts = await main_module.get_latest_tts()
        self.assertEqual(latest_tts.data.status, "generated")

    async def test_phase9b_smart_model_query_and_open_chat(self) -> None:
        os.environ["LLM_ENABLE"] = "true"
        os.environ["DEEPSEEK_API_KEY"] = "test-placeholder-key"
        os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
        original_chat_json = llm_intent_parser_module.llm_client.chat_json

        model_reply = await main_module.smart_command(
            SmartCommandRequest(text="你使用的模型是什么", source="test-smart", requested_by="unittest")
        )
        self.assertEqual(model_reply.data.intent, "query_assistant_model")
        self.assertEqual(model_reply.data.data_source, "llm_config")
        self.assertIn("DeepSeek", model_reply.data.reply_text)
        self.assertIn("deepseek-v4-flash", model_reply.data.reply_text)
        self.assertIsNone(model_reply.data.mission_candidate)

        def fake_chat_json(**kwargs):
            return LLMClientResponse(
                success=True,
                content=json.dumps({
                    "intent": "open_chat",
                    "command": "open_chat",
                    "waypoint_alias": None,
                    "waypoint_id": None,
                    "confidence": 0.92,
                    "need_confirm": False,
                    "reason": "开放问答",
                    "reply_text": "可以，我会用简短的话解释导航状态，并且不会直接控制底盘。",
                    "missing_slots": [],
                    "ask_text": None,
                }, ensure_ascii=False),
                model="deepseek-v4-flash",
            )

        llm_intent_parser_module.llm_client.chat_json = fake_chat_json
        try:
            response = await main_module.smart_command(
                SmartCommandRequest(text="请用一句话解释你如何协助导航", source="test-smart", requested_by="unittest", use_llm=True)
            )
            self.assertEqual(response.data.intent, "open_chat")
            self.assertEqual(response.data.data_source, "deepseek")
            self.assertEqual(response.data.parser, "llm")
            self.assertIn("不会直接控制底盘", response.data.reply_text)
            self.assertFalse(response.data.need_confirm)
            self.assertIsNone(response.data.mission_candidate)
            self.assertEqual(len(persistence.list_command_logs()), 0)
        finally:
            llm_intent_parser_module.llm_client.chat_json = original_chat_json

    async def test_phase9a_smart_motion_candidate_confirm_and_reject_speed(self) -> None:
        response = await main_module.smart_command(
            SmartCommandRequest(text="帮我送到二零一实验室", source="test-smart", requested_by="unittest")
        )
        self.assertTrue(response.success)
        self.assertEqual(response.data.intent, "go_to_waypoint")
        self.assertTrue(response.data.need_confirm)
        self.assertIsNotNone(response.data.mission_candidate)
        self.assertEqual(response.data.mission_candidate.payload["waypoint_id"], "wp_201")
        self.assertIsNotNone(response.data.pending_command_id)
        self.assertEqual(len(persistence.list_command_logs()), 0)

        confirm_response = await main_module.confirm_voice_command(
            VoiceConfirmCommandRequest(
                pending_command_id=response.data.pending_command_id,
                confirmed=True,
                requested_by="operator",
            )
        )
        self.assertTrue(confirm_response.data.accepted)
        self.assertEqual(confirm_response.data.command, "go_to_waypoint")
        self.assertEqual(persistence.list_command_logs()[0].payload["waypoint_id"], "wp_201")

        rejected = await main_module.smart_command(
            SmartCommandRequest(text="向前走一米", source="test-smart", requested_by="unittest")
        )
        self.assertEqual(rejected.data.intent, "unknown")
        self.assertIsNone(rejected.data.mission_candidate)
        self.assertIn("拒绝直接速度控制", rejected.data.reply_text)

    async def test_detection_status_update_is_visible_in_latest_state(self) -> None:
        response = await main_module.ingest_detection_status(
            PerceptionDetectionStatusRequest(
                detection_status=DetectionStatus(
                    enabled=True,
                    source="rk3588-rknn-yolo",
                    model_name="custom_delivery_yolo_rk3588.rknn",
                    frame_id="camera_front",
                    timestamp=datetime.now(timezone.utc),
                    objects=[
                        DetectionObject(
                            class_name="person",
                            confidence=0.86,
                            bbox_xyxy=[120, 80, 260, 360],
                        )
                    ],
                    events=[
                        DetectionEvent(
                            event_type="person_detected",
                            level="info",
                            message="检测到人员目标",
                        )
                    ],
                )
            )
        )
        latest_state = state_store.get_latest_state()

        self.assertTrue(response.data.accepted)
        self.assertIsNotNone(latest_state.detection_status)
        self.assertEqual(latest_state.detection_status.model_name, "custom_delivery_yolo_rk3588.rknn")
        self.assertEqual(latest_state.detection_status.objects[0].class_name, "person")


    async def test_audio_command_mock_asr_routes_to_existing_mission_flow(self) -> None:
        os.environ["ASR_BACKEND"] = "mock"
        os.environ["VOICE_MOCK_RECOGNIZED_TEXT"] = "暂停任务"
        request = _FakeMultipartRequest(
            filename="pause_task.wav",
            content=_tiny_wav_bytes(),
            fields={"source": "audio-test", "requested_by": "unittest"},
        )

        response = await main_module.audio_command(request)
        logs = persistence.list_command_logs(limit=5)

        self.assertTrue(response.success)
        self.assertEqual(response.data.recognized_text, "暂停任务")
        self.assertEqual(response.data.intent, "pause_task")
        self.assertTrue(response.data.accepted)
        self.assertEqual(logs[0].command, "voice_audio_command")
        self.assertEqual(logs[0].payload["recognized_text"], "暂停任务")

    async def test_audio_command_unknown_text_does_not_trigger_mission(self) -> None:
        os.environ["ASR_BACKEND"] = "mock"
        os.environ["VOICE_MOCK_RECOGNIZED_TEXT"] = "打开窗户"
        request = _FakeMultipartRequest(
            filename="unknown_command.wav",
            content=_tiny_wav_bytes(),
            fields={"source": "audio-test", "requested_by": "unittest"},
        )

        response = await main_module.audio_command(request)
        logs = persistence.list_command_logs(limit=5)

        self.assertTrue(response.success)
        self.assertFalse(response.data.accepted)
        self.assertTrue(response.data.need_confirm)
        self.assertIsNone(response.data.intent)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].command, "voice_audio_command")
        self.assertFalse(logs[0].accepted)

    async def test_audio_command_rejects_non_wav_upload(self) -> None:
        os.environ["ASR_BACKEND"] = "mock"
        request = _FakeMultipartRequest(
            filename="command.txt",
            content=b"not a wav",
            fields={"source": "audio-test", "requested_by": "unittest"},
        )

        with self.assertRaises(main_module.HTTPException):
            await main_module.audio_command(request)

    async def test_record_command_reuses_asr_and_deletes_recording_when_requested(self) -> None:
        os.environ["ASR_BACKEND"] = "mock"
        os.environ["VOICE_MOCK_RECOGNIZED_TEXT"] = "开始巡检"
        recorded_path = Path(self._temp_dir.name) / "start_patrol.wav"
        recorded_path.write_bytes(_tiny_wav_bytes())
        original_recorder = main_module.audio_recorder

        class FakeRecordResult:
            success = True
            audio_path = recorded_path
            duration = 3
            audio_device = "fake-device"
            error = None
            detail = None

        class WorkingRecorder:
            def default_duration(self) -> int:
                return 3

            def default_keep_audio(self) -> bool:
                return True

            def record(self, duration: int) -> FakeRecordResult:
                return FakeRecordResult()

        main_module.audio_recorder = WorkingRecorder()
        try:
            response = await main_module.record_command(
                VoiceRecordCommandRequest(
                    duration=3,
                    source="record-test",
                    requested_by="unittest",
                    keep_audio=False,
                )
            )
        finally:
            main_module.audio_recorder = original_recorder

        self.assertTrue(response.success)
        self.assertIsNotNone(response.data)
        self.assertEqual(response.data.intent, "start_patrol")
        self.assertFalse(response.data.accepted)
        self.assertTrue(response.data.need_confirm)
        self.assertIsNotNone(response.data.pending_command_id)
        self.assertFalse(response.data.audio_retained)
        self.assertIsNone(response.data.audio_path)
        self.assertFalse(recorded_path.exists())
        logs = persistence.list_command_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].command, "voice_audio_command")
        self.assertFalse(logs[0].accepted)
        self.assertEqual(logs[0].payload["intent"], "start_patrol")
        self.assertTrue(logs[0].payload["need_confirm"])

    async def test_record_command_recording_failure_does_not_call_asr(self) -> None:
        os.environ["ASR_BACKEND"] = "mock"
        os.environ["VOICE_MOCK_RECOGNIZED_TEXT"] = "暂停任务"
        original_recorder = main_module.audio_recorder

        class FailedRecordResult:
            success = False
            audio_path = None
            duration = 3
            audio_device = "wrong-device"
            error = "audio_record_failed"
            detail = "arecord failed: fake device"

        class FailedRecorder:
            def default_duration(self) -> int:
                return 3

            def default_keep_audio(self) -> bool:
                return True

            def record(self, duration: int) -> FailedRecordResult:
                return FailedRecordResult()

        main_module.audio_recorder = FailedRecorder()
        try:
            response = await main_module.record_command(VoiceRecordCommandRequest(duration=3))
        finally:
            main_module.audio_recorder = original_recorder

        self.assertFalse(response.success)
        self.assertEqual(response.error, "audio_record_failed")
        self.assertIsNone(response.data)
        self.assertIn("arecord failed", response.detail)

    async def test_system_mode_switch_endpoint_updates_contract_state(self) -> None:
        response = await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        latest_state = state_store.get_latest_state()

        self.assertTrue(response.success)
        self.assertEqual(response.data.system_mode.mode, "real")
        self.assertEqual(latest_state.system_mode.mode, "real")
        self.assertFalse(latest_state.device_status.online)
        self.assertEqual(latest_state.device_status.fault_code, "waiting-for-real-state")
        self.assertEqual(latest_state.nav_status.state, "offline")

    async def test_switching_back_to_mock_restores_mock_state_contract(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )

        response = await main_module.switch_system_mode(
            ModeSwitchRequest(mode="mock", source="test", requested_by="unittest")
        )
        latest_state = state_store.get_latest_state()

        self.assertTrue(response.success)
        self.assertEqual(response.data.system_mode.mode, "mock")
        self.assertEqual(latest_state.system_mode.mode, "mock")
        self.assertTrue(latest_state.device_status.online)
        self.assertEqual(latest_state.device_status.fault_code, None)
        self.assertEqual(latest_state.env_sensor.status, "mock")

    async def test_nuc_state_ingest_updates_shared_state_in_real_mode(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )

        response = await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=12.3,
                    y=4.5,
                    yaw=1.2,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-001",
                    remaining_distance=3.2,
                ),
                task_status=TaskStatus(
                    task_id="task-real-001",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=35,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=77,
                    emergency_stop=False,
                    fault_code=None,
                    online=True,
                ),
                env_sensor=EnvSensor(
                    temperature_c=26.5,
                    humidity_percent=48.2,
                    status="nominal",
                ),
                alerts=[
                    AlertEvent(
                        alert_id="alert-real-001",
                        level="warning",
                        message="NUC state injected for test.",
                        source="nuc",
                        timestamp=datetime.now(timezone.utc),
                        acknowledged=False,
                    )
                ],
                updated_at=datetime.now(timezone.utc),
            )
        )
        latest_state = state_store.get_latest_state()
        alerts = persistence.list_recent_alerts()

        self.assertTrue(response.success)
        self.assertTrue(response.data.accepted)
        self.assertTrue(response.data.state_updated)
        self.assertEqual(latest_state.system_mode.mode, "real")
        self.assertEqual(latest_state.task_status.source, "nuc")
        self.assertEqual(latest_state.nav_status.current_goal, "wp-001")
        self.assertIn("alert-real-001", [alert.alert_id for alert in alerts])
        self.assertTrue(latest_state.device_status.online)

    async def test_latest_state_reflects_rtt_derived_device_status_from_nuc_payload(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )

        await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=8.8,
                    y=6.6,
                    yaw=1.1,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-rtt-device-001",
                    remaining_distance=2.4,
                ),
                task_status=TaskStatus(
                    task_id="task-rtt-device-001",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=55,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=42,
                    emergency_stop=True,
                    fault_code="rtt-estop-active",
                    online=False,
                ),
                env_sensor=EnvSensor(
                    temperature_c=None,
                    humidity_percent=None,
                    status="offline",
                ),
                alerts=[],
                updated_at=datetime.now(timezone.utc),
            )
        )

        latest_response = await main_module.get_latest_state()

        self.assertTrue(latest_response.success)
        self.assertEqual(latest_response.data.device_status.battery_percent, 42)
        self.assertTrue(latest_response.data.device_status.emergency_stop)
        self.assertEqual(latest_response.data.device_status.fault_code, "rtt-estop-active")
        self.assertFalse(latest_response.data.device_status.online)
        self.assertIsNone(latest_response.data.env_sensor.temperature_c)
        self.assertIsNone(latest_response.data.env_sensor.humidity_percent)
        self.assertEqual(latest_response.data.env_sensor.status, "offline")
        self.assertEqual(latest_response.data.nav_status.current_goal, "wp-rtt-device-001")

    async def test_nuc_imu_update_is_available_through_latest_imu_api(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )

        response = await main_module.ingest_nuc_imu(
            NucImuUpdateRequest(
                source="rtt",
                updated_at=datetime.now(timezone.utc),
                imu=ImuSample(
                    frame_id="gimbal_pitch_odom",
                    timestamp=datetime.now(timezone.utc),
                    orientation=QuaternionSample(x=0.1, y=0.2, z=0.3, w=0.9),
                    euler_deg=EulerDegSample(yaw=12.5, pitch=-3.2, roll=0.6),
                    angular_velocity=Vector3Sample(x=0.01, y=0.02, z=0.03),
                    linear_acceleration=Vector3Sample(x=1.1, y=1.2, z=1.3),
                ),
            )
        )
        latest_imu = await main_module.get_latest_imu()

        self.assertTrue(response.success)
        self.assertTrue(response.data.accepted)
        self.assertTrue(response.data.imu_updated)
        self.assertIsNotNone(latest_imu.data)
        self.assertEqual(latest_imu.data.source, "rtt")
        self.assertEqual(latest_imu.data.imu.frame_id, "gimbal_pitch_odom")
        self.assertEqual(latest_imu.data.imu.orientation.w, 0.9)
        self.assertIsNotNone(latest_imu.data.imu.euler_deg)
        self.assertEqual(latest_imu.data.imu.euler_deg.yaw, 12.5)
        self.assertEqual(latest_imu.data.imu.angular_velocity.z, 0.03)

    async def test_switching_back_to_mock_clears_latest_imu_sample(self) -> None:
        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        await main_module.ingest_nuc_imu(
            NucImuUpdateRequest(
                source="rtt",
                updated_at=datetime.now(timezone.utc),
                imu=ImuSample(
                    frame_id="imu-link",
                    timestamp=datetime.now(timezone.utc),
                    orientation=QuaternionSample(),
                    angular_velocity=Vector3Sample(),
                    linear_acceleration=Vector3Sample(),
                ),
            )
        )

        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="mock", source="test", requested_by="unittest")
        )
        latest_imu = await main_module.get_latest_imu()

        self.assertIsNone(latest_imu.data)

    async def test_real_mode_forwards_three_commands_to_nuc_and_persists_logs(self) -> None:
        server = _FakeNucMissionServer()
        server.start()
        os.environ["NUC_BASE_URL"] = server.base_url

        try:
            await main_module.switch_system_mode(
                ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
            )

            go_to_response = await main_module.go_to_waypoint(
                GoToWaypointRequest(
                    waypoint_id="wp-real-007",
                    source="test",
                    requested_by="unittest",
                )
            )
            pause_response = await main_module.pause_mission(
                PauseMissionRequest(source="test", requested_by="unittest")
            )
            return_home_response = await main_module.return_home(
                ReturnHomeRequest(source="test", requested_by="unittest")
            )
        finally:
            server.stop()

        latest_state = state_store.get_latest_state()
        logs = persistence.list_command_logs(limit=5)

        self.assertTrue(go_to_response.data.accepted)
        self.assertTrue(pause_response.data.accepted)
        self.assertTrue(return_home_response.data.accepted)
        self.assertEqual(
            [payload["command"] for payload in server.requests],
            ["go_to_waypoint", "pause_task", "return_home"],
        )
        self.assertEqual(len(logs), 3)
        self.assertEqual(logs[0].command, "return_home")
        self.assertEqual(logs[1].payload["forwarded_command"], "pause_task")
        self.assertEqual(latest_state.system_mode.mode, "real")
        self.assertEqual(latest_state.task_status.source, "nuc")
        self.assertEqual(latest_state.nav_status.current_goal, "home")

    async def test_real_mode_returns_structured_failure_when_nuc_unreachable(self) -> None:
        os.environ["NUC_BASE_URL"] = "http://127.0.0.1:1"
        os.environ["NUC_TIMEOUT_SECONDS"] = "0.2"

        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        response = await main_module.resume_mission(
            ResumeMissionRequest(source="test", requested_by="unittest")
        )
        logs = persistence.list_command_logs(limit=5)

        self.assertTrue(response.success)
        self.assertFalse(response.data.accepted)
        self.assertIn("NUC 命令接口", response.data.detail)
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].accepted)
        self.assertEqual(logs[0].command, "resume")
        self.assertFalse(state_store.get_latest_state().device_status.online)
        self.assertEqual(state_store.get_latest_state().device_status.fault_code, "nuc-bridge-unreachable")

    async def test_real_mode_timeout_marks_state_offline_and_recovery_restores_online(self) -> None:
        os.environ["REAL_STATE_STALE_AFTER_SECONDS"] = "0"

        await main_module.switch_system_mode(
            ModeSwitchRequest(mode="real", source="test", requested_by="unittest")
        )
        await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=1.0,
                    y=2.0,
                    yaw=0.3,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-timeout",
                    remaining_distance=1.2,
                ),
                task_status=TaskStatus(
                    task_id="task-timeout-001",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=50,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=80,
                    emergency_stop=False,
                    fault_code=None,
                    online=True,
                ),
                env_sensor=EnvSensor(
                    temperature_c=24.0,
                    humidity_percent=40.0,
                    status="nominal",
                ),
                alerts=[],
                updated_at=datetime.now(timezone.utc),
            )
        )

        timed_out_state = mode_manager.poll_real_health()

        self.assertIsNotNone(timed_out_state)
        self.assertFalse(timed_out_state.device_status.online)
        self.assertEqual(timed_out_state.device_status.fault_code, "nuc-state-timeout")
        self.assertEqual(timed_out_state.nav_status.state, "offline")

        await main_module.ingest_nuc_state(
            NucStateUpdateRequest(
                robot_pose=RobotPose(
                    x=3.0,
                    y=4.0,
                    yaw=0.6,
                    frame_id="map",
                    timestamp=datetime.now(timezone.utc),
                ),
                nav_status=NavStatus(
                    mode="auto",
                    state="running",
                    current_goal="wp-recovered",
                    remaining_distance=0.8,
                ),
                task_status=TaskStatus(
                    task_id="task-timeout-002",
                    task_type="go_to_waypoint",
                    state="running",
                    progress=70,
                    source="nuc",
                ),
                device_status=DeviceStatus(
                    battery_percent=78,
                    emergency_stop=False,
                    fault_code=None,
                    online=True,
                ),
                env_sensor=EnvSensor(
                    temperature_c=25.0,
                    humidity_percent=41.0,
                    status="nominal",
                ),
                alerts=[],
                updated_at=datetime.now(timezone.utc),
            )
        )
        recovered_state = state_store.get_latest_state()

        self.assertTrue(recovered_state.device_status.online)
        self.assertEqual(recovered_state.nav_status.current_goal, "wp-recovered")
        self.assertEqual(recovered_state.device_status.fault_code, None)

    def test_mock_state_tick_updates_snapshot_history(self) -> None:
        before = main_module.mock_state_service.get_latest_state()
        after = main_module.mock_state_service.tick()

        with sqlite3.connect(persistence.db_path) as connection:
            snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM state_snapshots"
            ).fetchone()[0]

        self.assertNotEqual(before.updated_at, after.updated_at)
        self.assertNotEqual(before.device_status.battery_percent, after.device_status.battery_percent)
        self.assertGreaterEqual(snapshot_count, 2)

    @staticmethod
    def _restore_env(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
