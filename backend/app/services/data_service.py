import os
from datetime import datetime, timezone

from app.schemas import AlertEvent, RobotProfile, RobotState, TaskStatus, WeatherData
from app.services.profile_provider import profile_provider
from app.services.robot_status_provider import robot_status_provider
from app.services.weather_provider import weather_provider


class DataService:
    def robot_profile(self) -> RobotProfile:
        return profile_provider.get_profile()

    def robot_state(self) -> RobotState:
        return robot_status_provider.latest_state()

    def task_status(self) -> TaskStatus:
        return robot_status_provider.current_task()

    def alerts(self) -> list[AlertEvent]:
        return robot_status_provider.alerts()

    def weather(self) -> WeatherData:
        return weather_provider.latest()

    def assistant_model_reply(self) -> str:
        backend = os.getenv("LLM_BACKEND", "deepseek").strip() or "deepseek"
        if backend == "local":
            model = os.getenv("LLM_LOCAL_MODEL", "").strip() or "本地大模型"
            return (f"我跑在本机 RK3588 上，用的是 {model}，走 NPU，全程不联网。"
                    "你说话我先在本地理解，运动指令还是会先经安全校验、再请你确认。")
        request_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
        model = os.getenv("DEEPSEEK_DISPLAY_MODEL", request_model).strip() or request_model
        if backend == "deepseek":
            return f"当前智能语音助手的大模型后端是 DeepSeek，模型配置为 {model}。机器人运动控制仍由本地安全校验和确认流程接管。"
        return f"当前智能语音助手的大模型后端配置为 {backend}，模型配置为 {model}。机器人运动控制仍由本地安全校验和确认流程接管。"

    def reply_for_query(self, intent: str, *, question: str | None = None) -> tuple[str, str]:
        if intent == "query_self_identity":
            return "robot_profile", profile_provider.identity_reply()
        if intent == "query_capability":
            return "robot_profile", profile_provider.capability_reply()
        if intent == "query_safety_rule":
            return "robot_profile", profile_provider.safety_reply()
        if intent == "query_assistant_model":
            return "llm_config", self.assistant_model_reply()
        if intent in {"query_robot_status", "query_status"}:
            return "state_store", robot_status_provider.robot_status_reply()
        if intent in {"query_task_status", "query_task"}:
            return "state_store", robot_status_provider.task_reply()
        if intent == "query_navigation_status":
            return "navigation_store", robot_status_provider.navigation_reply()
        if intent in {"query_navigation_safety"}:
            return "navigation_store+visual_events+llm", robot_status_provider.front_status_reply(question)
        if intent in {"query_front_status", "query_obstacle_status"}:
            return "visual_events+detection_status+llm", robot_status_provider.front_status_reply(question)
        if intent == "query_battery":
            return "state_store", robot_status_provider.battery_reply()
        if intent == "query_emergency_stop":
            return "state_store", robot_status_provider.emergency_stop_reply()
        if intent in {"query_perception_status", "query_detection"}:
            return "state_store", robot_status_provider.perception_reply()
        if intent in {"query_weather", "query_environment"}:
            weather = weather_provider.latest()
            if weather.source == "unavailable":
                return "weather_unavailable", "我现在连不上天气服务，稍后再帮你查。"
            return weather.source, _weather_reply(weather, question or "")
        return "none", "我还不能回答这个问题。"


def _weather_reply(weather, question: str) -> str:
    """按问题回答，不再把整段数据都念一遍。数据仍是实时 Open-Meteo。"""
    loc = weather.location
    w = weather.weather
    t = weather.temperature_c
    feels = weather.apparent_temperature_c
    hum = weather.humidity_percent
    rain = weather.precipitation_probability_percent
    uv = weather.uv_index
    wind = weather.wind
    q = question or ""

    def age() -> str:
        mins = max(0.0, (datetime.now(timezone.utc) - weather.updated_at).total_seconds()) / 60
        return "刚更新" if mins < 1 else f"约{mins:.0f}分钟前更新"

    if any(k in q for k in ("下雨", "带伞", "雨", "淋")):
        if rain is None:
            return f"{loc}现在{w}，暂时没有降雨预报数据。"
        if rain >= 50 or (weather.precipitation_mm or 0) > 0:
            return f"{loc}今天最高降雨概率{rain:.0f}%，最好带把伞。{weather.advice or ''}"
        return f"{loc}现在{w}，今天最高降雨概率只有{rain:.0f}%，基本不会下，不用带伞。"

    if any(k in q for k in ("冷", "热", "凉", "晒", "暖")):
        if t is None:
            return f"{loc}现在{w}，温度数据暂时没拿到。"
        feel = f"，体感{feels:.0f}度" if feels is not None else ""
        only_today = "明天的预报我还没有，先说今天：" if ("明" in q or "后天" in q or "周末" in q) else ""
        if t <= 12 or (feels is not None and feels <= 10):
            return f"{only_today}{loc}现在{t:.0f}度{feel}，挺冷的，出门加件外套。"
        if t >= 30 or (feels is not None and feels >= 33):
            hum_text = "，湿度也大，闷热" if hum is not None and hum >= 75 else ""
            return f"{only_today}{loc}现在{t:.0f}度{feel}{hum_text}，注意防晒补水。"
        return f"{only_today}{loc}现在{t:.0f}度{feel}，不冷不热，挺舒服的。"

    if any(k in q for k in ("紫外线", "防晒", "晒不晒")):
        if uv is None:
            return f"{loc}紫外线数据暂时没拿到。"
        level = "很强" if uv >= 8 else "较强" if uv >= 6 else "中等" if uv >= 3 else "弱"
        tip = "，长时间在外要涂防晒、戴帽子" if uv >= 6 else "，正常活动不用太担心"
        return f"{loc}紫外线指数{uv:.1f}，{level}{tip}。"

    if any(k in q for k in ("风", "刮")):
        return f"{loc}现在{w}，{wind or '风力数据没拿到'}。"

    if "明天" in q or "明后" in q:
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        d = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        base = f"我现在只有{loc}今天的数据：{w}" + (f"，气温{t:.0f}度" if t is not None else "")
        if rain is not None:
            base += f"，今天最高降雨概率{rain:.0f}%"
        return base + f"。明天（{d.month}月{d.day}日 星期{weekdays[d.weekday()]}）的预报我还没查到。"

    parts = [f"{loc}现在{w}"]
    if t is not None:
        feel_part = f"（体感{feels:.0f}度）" if feels is not None and abs(feels - t) >= 2 else ""
        parts.append(f"气温{t:.0f}度{feel_part}")
    if hum is not None:
        parts.append(f"湿度{hum:.0f}%")
    line = "，".join(parts) + "。"
    advice = weather.advice if weather.advice and weather.advice != "天气条件总体平稳，适合正常出行。" else ""
    extras = []
    if rain is not None and rain >= 30:
        extras.append(f"今日最高降雨概率{rain:.0f}%")
    if uv is not None and uv >= 6 and "紫外线" not in advice:
        extras.append(f"紫外线指数{uv:.1f}，注意防晒")
    if extras:
        line += "；".join(extras) + "。"
    if advice:
        line += f"出行建议：{advice}"
    return line + f"（{age()}）"


data_service = DataService()
