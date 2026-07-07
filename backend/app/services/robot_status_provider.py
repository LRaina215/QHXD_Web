from datetime import datetime, timezone

from app.schemas import AlertEvent, RobotState, TaskStatus
from app.services.mock_state import mock_state_service
from app.services.navigation_store import navigation_store
from app.services.persistence import persistence
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
        events = persistence.list_task_events(limit=3, task_id=None if task.task_id == "mock-task" else task.task_id)
        event_text = "；".join(event.detail for event in events[:3]) if events else "暂无任务事件记录"
        return (
            f"当前任务为 {task.task_type}，状态 {task.state}，进度 {task.progress}%，来源 {task.source}。"
            f"最近事件：{event_text}。"
        )

    def navigation_reply(self) -> str:
        state = self.latest_state()
        nav = state.nav_status
        snapshot = navigation_store.latest()
        if snapshot is None:
            return f"当前导航状态为 {nav.state}，还没有收到导航地图或定位快照。"

        age = (datetime.now(timezone.utc) - snapshot.timestamp).total_seconds()
        age_text = f"{age:.1f}秒前"
        if snapshot.pose is None:
            return f"当前导航状态为 {nav.state}，最近导航快照在{age_text}更新，但暂未获得 map 到车体位姿。"

        goal_text = f"目标点 {nav.current_goal}" if nav.current_goal else "当前没有明确目标点"
        distance_text = f"，剩余距离约 {nav.remaining_distance:.2f} 米" if nav.remaining_distance is not None else ""
        path_text = f"，全局路径 {len(snapshot.global_path)} 个点，局部路径 {len(snapshot.local_path)} 个点"
        stale_text = "，导航数据可能过期" if age > 3 else ""
        return (
            f"当前已定位，导航状态 {nav.state}，{goal_text}{distance_text}{path_text}。"
            f"最近导航快照更新于{age_text}{stale_text}。"
        )

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
        objects = self._objects_text(detection.objects)
        live_events = "、".join(event.message for event in detection.events[:3])
        persisted = persistence.list_visual_events(limit=3)
        history = "、".join(f"{event.message}（{self._age_text(event.last_seen_at)}）" for event in persisted)
        event_text = live_events or history or "暂无视觉事件"
        age = self._age_text(detection.timestamp)
        return f"视觉来源 {detection.source}，画面更新于{age}，最近目标：{objects}；最近事件：{event_text}。"

    def front_status_reply(self) -> str:
        state = self.latest_state()
        detection = state.detection_status
        snapshot = navigation_store.latest()
        nav = state.nav_status

        if detection is None:
            return "当前没有前方视觉数据，无法判断前方状况。"

        detection_age = (datetime.now(timezone.utc) - detection.timestamp).total_seconds()
        if detection_age > 5:
            return f"当前视觉数据已过期，最后一帧来自 {detection.source}，更新时间为{self._age_text(detection.timestamp)}。"
        if not detection.enabled:
            return "当前相机或视觉检测链路不可用，无法查看前方画面。"

        objects = self._objects_text(detection.objects)
        people = [obj for obj in detection.objects if obj.class_name == "person"]
        obstacles = [obj for obj in detection.objects if obj.class_name in {"chair", "backpack", "suitcase", "box", "bottle", "traffic cone", "obstacle"}]
        recent_events = persistence.list_visual_events(limit=3)
        event_text = "；".join(f"{event.message}（{self._age_text(event.last_seen_at)}）" for event in recent_events)

        risk: list[str] = []
        if people:
            risk.append(f"当前帧检测到人员 {len(people)} 个")
        if obstacles:
            classes = "、".join(sorted({item.class_name for item in obstacles}))
            risk.append(f"当前帧检测到可能障碍物：{classes}")
        if not risk and recent_events:
            risk.append("当前帧未见明显目标，但最近有视觉事件记录")
        if not risk:
            risk.append("当前帧未检测到人员或常见障碍物")

        nav_text = f"导航状态 {nav.state}"
        if nav.current_goal:
            nav_text += f"，目标 {nav.current_goal}"
        if nav.remaining_distance is not None:
            nav_text += f"，剩余约 {nav.remaining_distance:.2f} 米"
        if snapshot is not None and snapshot.pose is None:
            nav_text += "，定位暂未就绪"

        recommendation = "建议继续保持观察，不要把视觉识别当作直接避障控制。"
        if people or obstacles:
            recommendation = "建议减速观察或等待前方目标离开；我不会直接替代 Nav2 避障控制。"

        return (
            f"{nav_text}。前方视觉更新于{self._age_text(detection.timestamp)}，{'; '.join(risk)}。"
            f"当前目标摘要：{objects}。"
            f"{'最近事件：' + event_text + '。' if event_text else ''}{recommendation}"
        )

    @staticmethod
    def _objects_text(objects) -> str:
        return "、".join(f"{obj.class_name} {obj.confidence:.2f}" for obj in objects[:5]) or "当前没有检测到目标"

    @staticmethod
    def _age_text(timestamp: datetime) -> str:
        seconds = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())
        if seconds < 1:
            return "刚刚"
        if seconds < 60:
            return f"{seconds:.0f}秒前"
        return f"{seconds / 60:.1f}分钟前"


robot_status_provider = RobotStatusProvider()
