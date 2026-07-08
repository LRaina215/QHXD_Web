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
                return "weather_unavailable", "暂时无法获取实时天气，请稍后再试。"
            temperature = f"气温{weather.temperature_c:.1f}摄氏度" if weather.temperature_c is not None else "气温未知"
            apparent = (
                f"，体感{weather.apparent_temperature_c:.1f}摄氏度"
                if weather.apparent_temperature_c is not None else ""
            )
            humidity = f"，相对湿度{weather.humidity_percent:.0f}%" if weather.humidity_percent is not None else ""
            rain_probability = (
                f"今日最高降雨概率{weather.precipitation_probability_percent:.0f}%"
                if weather.precipitation_probability_percent is not None else ""
            )
            uv_index = f"，紫外线指数{weather.uv_index:.1f}" if weather.uv_index is not None else ""
            forecast = f"{rain_probability}{uv_index}。" if rain_probability or uv_index else ""
            age_seconds = max(0.0, (datetime.now(timezone.utc) - weather.updated_at).total_seconds())
            if weather.source == "open_meteo":
                freshness = f"实时天气，约{age_seconds / 60:.0f}分钟前更新"
            elif weather.is_stale:
                freshness = f"使用最近一次成功缓存，约{age_seconds / 60:.0f}分钟前更新"
            else:
                freshness = f"缓存天气，约{age_seconds / 60:.0f}分钟前更新"
            return (
                weather.source,
                f"{weather.location}当前{weather.weather}（{freshness}），{temperature}{apparent}{humidity}，"
                f"{weather.wind or '风力未知'}。{forecast}出行建议：{weather.advice or '请根据天气合理安排出行。'}"
            )
        return "none", "我还不能回答这个问题。"


data_service = DataService()
