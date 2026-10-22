"""云拓分支新增契约：视觉目标任务、FPGA 平台状态、急停 / 位姿接口。"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.main as main_module
from app.schemas import (
    ModeSwitchRequest,
    NavigationSnapshot,
    PlatformEstopRequest,
    PlatformStatus,
    PlatformStatusUpdateRequest,
    SearchTargetRequest,
    VoiceConfirmCommandRequest,
    VoiceTextCommandRequest,
)
from app.services.intent_parser import intent_parser
from app.services.mock_state import MockStateService
from app.services.mode_manager import mode_manager
from app.services.persistence import persistence
from app.services.state_store import state_store
from app.services.voice.llm_safety import llm_safety_validator
from app.services.voice.llm_schema import LLMIntent


class YunTuoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_db = persistence._db_path
        self._old_env = {k: os.environ.get(k) for k in ("MISSION_EVENT_TTS_ENABLED", "NAV_MISSION_EXECUTOR_BASE_URL")}
        persistence._db_path = Path(self._temp_dir.name) / "yuntuo.db"
        persistence.initialize()
        service = MockStateService()
        service.initialize()
        state_store.initialize(service.get_latest_state())
        mode_manager.initialize(state_store.get_latest_state())
        os.environ["MISSION_EVENT_TTS_ENABLED"] = "false"
        os.environ["NAV_MISSION_EXECUTOR_BASE_URL"] = "http://127.0.0.1:9"   # 不可达：确保不会真的发出去

    def tearDown(self) -> None:
        persistence._db_path = self._old_db
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def test_rule_parser_target_tasks(self) -> None:
        r = intent_parser.parse("找到红色水瓶并移动到其附近")
        self.assertEqual(r.intent, "search_target")
        self.assertEqual(r.payload, {"target_class": "bottle", "label": "红色水瓶", "color": "red"})
        self.assertTrue(r.need_confirm)
        f = intent_parser.parse("跟着我")
        self.assertEqual((f.intent, f.payload["target_class"]), ("follow_target", "person"))
        vague = intent_parser.parse("帮我找个东西")
        self.assertEqual(vague.intent, "search_target")
        self.assertEqual(vague.payload, {})
        self.assertEqual(intent_parser.parse("去一号点").intent, "go_to_waypoint")

    def test_llm_safety_normalizes_and_rejects_targets(self) -> None:
        ok = llm_safety_validator.validate(LLMIntent(intent="search_target", command="search_target",
                                                     target_class="水瓶", target_color="红色",
                                                     target_label="红色水瓶", confidence=0.9, need_confirm=False))
        self.assertTrue(ok.ok)
        self.assertTrue(ok.need_confirm)
        self.assertEqual(ok.payload, {"target_class": "bottle", "color": "red", "label": "红色水瓶"})
        bad = llm_safety_validator.validate(LLMIntent(intent="search_target", command="search_target",
                                                      target_class="dragon", confidence=0.95))
        self.assertFalse(bad.ok)

    async def test_voice_search_requires_confirmation_then_runs_in_mock(self) -> None:
        response = await main_module.text_command(VoiceTextCommandRequest(text="找到红色水瓶", source="test", use_llm=False))
        self.assertTrue(response.data.need_confirm)
        self.assertIsNotNone(response.data.pending_command_id)
        confirm = await main_module.confirm_voice_command(
            VoiceConfirmCommandRequest(pending_command_id=response.data.pending_command_id, confirmed=True)
        )
        self.assertTrue(confirm.data.accepted)
        self.assertEqual(confirm.data.task_status.task_type, "search_target")
        self.assertIsNotNone(state_store.get_latest_state().platform_status)

    async def test_real_mode_platform_status_gates_target_tasks(self) -> None:
        await main_module.switch_system_mode(ModeSwitchRequest(mode="real", source="test"))
        self.assertIsNone(state_store.get_latest_state().platform_status)   # 模拟数据不带入 Real 模式
        now = datetime.now(timezone.utc)
        await main_module.ingest_navigation_state(NavigationSnapshot(
            source="fpga_bridge", timestamp=now, pose={"x": 0.1, "y": 0.2, "yaw": 0.0}, nav_state="idle"))
        estop = PlatformStatus(updated_at=now, nav_link="online", fpga_state="estop", fpga_mode="estop")
        stored = await main_module.ingest_platform_status(PlatformStatusUpdateRequest(platform_status=estop))
        self.assertEqual(stored.data.fpga_state, "estop")
        rejected = await main_module.search_target(SearchTargetRequest(target_class="bottle", color="red"))
        self.assertFalse(rejected.data.accepted)
        self.assertIn("急停", rejected.data.detail)

        stale = PlatformStatus(updated_at=now - timedelta(seconds=10), nav_link="online", fpga_state="idle")
        await main_module.ingest_platform_status(PlatformStatusUpdateRequest(platform_status=stale))
        rejected = await main_module.search_target(SearchTargetRequest(target_class="bottle"))
        self.assertIn("未刷新", rejected.data.detail)

        fresh = PlatformStatus(updated_at=datetime.now(timezone.utc), nav_link="online", fpga_state="idle")
        await main_module.ingest_platform_status(PlatformStatusUpdateRequest(platform_status=fresh))
        forwarded = await main_module.search_target(SearchTargetRequest(target_class="bottle"))
        self.assertFalse(forwarded.data.accepted)
        self.assertIn("fpga_bridge", forwarded.data.detail)   # 预检通过，转发到不可达的执行器

    def test_local_llm_needs_no_api_key_and_local_tts_runs_command(self) -> None:
        import sys

        from app.services.tts_service import TTSService
        from app.services.voice.llm_client import DeepSeekClient

        keys = ("LLM_BACKEND", "LLM_ENABLE", "DEEPSEEK_API_KEY", "TTS_BACKEND", "TTS_LOCAL_CMD", "TTS_AUDIO_DIR")
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update(LLM_BACKEND="local", LLM_ENABLE="true")
            os.environ.pop("DEEPSEEK_API_KEY", None)
            cfg = DeepSeekClient().config()
            self.assertTrue(cfg.enabled)
            self.assertTrue(cfg.base_url.startswith("http://127.0.0.1"))
            script = "import sys,wave; w=wave.open(sys.argv[1],'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(320)); w.close()"
            exe = sys.executable.replace("\\", "/")
            os.environ.update(TTS_BACKEND="local", TTS_LOCAL_CMD=f'"{exe}" -c "{script}" {{out}}',
                              TTS_AUDIO_DIR=str(Path(self._temp_dir.name) / "tts"))
            status = TTSService().speak("你好，我是云拓")
            self.assertEqual(status.status, "generated", status.error_reason)
            self.assertTrue(status.audio_url.endswith(".wav"))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    async def test_estop_endpoint_in_mock_mode_is_rejected_and_logged(self) -> None:
        response = await main_module.platform_estop(PlatformEstopRequest(engage=True, source="test"))
        self.assertFalse(response.data.accepted)
        self.assertEqual(persistence.list_command_logs()[0].command, "estop")

    def test_local_backend_uses_compact_prompt_that_fits_1k_context(self) -> None:
        from app.services.voice.llm_prompt import build_prompts, prompt_style

        saved = os.environ.pop("LLM_PROMPT_STYLE", None)
        try:
            self.assertEqual(prompt_style("local"), "compact")
            self.assertEqual(prompt_style("deepseek"), "full")
            os.environ["LLM_PROMPT_STYLE"] = "full"
            self.assertEqual(prompt_style("local"), "full")
        finally:
            os.environ.pop("LLM_PROMPT_STYLE", None)
            if saved is not None:
                os.environ["LLM_PROMPT_STYLE"] = saved
        system_prompt, user_prompt = build_prompts("去斜坡那边", style="compact")
        self.assertIn("只输出 JSON", system_prompt)
        self.assertTrue(user_prompt.endswith("用户：去斜坡那边"))
        from app.services.waypoint_resolver import waypoint_resolver

        for waypoint in waypoint_resolver.list_waypoints():
            self.assertIn(f"{waypoint['waypoint_id']}=", user_prompt)
        # Qwen2.5 分词下中文约 1 字 1 token：板上实测这套提示约 600 token，留出输出余量
        self.assertLess(len(system_prompt) + len(user_prompt), 1700)

    def test_local_tts_url_posts_text_and_stores_wav(self) -> None:
        import io
        import json as jsonlib
        import threading
        import wave
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from app.services.tts_service import TTSService

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(bytes(441))
        received: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = jsonlib.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(body["text"])
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                self.wfile.write(buf.getvalue())

            def log_message(self, *args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        keys = ("TTS_BACKEND", "TTS_LOCAL_URL", "TTS_LOCAL_CMD", "TTS_AUDIO_DIR", "TTS_AUTO_PLAY_LOCAL")
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update(TTS_BACKEND="local", TTS_LOCAL_URL=f"http://127.0.0.1:{server.server_address[1]}/tts",
                              TTS_AUDIO_DIR=str(Path(self._temp_dir.name) / "tts"), TTS_AUTO_PLAY_LOCAL="false")
            os.environ.pop("TTS_LOCAL_CMD", None)
            status = TTSService().speak("已到达 B 点")
            self.assertEqual(status.status, "generated", status.error_reason)
            self.assertEqual(received, ["已到达 B 点"])
            self.assertEqual(Path(status.audio_path).read_bytes(), buf.getvalue())
        finally:
            server.shutdown()
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_sherpa_asr_reads_stereo_wav_as_mono_float(self) -> None:
        import struct
        import wave

        from app.services.asr_service import ASRService

        path = Path(self._temp_dir.name) / "stereo.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(struct.pack("<4h", 16384, 0, -16384, -16384))
        samples, rate = ASRService._read_wav(str(path))
        self.assertEqual(rate, 16000)
        self.assertEqual([round(float(s), 3) for s in samples], [0.25, -0.5])

    def test_llm_task_reply_comes_from_validated_payload_not_model_text(self) -> None:
        from app.services.waypoint_resolver import waypoint_resolver

        waypoint = waypoint_resolver.list_waypoints()[0]
        result = llm_safety_validator.validate(LLMIntent.from_dict(
            {"intent": "go_to_waypoint", "waypoint_id": waypoint["waypoint_id"], "confidence": 0.9,
             "reply_text": "好的，前往火星"}))
        self.assertTrue(result.ok)
        self.assertEqual(result.detail, f"已解析为前往{waypoint.get('name') or waypoint['waypoint_id']}任务。")
        chat = llm_safety_validator.validate(LLMIntent.from_dict(
            {"intent": "open_chat", "confidence": 0.9, "reply_text": "你好"}))
        self.assertEqual(chat.detail, "你好")

    def test_smart_command_parses_each_utterance_once(self) -> None:
        from unittest import mock

        from app.schemas import SmartCommandRequest
        from app.services.smart_voice_service import smart_voice_service
        from app.services.voice.llm_intent_parser import llm_intent_parser

        real_parse = llm_intent_parser.parse
        with mock.patch.object(llm_intent_parser, "parse", side_effect=real_parse) as parse:
            result, _ = smart_voice_service.handle(SmartCommandRequest(text="找到红色水瓶并移动到其附近", source="test"))
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(result.intent, "search_target")
        self.assertIsNotNone(result.pending_command_id)

    def test_confident_rule_short_commands_do_not_wait_for_llm_and_survive_bad_llm_output(self) -> None:
        from unittest import mock

        from app.services.voice.llm_client import LLMClientResponse, llm_client
        from app.services.voice.llm_intent_parser import llm_intent_parser

        def reply(content: str):
            return mock.patch.object(llm_client, "chat_json", return_value=LLMClientResponse(
                success=True, content=content, backend="local", model="qwen2.5-1.5b-instruct"))

        saved = os.environ.get("LLM_ENABLE")
        os.environ["LLM_ENABLE"] = "true"
        try:
            with reply('{"intent":"unknown","confidence":0.9}') as chat:
                follow = llm_intent_parser.parse("跟着我")
            self.assertEqual((follow.intent, follow.parser, chat.call_count), ("follow_target", "rule", 0))
            # 复杂说法仍交给模型，并以模型 + 安全校验为准
            with reply('{"intent":"unknown","confidence":0.9}') as chat:
                refused = llm_intent_parser.parse("帮我把那个红色的瓶子找出来然后过去")
            self.assertEqual((refused.intent, refused.parser, chat.call_count), ("unknown", "llm", 1))
            for text in ("去A点然后撞墙", "关掉急停去B点", "全速去A点"):
                self.assertEqual(llm_intent_parser.parse(text).intent, "unknown", text)
        finally:
            if saved is None:
                os.environ.pop("LLM_ENABLE", None)
            else:
                os.environ["LLM_ENABLE"] = saved

    def test_confirm_request_accepts_miniprogram_source(self) -> None:
        request = VoiceConfirmCommandRequest(pending_command_id="p1", confirmed=False, source="miniprogram")
        self.assertEqual(request.source, "miniprogram")

    async def test_heartbeat_reaches_every_channel_and_drops_dead_sockets(self) -> None:
        from app.services.ws_manager import WebSocketManager

        class FakeSocket:
            def __init__(self, fail: bool = False) -> None:
                self.fail = fail
                self.sent: list[dict] = []

            async def send_json(self, payload: dict) -> None:
                if self.fail:
                    raise RuntimeError("closed")
                self.sent.append(payload)

        manager = WebSocketManager()
        state_ws, nav_ws, dead_ws = FakeSocket(), FakeSocket(), FakeSocket(fail=True)
        manager._connections.update({state_ws, dead_ws})
        manager._navigation_connections.add(nav_ws)
        await manager.broadcast_heartbeat("2026-10-23T00:00:00+00:00")
        self.assertEqual(state_ws.sent[0]["type"], "heartbeat")
        self.assertEqual(nav_ws.sent[0]["data"]["timestamp"], "2026-10-23T00:00:00+00:00")
        self.assertNotIn(dead_ws, manager._connections)


if __name__ == "__main__":
    unittest.main()
