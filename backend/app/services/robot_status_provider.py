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
        if not device.online:
            return "我现在和机器人的链路断了，先帮我检查一下连接。"
        if device.emergency_stop:
            return "机器人现在处于急停状态，先人工处理一下再继续。"
        if device.fault_code:
            return f"机器人报故障了（故障码 {device.fault_code}），先看一眼再动。"
        return "机器人现在正常，没有急停，也没报故障。"

    def status_reply(self, question: str | None = None) -> str:
        """“你的状态怎么样”这类开放状态问题：把 FPGA 遥测 + 任务 + 视觉 + 电量打包给本地大模型组织语言，
        模型不可用时退回确定性摘要（比单句“正常”信息多）。"""
        context = self.status_context()
        if os.getenv("STATUS_LLM_ENABLE", "true").strip().lower() in {"1", "true", "yes", "on"}:
            llm_reply = self._status_llm_reply(question or "你的状态怎么样", context)
            if llm_reply:
                return llm_reply
        return self._status_fallback_reply(context)

    def status_context(self) -> dict:
        state = self.latest_state()
        platform = state.platform_status
        detection = state.detection_status
        task = state.task_status
        now = datetime.now(timezone.utc)
        motion: dict = {}
        if platform is not None:
            motion = {
                "fpga_link": platform.nav_link,
                "fpga_mode": platform.fpga_mode, "fpga_state": platform.fpga_state,
                "loc_state": platform.loc_state, "loc_quality_percent": platform.loc_quality,
                "cmd_speed_mps": platform.cmd_vx_mps, "cmd_turn_radps": platform.cmd_wz_radps,
                "estop": platform.control_estop or state.device_status.emergency_stop,
                "faults": platform.control_faults or [],
                "pitch_deg": platform.pitch_deg, "roll_deg": platform.roll_deg,
                "body_height_cmd_m": platform.height_cmd_m,
                "telemetry_rate_hz": platform.telemetry_rate_hz,
            }
        detection_objects = []
        if detection is not None:
            age_s = max(0.0, (now - detection.timestamp).total_seconds())
            detection_objects = [
                {"class_name": obj.class_name, "color": obj.color, "distance_m": obj.distance_m}
                for obj in detection.objects[:6]
            ]
            motion["vision_fresh"] = age_s <= 5.0
        # 短键 + 去 None：板上模型的预填 token 数直接决定首字延迟，上下文越短答得越快
        slim_motion = {k: v for k, v in motion.items() if v not in (None, [], False)}
        snapshot = navigation_store.latest()
        pos = None
        if snapshot is not None and snapshot.pose is not None:
            pos = {"x": round(snapshot.pose.x, 2), "y": round(snapshot.pose.y, 2)}
        nav = state.nav_status
        return {
            "mode": state.system_mode.mode,
            "task": {"type": task.task_type, "state": task.state, "prog": task.progress},
            "fpga": slim_motion,
            "nav": {"goal": nav.current_goal, "remain_m": nav.remaining_distance, "pos": pos},
            "bat": state.device_status.battery_percent,
            "see": {"objs": [{"c": o["class_name"], "color": o["color"], "d": o["distance_m"]}
                             for o in detection_objects][:5],
                    "persons": sum(1 for o in detection_objects if o["class_name"] == "person")},
            "ev": [e.message[:40] for e in persistence.list_visual_events(limit=2)],
        }

    def _status_llm_reply(self, question: str, context: dict) -> str | None:
        system_prompt = (
            "你是云拓轮腿机器人的车载助手。用户问你的状态时，只根据给定 JSON 上下文回答，"
            "涵盖：正在做什么任务(task)、是否在动(fpga.vx)、定位是否可靠(fpga.loc)、在哪/去哪(nav.pos/nav.goal/nav.remain_m)、"
            "看到了什么(see.objs)，有异常必须提醒。用户问在哪，就只说坐标数字，例如“在场地坐标 0.15、0.0 米处”，不要出现 nav.pos 这类字段名。"
            "2 到 4 句话，口语化，不要罗列字段名、接口名、频率、时间戳或模型名，不要编造上下文里没有的东西，"
            "不能声称已经执行了什么动作。出现数字时必须原样照抄上下文里的数字，不许换算或估读。"
            "不要提电量或电池，电量由系统另行播报。有故障、急停时必须明确说出来。"
        )
        response = llm_client.chat_text(
            system_prompt=system_prompt,
            user_prompt=json.dumps({"question": question, "context": context}, ensure_ascii=False,
                                   separators=(",", ":")),
        )
        if not response.success or not response.content:
            return None
        reply = response.content.strip()
        # 小模型对电量数字不稳（实测同一上下文一次 86% 一次“低于20%”）：模型说的电量句子一律丢弃
        import re
        reply = "".join(part for part in re.split(r"(?<=[。！？])", reply) if part.strip()
                        and not re.search(r"电量|电池|充电", part))   # 分句保留原标点，直接拼接
        battery = context.get("battery_percent", context.get("bat"))
        if isinstance(battery, (int, float)):
            reply += f"电量 {battery:.0f}%。" + ("有点低了，记得充电。" if battery < 20 else "")
        return reply[:320] if reply else None

    def _status_fallback_reply(self, context: dict) -> str:
        task = context["task"]
        motion = context.get("fpga", context.get("motion", {}))
        parts = []
        if task.get("state") in {"running", "pending"}:
            prog = f"（{task.get('prog', task.get('progress'))}%）" if task.get("prog", task.get("progress")) else ""
            parts.append(f"正在执行{task['type']}{prog}")
        elif task.get("state") == "paused":
            parts.append("任务暂停中")
        else:
            parts.append("没有在跑的任务")
        speed = motion.get("cmd_speed_mps", motion.get("vx"))
        if isinstance(speed, (int, float)) and abs(speed) > 0.05:
            parts.append(f"正在以约 {speed:.2f} 米每秒移动")
        loc = motion.get("loc_state", motion.get("loc"))
        if loc == "ok":
            parts.append("定位正常")
        elif loc in {"degraded", "lost"}:
            parts.append(f"定位{ '退化' if loc == 'degraded' else '丢失' }，走慢点")
        raw_objects = context.get("see", {}).get("objs", context.get("vision", {}).get("objects", []))
        objects = [{"class_name": o.get("c", o.get("class_name"))} for o in raw_objects]
        if objects:
            names = "、".join(sorted({o["class_name"] for o in objects}))
            parts.append(f"现在能看到{names}")
        battery = context.get("battery_percent", context.get("bat"))
        if isinstance(battery, (int, float)):
            parts.append(f"电量 {battery:.0f}%")
        if motion.get("estop"):
            return "现在处于急停状态，先处理急停再继续。"
        if motion.get("faults"):
            return f"控制侧有故障标志（{ '、'.join(motion['faults'][:3]) }），建议先检查。"
        return "，".join(parts) + "。"

    def task_reply(self) -> str:
        task = self.current_task()
        events = persistence.list_task_events(limit=3, task_id=None if task.task_id == "mock-task" else task.task_id)
        if task.state == "idle":
            return "现在没有正在执行的任务，可以给我派一个。"
        if task.state == "completed":
            last = events[0].detail if events else "上一个任务"
            return f"刚才的任务已经做完了。{last}。"
        if task.state == "paused":
            return f"任务暂停了，进度 {task.progress}%，说继续我就接着做。"
        if task.state in {"running", "pending"}:
            prog = f"，进度 {task.progress}%" if task.progress else ""
            return f"正在执行{task.task_type}任务{prog}。"
        return f"任务状态：{task.task_type} / {task.state}，进度 {task.progress}%。"

    def navigation_reply(self) -> str:
        state = self.latest_state()
        nav = state.nav_status
        snapshot = navigation_store.latest()
        if snapshot is None or snapshot.pose is None:
            return "我现在还没拿到定位，等导航起来我再告诉你。"
        if nav.state == "idle":
            return "导航已经定位好了，现在在原地待命，没有目标点。"
        parts = ["导航在跑"]
        if nav.current_goal:
            parts.append(f"目标是{nav.current_goal}")
        if nav.remaining_distance is not None:
            parts.append(f"还剩约 {nav.remaining_distance:.1f} 米")
        return "，".join(parts) + "。"

    def battery_reply(self) -> str:
        battery = self.latest_state().device_status.battery_percent
        if battery is None:
            return "我这边还没拿到电量数据。"
        if battery <= 20:
            return f"只剩 {battery}% 了，得赶紧回去充电。"
        if battery <= 50:
            return f"还有 {battery}%，能用一阵，留意着点。"
        return f"电量 {battery}%，挺充足的。"

    def emergency_stop_reply(self) -> str:
        device = self.latest_state().device_status
        if device.emergency_stop:
            return "现在处于急停状态，机器人不动了，先人工检查一下。"
        return "没有触发急停，一切正常。"

    def perception_reply(self, question: str | None = None) -> str:
        """视觉问答：把检测目标（类别/颜色/距离）+ 人数 + 近期事件交给本地大模型，
        按问题答（几个 / 什么颜色 / 多远），失败退确定性摘要。"""
        detection = self.latest_state().detection_status
        now = datetime.now(timezone.utc)
        objs, persons, fresh = [], 0, True
        if detection is not None:
            fresh = max(0.0, (now - detection.timestamp).total_seconds()) <= 5.0
            for obj in detection.objects[:6]:
                entry = {"class": obj.class_name}
                if obj.color:
                    entry["color"] = obj.color
                if obj.distance_m is not None:
                    entry["distance_m"] = round(obj.distance_m, 2)
                objs.append(entry)
                if obj.class_name == "person":
                    persons += 1
        context = {
            "vision_fresh": fresh,
            "objects": objs,
            "person_count": persons,
            "recent_events": [e.message for e in persistence.list_visual_events(limit=3)],
        }
        if os.getenv("STATUS_LLM_ENABLE", "true").strip().lower() in {"1", "true", "yes", "on"}:
            system_prompt = (
                "你是云拓机器人的车载视觉助手，只根据给定 JSON 上下文回答用户关于看到什么的问题。"
                "问几个人就答 person_count；问颜色用 objects 里的 color，没有就说这个目标没识别出颜色；"
                "问距离用 distance_m（单位米），为空就说这个目标没测到距离，不要把别的数字当距离。"
                "person_count 为 0 就直接说没看到人，不要解释原因。"
                "1 到 2 句话，不要提置信度、框、接口或字段名，vision_fresh 为 false 时说明画面可能不是最新的，"
                "不要编造上下文里没有的目标。"
            )
            response = llm_client.chat_text(
                system_prompt=system_prompt,
                user_prompt=json.dumps({"question": question or "你看到了什么", "context": context},
                                       ensure_ascii=False, separators=(",", ":")),
            )
            if response.success and response.content and response.content.strip():
                reply = response.content.strip()
                for marker in ("\n用户：", "用户：", "\n助手：", "助手："):
                    reply = reply.split(marker)[0].rstrip()
                import re as _re
                if reply and not _re.search(r"person_count|vision_fresh|objects|distance_m", reply):
                    return reply[:220]          # 字段名漏出来就当无效，走确定性兜底
        q = question or ""
        if persons == 0 and any(k in q for k in ("几个", "多少个", "多少人", "有人吗")):
            return "现在没看到人。" + (f"能看到：{'、'.join(sorted({o['class'] for o in objs}))}。" if objs else "")
        if not objs:
            history = "；".join(e.message for e in persistence.list_visual_events(limit=2))
            return f"现在画面里没识别到目标。{('之前：' + history) if history else ''}"
        names = "、".join(sorted({o["class"] for o in objs}))
        nearest = next((o for o in objs if "distance_m" in o), None)
        tail = f"，最近的约 {nearest['distance_m']} 米" if nearest else ""
        if persons:
            return f"现在能看到 {persons} 个人，还有：{names}{tail}。"
        return f"现在能看到：{names}{tail}。"

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
            "safety_boundary": "回答只能用于观察和建议，不能替代 FPGA 导航避障，也不能直接生成控制命令。",
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
            "你是云拓多模态复杂地形轮腿机器人的车载智能助手。"
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
