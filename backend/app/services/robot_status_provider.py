import json
import os
from datetime import datetime, timezone

from app.schemas import AlertEvent, RobotState, TaskStatus
from app.services.mock_state import mock_state_service
from app.services.navigation_store import navigation_store
from app.services.persistence import persistence
from app.services.state_store import state_store
from app.services.voice.llm_client import llm_client


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

    def front_status_reply(self, question: str | None = None, *, use_llm: bool = True) -> str:
        context = self.front_status_context()
        if use_llm:
            llm_reply = self._front_status_llm_reply(question or "现在导航前方有什么", context)
            if llm_reply:
                return llm_reply
        return self._front_status_fallback_reply(context)

    def front_status_context(self) -> dict:
        state = self.latest_state()
        detection = state.detection_status
        snapshot = navigation_store.latest()
        nav = state.nav_status
        task = state.task_status
        now = datetime.now(timezone.utc)
        recent_events = persistence.list_visual_events(limit=5)

        context: dict = {
            "vision": {
                "status": "unavailable",
                "freshness": "unavailable",
                "objects": [],
                "recent_events": [self._visual_event_context(event, now) for event in recent_events],
            },
            "navigation": {
                "state": nav.state,
                "current_goal": nav.current_goal,
                "remaining_distance_m": nav.remaining_distance,
                "pose_ready": snapshot.pose is not None if snapshot is not None else False,
                "global_path_points": len(snapshot.global_path) if snapshot is not None else 0,
                "local_path_points": len(snapshot.local_path) if snapshot is not None else 0,
            },
            "task": {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "state": task.state,
                "progress": task.progress,
                "source": task.source,
            },
            "safety_boundary": "回答只能用于观察和建议，不能替代 Nav2 避障，也不能直接生成控制命令。",
        }

        if detection is None:
            return context

        detection_age = max(0.0, (now - detection.timestamp).total_seconds())
        fresh_seconds = self._front_status_fresh_seconds()
        recent_seconds = self._front_status_recent_seconds()
        freshness = "fresh"
        if detection_age > recent_seconds:
            freshness = "stale"
        elif detection_age > fresh_seconds:
            freshness = "recent"

        objects = [
            {
                "class_name": obj.class_name,
                "confidence": round(obj.confidence, 4),
                "current_frame": obj.current_frame,
                "recently_seen": obj.recently_seen,
                "age_s": obj.age_s,
            }
            for obj in detection.objects[:8]
        ]
        people_count = sum(1 for obj in detection.objects if obj.class_name == "person")
        obstacle_classes = sorted(
            {
                obj.class_name
                for obj in detection.objects
                if obj.class_name in {"chair", "backpack", "suitcase", "box", "bottle", "traffic cone", "obstacle"}
            }
        )

        context["vision"].update(
            {
                "status": "available" if detection.enabled else "disabled",
                "freshness": freshness,
                "age_s": round(detection_age, 2),
                "objects": objects,
                "people_count": people_count,
                "obstacle_classes": obstacle_classes,
                "live_events": [
                    {"event_type": event.event_type, "level": event.level, "message": event.message}
                    for event in detection.events[:5]
                ],
            }
        )
        return context

    def _front_status_fallback_reply(self, context: dict) -> str:
        vision = context["vision"]
        nav = context["navigation"]
        recent_events = vision.get("recent_events", [])

        if vision["status"] == "unavailable":
            history = self._event_context_text(recent_events)
            return f"我现在还没有拿到稳定的前方画面。{history or '最近也没有可用的视觉事件记录。'}"
        if vision["status"] == "disabled":
            return "当前相机或视觉检测链路不可用，无法查看前方画面。"

        object_text = self._object_context_text(vision.get("objects", []))
        people_count = int(vision.get("people_count") or 0)
        obstacle_classes = list(vision.get("obstacle_classes") or [])

        risk: list[str] = []
        if people_count:
            risk.append(f"前方检测到人员 {people_count} 个")
        if obstacle_classes:
            risk.append(f"前方检测到可能障碍物：{'、'.join(obstacle_classes)}")
        if not risk and recent_events:
            risk.append("当前画面未见明显目标，但最近有视觉事件记录")
        if not risk:
            risk.append("当前未检测到人员或常见障碍物")

        nav_text = f"导航状态 {nav['state']}"
        if nav.get("current_goal"):
            nav_text += f"，目标 {nav['current_goal']}"
        if nav.get("remaining_distance_m") is not None:
            nav_text += f"，剩余约 {nav['remaining_distance_m']:.2f} 米"
        if not nav.get("pose_ready"):
            nav_text += "，定位暂未就绪"

        if vision.get("freshness") == "stale":
            history = self._event_context_text(recent_events)
            return f"我现在无法可靠确认前方实时画面。{history or '最近没有可用的视觉事件记录。'}"

        recommendation = "建议继续保持观察。"
        if people_count or obstacle_classes:
            recommendation = "建议先减速或暂停观察，确认通道安全后再继续。"

        return (
            f"{nav_text}。{'; '.join(risk)}。"
            f"{'目标摘要：' + object_text + '。' if object_text else ''}{recommendation}"
        )

    def _front_status_llm_reply(self, question: str, context: dict) -> str | None:
        if os.getenv("FRONT_STATUS_LLM_ENABLE", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return None

        system_prompt = (
            "你是琼海芯动灵巡机器人的车载智能助手。"
            "请只根据给定 JSON 上下文回答用户关于前方、导航安全或障碍物的问题。"
            "正常情况下不要提更新时间、数据来源、接口名、detection_status、YOLO、rk3588、时间戳或模型名。"
            "只有当 vision.freshness=stale 或 vision.status 不是 available 时，才用自然语言说明现在无法可靠查看前方画面，并结合最近事件说明。"
            "回答要简短自然，1 到 3 句话。"
            "可以给出减速、暂停观察、等待通道清空等建议，但不能声称已经控制机器人，也不能生成新的运动命令。"
            "不要编造上下文里没有的目标、人、障碍物或距离。"
        )
        payload = {
            "question": question,
            "context": context,
        }
        response = llm_client.chat_text(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        if not response.success or not response.content:
            return None
        reply = response.content.strip()
        if not reply:
            return None
        return reply[:400]

    @staticmethod
    def _object_context_text(objects: list[dict]) -> str:
        return "、".join(f"{item['class_name']} {item['confidence']:.2f}" for item in objects[:5])

    @staticmethod
    def _event_context_text(events: list[dict]) -> str:
        if not events:
            return ""
        return "最近看到：" + "；".join(str(event.get("message") or event.get("event_type")) for event in events[:3]) + "。"

    def _visual_event_context(self, event, now: datetime) -> dict:
        return {
            "event_type": event.event_type,
            "level": event.level,
            "class_name": event.class_name,
            "message": event.message,
            "age_s": round(max(0.0, (now - event.last_seen_at).total_seconds()), 2),
            "duration_s": round(event.duration_s, 2),
            "max_confidence": event.max_confidence,
            "count": event.count,
        }

    @staticmethod
    def _front_status_fresh_seconds() -> float:
        try:
            return max(1.0, float(os.getenv("FRONT_STATUS_FRESH_SECONDS", "15")))
        except ValueError:
            return 15.0

    @staticmethod
    def _front_status_recent_seconds() -> float:
        try:
            return max(RobotStatusProvider._front_status_fresh_seconds(), float(os.getenv("FRONT_STATUS_RECENT_SECONDS", "60")))
        except ValueError:
            return 60.0

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
