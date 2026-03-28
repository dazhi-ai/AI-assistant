"""Model tool definitions and execution dispatcher."""

from __future__ import annotations

import json
from typing import Any

from plugins.netease_cloud import NeteaseCloudController
from plugins.weather_service import WeatherService


class ToolHandler:
    """Parse and execute model tool_calls safely."""

    def __init__(self, netease: NeteaseCloudController, weather: WeatherService) -> None:
        self._netease = netease
        self._weather = weather

    @staticmethod
    def tool_schemas() -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool schemas for model planning."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_weather_forecast",
                    "description": (
                        "Get weather forecast, rain timing, and minutely precipitation by city name. "
                        "Use this for weather, rain start time, rain stop time, umbrella advice, "
                        "and questions like what time it will rain."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "time_query": {
                                "type": "string",
                                "description": "Original user time/rain concern such as 今晚、几点几分下雨、雨什么时候停。",
                            },
                        },
                        "required": ["city"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_netease_login_qrcode",
                    "description": "Create Netease login QR code for user scan.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_netease_login_status",
                    "description": "Check Netease QR login status by unikey.",
                    "parameters": {
                        "type": "object",
                        "properties": {"unikey": {"type": "string"}},
                        "required": ["unikey"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "like_music",
                    "description": "Mark the current song as liked.",
                    "parameters": {
                        "type": "object",
                        "properties": {"song_id": {"type": "string"}},
                        "required": ["song_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "favorite_music",
                    "description": "Add current song to favorites collection.",
                    "parameters": {
                        "type": "object",
                        "properties": {"song_id": {"type": "string"}},
                        "required": ["song_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_music",
                    "description": "Search songs by keywords.",
                    "parameters": {
                        "type": "object",
                        "properties": {"keywords": {"type": "string"}},
                        "required": ["keywords"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "play_music",
                    "description": "Play one song by id.",
                    "parameters": {
                        "type": "object",
                        "properties": {"song_id": {"type": "string"}},
                        "required": ["song_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_user_playlist",
                    "description": "Get user playlist by type: liked or collected.",
                    "parameters": {
                        "type": "object",
                        "properties": {"type": {"type": "string"}},
                        "required": ["type"],
                    },
                },
            },
        ]

    async def execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute each tool call and return normalized outputs."""
        results: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            function_info = tool_call.get("function", {})
            call_name = function_info.get("name", "")
            raw_args = function_info.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            try:
                if call_name == "get_weather_forecast":
                    result = await self._weather.get_weather_forecast(
                        city_name=str(args.get("city", "")),
                        time_query=str(args.get("time_query", "")),
                    )
                elif call_name == "get_netease_login_qrcode":
                    result = await self._netease.get_login_qrcode()
                elif call_name == "check_netease_login_status":
                    result = await self._netease.check_login_status(unikey=str(args.get("unikey", "")))
                elif call_name == "like_music":
                    result = await self._netease.like_music(song_id=str(args.get("song_id", "")))
                elif call_name == "favorite_music":
                    result = await self._netease.favorite_music(song_id=str(args.get("song_id", "")))
                elif call_name == "search_music":
                    result = await self._netease.search_music(keywords=str(args.get("keywords", "")))
                elif call_name == "play_music":
                    result = await self._netease.play_music(song_id=str(args.get("song_id", "")))
                elif call_name == "get_user_playlist":
                    result = await self._netease.get_user_playlist(playlist_type=str(args.get("type", "")))
                else:
                    result = {"ok": False, "error": f"Unsupported tool: {call_name}"}
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}

            results.append(
                {
                    "tool_call_id": tool_call.get("id", ""),
                    "name": call_name,
                    "result": result,
                }
            )
        return results
