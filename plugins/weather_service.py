"""Weather service integration for forecast cards and rain timing answers.

支持两种配置方式（参考 https://dev.qweather.com/docs/configuration/api-config/）：
1. 自定义 API Host（推荐）：QWEATHER_API_HOST + QWEATHER_API_KEY，使用 Header 认证
2. 旧版公共地址：QWEATHER_GEO_BASE_URL + QWEATHER_WEATHER_BASE_URL + QWEATHER_API_KEY，使用 query key
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib import error, parse, request


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert arbitrary values into float safely."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert arbitrary values into int safely."""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _format_hour_label(fx_time: str) -> str:
    """Render one hourly forecast timestamp into a compact Chinese label."""
    if len(fx_time) >= 16:
        return f"{fx_time[8:10]}日{fx_time[11:16]}"
    return fx_time or "未知时间"


def _format_minute_label(fx_time: str) -> str:
    """Render one minutely forecast timestamp into HH:MM."""
    if len(fx_time) >= 16:
        return fx_time[11:16]
    return fx_time or "未知时间"


def _is_rainy_hour(item: dict[str, Any]) -> bool:
    """Treat explicit rain text or non-zero precipitation as rainy."""
    text = str(item.get("text", "") or "")
    return "雨" in text or _safe_float(item.get("precip")) > 0 or _safe_int(item.get("pop")) >= 30


def _is_rainy_minute(item: dict[str, Any]) -> bool:
    """Treat positive minutely precip as a rain signal."""
    return _safe_float(item.get("precip")) > 0


class WeatherService:
    """Wrap QWeather access for daily forecast and precise rain timing."""

    def __init__(
        self,
        api_key: str,
        geo_base_url: str = "https://geoapi.qweather.com/v2",
        weather_base_url: str = "https://devapi.qweather.com/v7",
        api_host: str = "",
        use_header_auth: bool = False,
        timeout_seconds: int = 15,
    ) -> None:
        self._api_key = api_key
        self._api_host = (api_host or "").strip().rstrip("/")
        self._use_header_auth = use_header_auth and bool(self._api_host)
        if self._api_host:
            if self._api_host.startswith(("http://", "https://")):
                base = self._api_host
            else:
                base = f"https://{self._api_host}"
            self._geo_base_url = f"{base}/geo/v2"
            self._weather_base_url = f"{base}/v7"
        else:
            self._geo_base_url = geo_base_url.rstrip("/")
            self._weather_base_url = weather_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        """Whether weather API is configured."""
        return bool(self._api_key)

    def _request_json_sync(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Perform one GET request and parse JSON body, supporting gzip response."""
        import gzip
        req_headers = dict(headers) if headers else {}
        req_headers.setdefault("Accept-Encoding", "gzip, deflate")
        req = request.Request(url, method="GET", headers=req_headers)
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                raw = response.read()
                encoding = response.headers.get("Content-Encoding", "")
                if encoding == "gzip" or (raw[:2] == b"\x1f\x8b"):
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except error.HTTPError as exc:
            return {"ok": False, "error": f"HTTP error: {exc.code}", "url": url}
        except error.URLError as exc:
            return {"ok": False, "error": f"Connection error: {exc.reason}", "url": url}
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid JSON response", "url": url}

    async def _request_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Async wrapper around blocking HTTP call."""
        return await asyncio.to_thread(self._request_json_sync, url, headers)

    def _get_auth_headers(self) -> dict[str, str]:
        """Return header auth for the custom QWeather host mode."""
        if self._use_header_auth:
            return {"X-QW-Api-Key": self._api_key}
        return {}

    def _build_url(self, base_url: str, path: str, query: dict[str, Any]) -> str:
        """Build one QWeather URL while preserving auth mode behavior."""
        actual_query = dict(query)
        if not self._use_header_auth:
            actual_query["key"] = self._api_key
        return f"{base_url}{path}?{parse.urlencode(actual_query)}"

    async def _lookup_city(self, city_name: str, headers: dict[str, str]) -> dict[str, Any]:
        """Resolve a city name into QWeather location metadata."""
        url = self._build_url(self._geo_base_url, "/city/lookup", {"location": city_name})
        data = await self._request_json(url, headers)
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        if data.get("code") and str(data.get("code")) != "200":
            return {"ok": False, "error": data.get("code", "unknown")}
        locations = data.get("location", []) or []
        if not locations:
            return {"ok": False, "error": f"未找到城市：{city_name}"}
        return {"ok": True, "location": locations[0]}

    async def _fetch_daily_forecast(self, location_id: str, headers: dict[str, str]) -> dict[str, Any]:
        """Fetch 3-day forecast by location id."""
        url = self._build_url(self._weather_base_url, "/weather/3d", {"location": location_id})
        data = await self._request_json(url, headers)
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        if data.get("code") and str(data.get("code")) != "200":
            return {"ok": False, "error": data.get("code", "unknown")}
        return {"ok": True, "daily": data.get("daily", []) or []}

    async def _fetch_hourly_forecast(self, location_id: str, headers: dict[str, str]) -> dict[str, Any]:
        """Fetch 24-hour weather details by location id."""
        url = self._build_url(self._weather_base_url, "/weather/24h", {"location": location_id})
        data = await self._request_json(url, headers)
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        if data.get("code") and str(data.get("code")) != "200":
            return {"ok": False, "error": data.get("code", "unknown")}
        return {"ok": True, "hourly": data.get("hourly", []) or []}

    async def _fetch_minutely_precipitation(self, lon: str, lat: str, headers: dict[str, str]) -> dict[str, Any]:
        """Fetch 2-hour, 5-minute precipitation forecast by longitude/latitude."""
        if not lon or not lat:
            return {"ok": True, "minutely": {}}
        url = self._build_url(self._weather_base_url, "/minutely/5m", {"location": f"{lon},{lat}"})
        data = await self._request_json(url, headers)
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        if data.get("code") and str(data.get("code")) != "200":
            return {"ok": False, "error": data.get("code", "unknown")}
        return {"ok": True, "minutely": data}

    def _build_forecast_cards(self, daily: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Normalize QWeather daily payload into the UI card format."""
        cards: list[dict[str, str]] = []
        for item in daily[:3]:
            cards.append(
                {
                    "date": str(item.get("fxDate", "") or ""),
                    "text_day": str(item.get("textDay", "") or ""),
                    "text_night": str(item.get("textNight", "") or ""),
                    "temp_min": str(item.get("tempMin", "") or ""),
                    "temp_max": str(item.get("tempMax", "") or ""),
                    "wind_dir_day": str(item.get("windDirDay", "") or ""),
                }
            )
        return cards

    def _build_today_overview(self, city_name: str, forecast: list[dict[str, str]]) -> str:
        """Generate one concise summary sentence for today."""
        if not forecast:
            return f"{city_name}天气数据暂时不完整。"
        today = forecast[0]
        return (
            f"{city_name}今天白天{today.get('text_day', '未知')}，夜间{today.get('text_night', '未知')}，"
            f"气温{today.get('temp_min', '')}到{today.get('temp_max', '')}度。"
        )

    def _build_hourly_rain_summary(self, hourly: list[dict[str, Any]]) -> str:
        """Summarize rain tendency from the 24-hour forecast."""
        if not hourly:
            return ""
        rainy_hours = [item for item in hourly if _is_rainy_hour(item)]
        if not rainy_hours:
            return "未来24小时暂无明显降雨。"

        ranges: list[list[dict[str, Any]]] = [[rainy_hours[0]]]
        for item in rainy_hours[1:]:
            prev = ranges[-1][-1].get("fxTime", "")
            curr = item.get("fxTime", "")
            prev_hour = _safe_int(prev[11:13], -1)
            curr_hour = _safe_int(curr[11:13], -1)
            is_continuous = prev[:10] == curr[:10] and prev_hour >= 0 and curr_hour - prev_hour == 1
            if is_continuous:
                ranges[-1].append(item)
            else:
                ranges.append([item])

        range_texts: list[str] = []
        for hour_range in ranges[:3]:
            start_text = _format_hour_label(str(hour_range[0].get("fxTime", "") or ""))
            end_text = _format_hour_label(str(hour_range[-1].get("fxTime", "") or ""))
            range_texts.append(start_text if start_text == end_text else f"{start_text}到{end_text}")
        first_text = _format_hour_label(str(rainy_hours[0].get("fxTime", "") or ""))
        return f"未来24小时最早可能在{first_text}开始下雨，主要降雨时段：{'；'.join(range_texts)}。"

    def _build_minutely_summary(self, minutely_data: dict[str, Any]) -> str:
        """Summarize the next 2 hours using the minutely precipitation API."""
        items = minutely_data.get("minutely", []) or []
        if not items:
            return ""
        rainy_items = [item for item in items if _is_rainy_minute(item)]
        summary = str(minutely_data.get("summary", "") or "").strip()
        if not rainy_items:
            return f"未来2小时分钟级降水：{summary or '暂无明显降水。'}"
        first_rain = _format_minute_label(str(rainy_items[0].get("fxTime", "") or ""))
        last_rain = _format_minute_label(str(rainy_items[-1].get("fxTime", "") or ""))
        if summary:
            return f"未来2小时分钟级降水：{summary} 最早可能在{first_rain}开始，预计到{last_rain}前后结束。"
        return f"未来2小时分钟级降水：最早可能在{first_rain}开始，预计到{last_rain}前后结束。"

    def _describe_rain_risk(self, label: str, items: list[dict[str, Any]], summary: str) -> str:
        """Explain whether a short time range has rain risk."""
        rainy_items = [item for item in items if _is_rainy_minute(item)]
        if rainy_items:
            first_rain = _format_minute_label(str(rainy_items[0].get("fxTime", "") or ""))
            return f"{label}有降雨风险，建议带伞，最早可能在{first_rain}前后开始下雨。"
        if summary:
            return f"{label}暂无明显降水，分钟级提示为：{summary}"
        return f"{label}暂无明显降水。"

    def _analyze_minutely_query(self, minutely_data: dict[str, Any], time_query: str) -> str:
        """Answer precise near-term rain questions from minutely data."""
        query = (time_query or "").strip()
        items = minutely_data.get("minutely", []) or []
        if not query or not items:
            return ""

        summary = str(minutely_data.get("summary", "") or "").strip()
        rainy_items = [item for item in items if _is_rainy_minute(item)]

        if any(keyword in query for keyword in ("雨什么时候停", "什么时候停雨", "什么时候停")):
            if not rainy_items:
                return "未来2小时看暂无明显降雨，所以也没有明确的停雨时间。"
            stop_time = _format_minute_label(str(rainy_items[-1].get("fxTime", "") or ""))
            return f"按分钟级降水看，这波雨大约会在{stop_time}前后停。"

        if "未来半小时" in query or "半小时内" in query:
            return self._describe_rain_risk("未来半小时", items[:6], summary)
        if "未来一小时" in query or "一小时内" in query:
            return self._describe_rain_risk("未来1小时", items[:12], summary)
        if any(keyword in query for keyword in ("带伞", "要不要带伞")):
            return self._describe_rain_risk("未来2小时", items, summary)
        if any(keyword in query for keyword in ("出门", "淋雨", "路上")):
            return self._describe_rain_risk("接下来1小时", items[:12], summary)

        minute_match = re.search(r"(\d{1,2})\s*点\s*(\d{1,2})?\s*分?", query)
        if minute_match:
            ask_hour = _safe_int(minute_match.group(1), -1)
            ask_minute = _safe_int(minute_match.group(2) or "0", 0)
            target_minute = ask_hour * 60 + ask_minute
            best_item: dict[str, Any] | None = None
            best_gap: int | None = None
            for item in items:
                fx_time = str(item.get("fxTime", "") or "")
                if len(fx_time) < 16:
                    continue
                gap = abs((_safe_int(fx_time[11:13]) * 60 + _safe_int(fx_time[14:16])) - target_minute)
                if best_gap is None or gap < best_gap:
                    best_gap = gap
                    best_item = item
            if best_item is not None:
                label = _format_minute_label(str(best_item.get("fxTime", "") or ""))
                precip = _safe_float(best_item.get("precip"))
                if _is_rainy_minute(best_item):
                    return f"按分钟级降水看，{label}前后有降水，5分钟累计降水量约{precip:.2f}毫米。"
                return f"按分钟级降水看，{label}前后暂无明显降水。"

        if any(keyword in query for keyword in ("几分下雨", "几点下雨", "什么时候下雨", "多久后下雨", "会不会下雨", "下不下雨", "有雨吗")):
            if not rainy_items:
                return "按分钟级降水看，未来2小时暂无明显降雨。"
            start_time = _format_minute_label(str(rainy_items[0].get("fxTime", "") or ""))
            return f"按分钟级降水看，最早可能在{start_time}开始降雨。"
        return ""

    def _hour_items_for_window(
        self,
        hourly: list[dict[str, Any]],
        target_date: str,
        start_hour: int,
        end_hour: int,
    ) -> list[dict[str, Any]]:
        """Pick hourly items within one date/hour range."""
        selected: list[dict[str, Any]] = []
        for item in hourly:
            fx_time = str(item.get("fxTime", "") or "")
            if len(fx_time) < 13 or fx_time[:10] != target_date:
                continue
            hour_value = _safe_int(fx_time[11:13], -1)
            if start_hour <= hour_value <= end_hour:
                selected.append(item)
        return selected

    def _analyze_hourly_window(self, hourly: list[dict[str, Any]], time_query: str) -> str:
        """Answer broader time-window rain questions from hourly data."""
        query = (time_query or "").strip()
        if not query or not hourly:
            return ""

        first_date = str(hourly[0].get("fxTime", "") or "")[:10]
        next_date = ""
        for item in hourly:
            current_date = str(item.get("fxTime", "") or "")[:10]
            if current_date and current_date != first_date:
                next_date = current_date
                break
        target_date = next_date if "明" in query and next_date else first_date

        range_match = re.search(r"(\d{1,2})\s*点\s*(?:到|至|\-|~)\s*(\d{1,2})\s*点", query)
        if range_match:
            start_hour = _safe_int(range_match.group(1), 0)
            end_hour = max(start_hour, _safe_int(range_match.group(2), start_hour))
            focus_hours = self._hour_items_for_window(hourly, target_date, start_hour, end_hour)
            label = f"{start_hour}点到{end_hour}点"
        else:
            windows = [
                ("今晚", 18, 23),
                ("今天晚上", 18, 23),
                ("今夜", 18, 23),
                ("明晚", 18, 23),
                ("明天晚上", 18, 23),
                ("明早", 5, 11),
                ("明晨", 5, 11),
                ("明天早上", 5, 11),
                ("明天上午", 6, 11),
                ("今天早上", 5, 11),
                ("早上", 5, 11),
                ("上午", 6, 11),
                ("中午", 11, 13),
                ("下午", 12, 17),
                ("傍晚", 17, 19),
                ("晚上", 18, 23),
                ("凌晨", 0, 5),
            ]
            focus_hours = []
            label = query
            single_match = re.search(r"(\d{1,2})\s*点", query)
            if single_match:
                hour_value = _safe_int(single_match.group(1), 0)
                focus_hours = self._hour_items_for_window(hourly, target_date, hour_value, hour_value)
                label = f"{hour_value}点左右"
            else:
                for text, start_hour, end_hour in windows:
                    if text in query:
                        focus_hours = self._hour_items_for_window(hourly, target_date, start_hour, end_hour)
                        label = text
                        break

        if not focus_hours:
            return ""

        rainy_hours = [item for item in focus_hours if _is_rainy_hour(item)]
        if rainy_hours:
            hour_labels = [_format_minute_label(str(item.get("fxTime", "") or "")) for item in rainy_hours[:5]]
            first_text = str(rainy_hours[0].get("text", "有雨") or "有雨")
            return f"{label}有下雨可能，重点时段在{'、'.join(hour_labels)}，天气以{first_text}为主。"

        highest_pop = 0
        highest_item: dict[str, Any] | None = None
        for item in focus_hours:
            pop_value = _safe_int(item.get("pop"), 0)
            if pop_value >= highest_pop:
                highest_pop = pop_value
                highest_item = item
        if highest_item is not None:
            peak_time = _format_minute_label(str(highest_item.get("fxTime", "") or ""))
            return f"{label}暂无明显降雨，较高降水概率大约在{peak_time}，约{highest_pop}%。"
        return f"{label}暂无明显降雨。"

    def _build_answer_text(
        self,
        city_name: str,
        forecast: list[dict[str, str]],
        hourly: list[dict[str, Any]],
        minutely_data: dict[str, Any],
        time_query: str,
    ) -> str:
        """Compose the final voice-friendly weather answer."""
        today_overview = self._build_today_overview(city_name, forecast)
        hourly_summary = self._build_hourly_rain_summary(hourly)
        minutely_summary = self._build_minutely_summary(minutely_data)
        minutely_target = self._analyze_minutely_query(minutely_data, time_query)
        hourly_target = self._analyze_hourly_window(hourly, time_query)

        parts: list[str] = []
        if minutely_target:
            parts.append(minutely_target)
        if hourly_target and hourly_target not in parts:
            parts.append(hourly_target)
        parts.append(today_overview)

        if not time_query:
            if minutely_summary:
                parts.append(minutely_summary)
            if hourly_summary and hourly_summary != minutely_summary:
                parts.append(hourly_summary)
        elif not minutely_target and not hourly_target:
            if minutely_summary:
                parts.append(minutely_summary)
            elif hourly_summary:
                parts.append(hourly_summary)

        return " ".join(part.strip() for part in parts if part and part.strip())

    async def get_weather_forecast(self, city_name: str, time_query: str = "") -> dict[str, Any]:
        """Return forecast cards and precise rain answer for one city."""
        if not self.enabled:
            return {"ok": False, "error": "QWEATHER_API_KEY is required"}
        if not city_name:
            return {"ok": False, "error": "city is required"}

        headers = self._get_auth_headers()
        city_result = await self._lookup_city(city_name, headers)
        if not city_result.get("ok"):
            return {"ok": False, "error": city_result.get("error", "城市查询失败")}

        location = city_result["location"]
        location_id = str(location.get("id", "") or "")
        if not location_id:
            return {"ok": False, "error": "城市 ID 解析失败"}

        daily_result, hourly_result, minutely_result = await asyncio.gather(
            self._fetch_daily_forecast(location_id, headers),
            self._fetch_hourly_forecast(location_id, headers),
            self._fetch_minutely_precipitation(
                str(location.get("lon", "") or ""),
                str(location.get("lat", "") or ""),
                headers,
            ),
        )
        for result in (daily_result, hourly_result, minutely_result):
            if not result.get("ok"):
                return {"ok": False, "error": result.get("error", "天气查询失败")}

        daily = daily_result.get("daily", []) or []
        if not daily:
            return {"ok": False, "error": "天气数据为空"}

        forecast = self._build_forecast_cards(daily)
        hourly = hourly_result.get("hourly", []) or []
        minutely_data = minutely_result.get("minutely", {}) or {}
        city_display_name = str(location.get("name", city_name) or city_name)

        return {
            "ok": True,
            "action": "get_weather_forecast",
            "city": city_display_name,
            "adm2": str(location.get("adm2", "") or ""),
            "adm1": str(location.get("adm1", "") or ""),
            "forecast": forecast,
            "time_query": time_query,
            "hourly_summary": self._build_hourly_rain_summary(hourly),
            "minutely_summary": self._build_minutely_summary(minutely_data),
            "answer_text": self._build_answer_text(
                city_name=city_display_name,
                forecast=forecast,
                hourly=hourly,
                minutely_data=minutely_data,
                time_query=time_query,
            ),
        }
