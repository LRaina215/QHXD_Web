from app.schemas import AlertEvent, RobotState, TaskStatus
from app.services.mock_state import mock_state_service
from app.services.state_store import state_store


class RobotStatusProvider:
    def latest_state(self) -> RobotState:
        return state_store.get_latest_state()

    def current_task(self) -> TaskStatus:
        return state_store.get_current_task()

    def alerts(self) -> list[AlertEvent]:
        return mock_state_service.get_alerts()

    def robot_status_reply(self) -> str:
        state = self.latest_state()
        device = state.device_status
        task = state.task_status
        nav = state.nav_status
        faults: list[str] = []
        if not device.online:
            faults.append("机器人链路离线")
        if device.emergency_stop:
            faults.append("急停已触发")
        if device.fault_code:
            faults.append(f"故障码 {device.fault_code}")
        fault_text = "，".join(faults) if faults else "未发现急停或故障"
        return (
            f"当前模式 {state.system_mode.mode}，任务状态 {task.task_type}/{task.state}，"
            f"导航状态 {nav.state}，{fault_text}。"
        )

    def task_reply(self) -> str:
        task = self.current_task()
        return f"当前任务为 {task.task_type}，状态 {task.state}，进度 {task.progress}%，来源 {task.source}。"

    def battery_reply(self) -> str:
        battery = self.latest_state().device_status.battery_percent
        if battery is None:
            return "当前没有电量数据。"
        return f"当前电量约 {battery}%。"

    def emergency_stop_reply(self) -> str:
        device = self.latest_state().device_status
        return "当前急停已触发，请人工检查。" if device.emergency_stop else "当前未触发急停。"

    def perception_reply(self) -> str:
        detection = self.latest_state().detection_status
        if detection is None:
            return "当前没有视觉检测状态。"
        objects = "、".join(f"{obj.class_name} {obj.confidence:.2f}" for obj in detection.objects[:5]) or "当前没有检测到目标"
        events = "、".join(event.message for event in detection.events[:3]) or "暂无视觉事件"
        return f"视觉来源 {detection.source}，最近目标：{objects}；最近事件：{events}。"


robot_status_provider = RobotStatusProvider()
