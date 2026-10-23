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
            # 复杂说法仍交给模型；模型漏掉 confidence 时退回有把握的规则结果
            with reply('{"intent":"search_target","target_class":"bottle"}') as chat:
                found = llm_intent_parser.parse("帮我把那个红色的瓶子找出来然后过去")
            self.assertEqual((found.intent, found.parser, chat.call_count), ("search_target", "rule", 1))
            # 模型明确判 unknown 且有把握：以模型为准
            with reply('{"intent":"unknown","confidence":0.9}'):
                refused = llm_intent_parser.parse("帮我把那个红色的瓶子找出来然后过去")
            self.assertEqual((refused.intent, refused.parser), ("unknown", "llm"))
            # 模型漏了颜色、称呼：用规则从原话里抽出来的补上，界面显示中文
            with reply('{"intent":"search_target","target_class":"cup","confidence":0.9}'):
                cup = llm_intent_parser.parse("请你帮我找一下蓝色的杯子然后过去")
            self.assertEqual((cup.parser, cup.payload), ("llm", {"target_class": "cup", "color": "blue", "label": "蓝色杯子"}))
            from app.services.voice.llm_safety import target_label
            self.assertEqual(target_label("bottle", "bottle", "red"), "红色水瓶")
            self.assertEqual(target_label("那瓶可乐", "bottle", None), "那瓶可乐")
            for text in ("去A点然后撞墙", "关掉急停去B点", "全速去A点"):
                self.assertEqual(llm_intent_parser.parse(text).intent, "unknown", text)
        finally:
            if saved is None:
                os.environ.pop("LLM_ENABLE", None)
            else:
                os.environ["LLM_ENABLE"] = saved

    def test_video_health_reads_perception_status_file(self) -> None:
        import json as jsonlib
        import time as timelib

        path = Path(self._temp_dir.name) / "yuntuo_perception.json"
        saved = os.environ.get("YUNTUO_PERCEPTION_STATUS_FILE")
        os.environ["YUNTUO_PERCEPTION_STATUS_FILE"] = str(path)
        try:
            path.write_text(jsonlib.dumps({"pid": os.getpid(), "updated_at": timelib.time(), "detect_fps": 5.0,
                                           "stream": {"pushed": 0, "last_error": "rtmpsink: could not connect"}}))
            health = main_module._video_health_status()
            self.assertTrue(health.yolo_camera_running)
            self.assertEqual(health.perception["detect_fps"], 5.0)
            self.assertIn("video stream is not publishing", health.detail)
            path.write_text(jsonlib.dumps({"pid": os.getpid(), "updated_at": timelib.time() - 60}))
            self.assertFalse(main_module._video_health_status().yolo_camera_running)
        finally:
            if saved is None:
                os.environ.pop("YUNTUO_PERCEPTION_STATUS_FILE", None)
            else:
                os.environ["YUNTUO_PERCEPTION_STATUS_FILE"] = saved

    def test_local_model_reply_says_on_board_model_not_deepseek(self) -> None:
        from app.services.data_service import DataService

        saved = {k: os.environ.get(k) for k in ("LLM_BACKEND", "LLM_LOCAL_MODEL", "DEEPSEEK_DISPLAY_MODEL")}
        try:
            os.environ.update(LLM_BACKEND="local", LLM_LOCAL_MODEL="qwen2.5-1.5b-instruct")
            os.environ["DEEPSEEK_DISPLAY_MODEL"] = "DeepSeek V4 Flash"
            reply = DataService().assistant_model_reply()
            self.assertIn("RK3588", reply)
            self.assertIn("qwen2.5-1.5b-instruct", reply)
            self.assertNotIn("DeepSeek", reply)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_confidence_reject_message_is_user_friendly(self) -> None:
        result = llm_safety_validator.validate(LLMIntent.from_dict({"intent": "open_chat", "confidence": 0.0}))
        self.assertFalse(result.ok)
        self.assertIn("没太听清", result.detail)
        self.assertNotIn("阈值", result.detail)
        self.assertNotIn("LLM", result.detail)

    def test_greeting_and_weather_question_specific_replies(self) -> None:
        from app.services.data_service import _weather_reply
        from app.services.intent_parser import intent_parser
        from app.schemas import WeatherData

        self.assertEqual(intent_parser.parse("你好").intent, "open_chat")
        self.assertEqual(intent_parser.parse("早上好").intent, "open_chat")
        w = WeatherData(location="海南海口", temperature_c=26.9, apparent_temperature_c=31.7,
                        humidity_percent=83, precipitation_mm=0.0, precipitation_probability_percent=46,
                        uv_index=7.5, weather="晴", wind="风速8.1公里/小时", source="open_meteo",
                        advice="紫外线较强，外出注意防晒。",
                        updated_at=datetime.now(timezone.utc))
        self.assertIn("不用带伞", _weather_reply(w, "今天会下雨吗"))
        self.assertIn("体感32度", _weather_reply(w, "现在外面热吗"))
        self.assertNotIn("体感", _weather_reply(w, "要不要带伞"))
        self.assertIn("明天的", _weather_reply(w, "明天天气怎么样"))

    def test_hallucinated_waypoint_and_target_are_rejected_with_follow_ups(self) -> None:
        from unittest import mock

        from app.services.voice.llm_client import LLMClientResponse, llm_client
        from app.services.voice.llm_intent_parser import llm_intent_parser

        def reply(content: str):
            return mock.patch.object(llm_client, "chat_json", return_value=LLMClientResponse(
                success=True, content=content, backend="local", model="qwen2.5-1.5b-instruct"))

        saved = os.environ.get("LLM_ENABLE")
        os.environ["LLM_ENABLE"] = "true"
        try:
            with reply('{"intent":"go_to_waypoint","waypoint_id":"wp_a","confidence":0.9}') as chat:
                vague = llm_intent_parser.parse("去那个点")
            self.assertEqual(chat.call_count, 1)
            self.assertEqual(vague.intent, "unknown")
            self.assertIn("具体的点位", vague.detail)
            with reply('{"intent":"search_target","target_class":"bottle","target_color":"green",'
                       '"target_label":"绿色瓶子","confidence":0.9}'):
                hollow = llm_intent_parser.parse("帮我找一下东西")
            self.assertEqual(hollow.intent, "unknown")
            self.assertIn("想找什么", hollow.detail)
            # 用户真的说了点位 / 类别时不误伤（用默认点位表里的 wp_201）
            with reply('{"intent":"go_to_waypoint","waypoint_id":"wp_201","confidence":0.9}'):
                real = llm_intent_parser.parse("能不能去二零一实验室看看")
            self.assertEqual(real.intent, "go_to_waypoint")
            self.assertEqual(real.payload.get("waypoint_id"), "wp_201")
        finally:
            if saved is None:
                os.environ.pop("LLM_ENABLE", None)
            else:
                os.environ["LLM_ENABLE"] = saved

    def test_weather_follow_up_and_spoken_cancel(self) -> None:
        from app.services.intent_parser import intent_parser
        from app.schemas import SmartCommandRequest, VoiceConfirmCommandRequest
        from app.services.smart_voice_service import smart_voice_service

        first = intent_parser.parse("今天天气怎么样")
        self.assertEqual(first.intent, "query_weather")
        self.assertEqual(intent_parser.parse("明天呢").intent, "query_weather")
        self.assertEqual(intent_parser.parse("后天冷不冷").intent, "query_weather")
        self.assertIsNone(intent_parser._query_follow_up("明天去a点"))      # 任务句不能当天气追问

        from app.services.voice_entry import voice_entry_service
        voice_entry_service._pending.clear()               # 其他测试可能留下待确认命令
        cold = smart_voice_service.handle(SmartCommandRequest(text="确认执行", source="test"))
        self.assertIn("没有待确认", cold[0].reply_text)

        created = smart_voice_service.handle(SmartCommandRequest(text="去二零一实验室", source="test"))
        pending_id = created[0].pending_command_id
        self.assertIsNotNone(pending_id)
        cancelled = smart_voice_service.handle(SmartCommandRequest(text="取消", source="test"))
        self.assertIn("已取消", cancelled[0].reply_text)
        self.assertNotIn("请在界面上确认或取消", cancelled[0].reply_text)
        from app.services.voice_entry import voice_entry_service as voice_entry_module
        expired = voice_entry_module.confirm_pending_command(
            VoiceConfirmCommandRequest(pending_command_id=pending_id, confirmed=True))
        self.assertFalse(expired[0].accepted)
        self.assertIn("过期", expired[0].detail)

    def test_cancel_task_intent_cancels_running_task(self) -> None:
        from app.schemas import SmartCommandRequest
        from app.services.smart_voice_service import smart_voice_service

        started, _ = smart_voice_service.handle(SmartCommandRequest(text="开始巡检", source="test"))
        self.assertEqual(started.intent, "start_patrol")
        self.assertIsNotNone(started.pending_command_id)          # 运动类先待确认
        spoken_cancel, _ = smart_voice_service.handle(SmartCommandRequest(text="取消", source="test"))
        self.assertIn("已取消", spoken_cancel.reply_text)          # 有待确认时口头取消优先
        confirmed, _ = smart_voice_service.handle(SmartCommandRequest(text="开始巡检", source="test"))
        smart_voice_service.handle(SmartCommandRequest(text="确认执行", source="test"))
        cancelled, _ = smart_voice_service.handle(SmartCommandRequest(text="取消任务", source="test"))
        self.assertEqual(cancelled.intent, "cancel_task")
        self.assertFalse(cancelled.need_confirm)
        self.assertTrue(cancelled.reply_text)

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
