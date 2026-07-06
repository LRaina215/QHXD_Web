from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.schemas import WeatherData


_WEATHER_CODES = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "轻微冻雨",
    57: "较强冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "较强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴轻微冰雹",
    99: "雷雨伴较强冰雹",
}


class WeatherProvider:
    """Fetch current weather from Open-Meteo with a small in-process cache."""

    def __init__(self) -> None:
        self._cache: WeatherData | None = None
        self._cache_time = 0.0
        self._lock = threading.Lock()

    def latest(self) -> WeatherData:
        now = time.monotonic()
        with self._lock:
            if self._cache is not None and now - self._cache_time < self._cache_ttl_seconds():
                return self._cache

        try:
            weather = self._fetch_live()
        except Exception:
            with self._lock:
                if self._cache is not None:
                    return self._cache.model_copy(update={"source": "open_meteo_cache", "is_stale": True})
            return WeatherData(
                location=self._location(),
                weather="实时天气暂不可用",
                source="unavailable",
                is_stale=True,
                advice="请稍后重新查询。",
                updated_at=datetime.now(timezone.utc),
            )

        with self._lock:
            self._cache = weather
            self._cache_time = now
        return weather

    def _fetch_live(self) -> WeatherData:
        params = {
            "latitude": os.getenv("WEATHER_LATITUDE", "20.0440"),
            "longitude": os.getenv("WEATHER_LONGITUDE", "110.1999"),
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,weather_code,wind_speed_10m"
            ),
            "daily": "precipitation_probability_max,uv_index_max",
            "timezone": os.getenv("WEATHER_TIMEZONE", "Asia/Shanghai"),
            "forecast_days": "1",
        }
        url = f"https://api.open-meteo.com/v1/forecast?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "QHXD-Sentinel/1.0"})
        with urlopen(request, timeout=self._timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8"))

        current = payload["current"]
        daily = payload.get("daily", {})
        temperature = float(current["temperature_2m"])
        humidity = float(current["relative_humidity_2m"])
        apparent = float(current["apparent_temperature"])
        precipitation = float(current.get("precipitation", 0.0))
        wind_speed = float(current.get("wind_speed_10m", 0.0))
        precipitation_probability = self._first_float(daily.get("precipitation_probability_max"))
        uv_index = self._first_float(daily.get("uv_index_max"))
        weather_text = _WEATHER_CODES.get(int(current["weather_code"]), "天气状况未知")

        return WeatherData(
            location=self._location(),
            temperature_c=temperature,
            apparent_temperature_c=apparent,
            humidity_percent=humidity,
            precipitation_mm=precipitation,
            precipitation_probability_percent=precipitation_probability,
            uv_index=uv_index,
            weather=weather_text,
            wind=f"风速{wind_speed:.1f}公里/小时",
            source="open_meteo",
            is_stale=False,
            advice=self._travel_advice(
                weather_code=int(current["weather_code"]),
                temperature=temperature,
                apparent=apparent,
                humidity=humidity,
                precipitation=precipitation,
                precipitation_probability=precipitation_probability,
                uv_index=uv_index,
                wind_speed=wind_speed,
            ),
            updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _travel_advice(
        *,
        weather_code: int,
        temperature: float,
        apparent: float,
        humidity: float,
        precipitation: float,
        precipitation_probability: float | None,
        uv_index: float | None,
        wind_speed: float,
    ) -> str:
        advice: list[str] = []
        rain_risk = precipitation_probability or 0.0
        if precipitation > 0 or rain_risk >= 50 or weather_code >= 51:
            advice.append("建议携带雨具，注意湿滑路面")
        if apparent >= 35 or temperature >= 33:
            advice.append("体感炎热，请减少长时间户外活动并及时补水")
        elif apparent <= 10:
            advice.append("体感偏凉，建议适当添衣")
        elif humidity >= 85:
            advice.append("湿度较高，体感可能闷热")
        if uv_index is not None and uv_index >= 6:
            advice.append("紫外线较强，外出注意防晒")
        if wind_speed >= 39:
            advice.append("风力较大，避免靠近临时搭建物")
        return "；".join(advice) + "。" if advice else "天气条件总体平稳，适合正常出行。"

    @staticmethod
    def _first_float(value: object) -> float | None:
        if not isinstance(value, list) or not value or value[0] is None:
            return None
        return float(value[0])

    @staticmethod
    def _location() -> str:
        return os.getenv("WEATHER_LOCATION", "海南海口").strip() or "海南海口"

    @staticmethod
    def _timeout_seconds() -> float:
        try:
            return max(1.0, min(float(os.getenv("WEATHER_TIMEOUT_SECONDS", "6")), 15.0))
        except ValueError:
            return 6.0

    @staticmethod
    def _cache_ttl_seconds() -> float:
        try:
            return max(60.0, min(float(os.getenv("WEATHER_CACHE_TTL_SECONDS", "300")), 1800.0))
        except ValueError:
            return 300.0


weather_provider = WeatherProvider()
