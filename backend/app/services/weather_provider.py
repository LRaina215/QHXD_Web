import os
from datetime import datetime, timezone

from app.schemas import WeatherData


class WeatherProvider:
    """Structured weather source placeholder.

    Phase 9A keeps weather separate from robot onboard sensors. Later, this
    provider can be replaced with a real weather API or fused with env_sensor.
    """

    def latest(self) -> WeatherData:
        try:
            temperature = float(os.getenv("WEATHER_TEMPERATURE_C", "28.6"))
        except ValueError:
            temperature = 28.6
        try:
            humidity = float(os.getenv("WEATHER_HUMIDITY_PERCENT", "82"))
        except ValueError:
            humidity = 82.0
        return WeatherData(
            location=os.getenv("WEATHER_LOCATION", "海南海口"),
            temperature_c=temperature,
            humidity_percent=humidity,
            weather=os.getenv("WEATHER_TEXT", "多云"),
            wind=os.getenv("WEATHER_WIND", "东南风"),
            source="weather_provider",
            updated_at=datetime.now(timezone.utc),
        )


weather_provider = WeatherProvider()
