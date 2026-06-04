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

    def reply_for_query(self, intent: str) -> tuple[str, str]:
        if intent == "query_self_identity":
            return "robot_profile", profile_provider.identity_reply()
        if intent == "query_capability":
            return "robot_profile", profile_provider.capability_reply()
        if intent == "query_safety_rule":
            return "robot_profile", profile_provider.safety_reply()
        if intent in {"query_robot_status", "query_status"}:
            return "state_store", robot_status_provider.robot_status_reply()
        if intent in {"query_task_status", "query_task"}:
            return "state_store", robot_status_provider.task_reply()
        if intent == "query_battery":
            return "state_store", robot_status_provider.battery_reply()
        if intent == "query_emergency_stop":
            return "state_store", robot_status_provider.emergency_stop_reply()
        if intent in {"query_perception_status", "query_detection"}:
            return "state_store", robot_status_provider.perception_reply()
        if intent in {"query_weather", "query_environment"}:
            weather = weather_provider.latest()
            return (
                "weather_provider",
                f"{weather.location}当前天气{weather.weather}，温度{weather.temperature_c:.1f}摄氏度，"
                f"湿度{weather.humidity_percent:.0f}%，{weather.wind or '风力未知'}。"
                "天气数据来自外部天气源，不代表机器人本体传感器。"
            )
        return "none", "我还不能回答这个问题。"


data_service = DataService()
