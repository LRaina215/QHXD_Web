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
        return (
            "导航和运动控制都在 FPGA 上跑，我能去指定地点、按路线巡检，也能适应台阶、斜坡和碎石地形。"
            "视觉上用 RGB-D 相机识别目标并测距，可以帮你找指定的东西（比如红色水瓶）停在旁边，或者跟着你走。"
            "你直接说话就行，运动类任务我会先跟你确认。"
        )

    def safety_reply(self) -> str:
        profile = self.get_profile()
        return (
            "我不能直接控制底盘速度——速度由 FPGA 导航限幅后交给 FPGA 运动控制。"
            "你下的每个运动指令都会先过本地安全校验，再经你确认才执行；目标不明确时我会先问你。"
            "任何时候急停都优先于任务。"
        )


profile_provider = ProfileProvider()
