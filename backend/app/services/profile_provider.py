import json
from pathlib import Path

from app.schemas import RobotProfile


class ProfileProvider:
    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or Path(__file__).resolve().parents[1] / "config" / "robot_profile.json"

    def get_profile(self) -> RobotProfile:
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        return RobotProfile(**data)

    def identity_reply(self) -> str:
        profile = self.get_profile()
        return profile.self_intro

    def capability_reply(self) -> str:
        profile = self.get_profile()
        abilities = "、".join(profile.abilities)
        return f"我是{profile.full_name}，当前能力包括：{abilities}。"

    def safety_reply(self) -> str:
        profile = self.get_profile()
        rules = "；".join(profile.safety_rules)
        return f"我的安全规则是：{rules}。我不能直接控制底盘速度，运动类任务必须经过确认和本地安全校验。"


profile_provider = ProfileProvider()
