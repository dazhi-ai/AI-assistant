"""Weather service integration for 3-day forecast cards."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, parse, request


class WeatherService:
    """Wrap QWeather API access for city lookup and daily forecast."""

    def __init__(
        self,
        api_key: str,
        geo_base_url: str = "https://geoapi.qweather.com/v2",
        weather_base_url: str = "https://devapi.qweather.com/v7",
        timeout_seconds: int = 15,
    ) -> None:
        self._api_key = api_key
        self._geo_base_url = geo_base_url.rstrip("/")
        self._weather_base_url = weather_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        """Whether weather API is configured."""
        return bool(self._api_key)

    def _request_json_sync(self, url: str) -> dict[str, Any]:
        """Perform one GET request and parse JSON body."""
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return {"ok": False, "error": f"HTTP error: {exc.code}", "url": url}
        except error.URLError as exc:
            return {"ok": False, "error": f"Connection error: {exc.reason}", "url": url}
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid JSON response", "url": url}

    async def _request_json(self, url: str) -> dict[str, Any]:
        """Async wrapper around blocking HTTP call."""
        return await asyncio.to_thread(self._request_json_sync, url)

    async def get_weather_forecast(self, city_name: str) -> dict[str, Any]:
        """Return 3-day forecast for one city."""
        if not self.enabled:
            return {"ok": False, "error": "QWEATHER_API_KEY is required"}
        if not city_name:
            return {"ok": False, "error": "city is required"}

        geo_query = parse.urlencode({"location": city_name, "key": self._api_key})
        geo_url = f"{self._geo_base_url}/city/lookup?{geo_query}"
        geo_data = await self._request_json(geo_url)
        if "error" in geo_data:
            return {"ok": False, "error": geo_data["error"]}
        locations = geo_data.get("location", []) or []
        if not locations:
            return {"ok": False, "error": f"未找到城市：{city_name}"}

        location = locations[0]
        location_id = location.get("id", "")
        if not location_id:
            return {"ok": False, "error": "城市 ID 解析失败"}

        weather_query = parse.urlencode({"location": location_id, "key": self._api_key})
        weather_url = f"{self._weather_base_url}/weather/3d?{weather_query}"
        weather_data = await self._request_json(weather_url)
        if "error" in weather_data:
            return {"ok": False, "error": weather_data["error"]}
        daily = weather_data.get("daily", []) or []
        if not daily:
            return {"ok": False, "error": "天气数据为空"}

        forecast = []
        for item in daily[:3]:
            forecast.append(
                {
                    "date": item.get("fxDate", ""),
                    "text_day": item.get("textDay", ""),
                    "text_night": item.get("textNight", ""),
                    "temp_min": item.get("tempMin", ""),
                    "temp_max": item.get("tempMax", ""),
                    "wind_dir_day": item.get("windDirDay", ""),
                }
            )

        return {
            "ok": True,
            "action": "get_weather_forecast",
            "city": location.get("name", city_name),
            "adm2": location.get("adm2", ""),
            "adm1": location.get("adm1", ""),
            "forecast": forecast,
        }
