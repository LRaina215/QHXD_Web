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


if __name__ == "__main__":
    unittest.main()
