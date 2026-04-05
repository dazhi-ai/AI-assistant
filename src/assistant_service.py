"""Conversation orchestration for text -> tool call -> response."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.ark_client import ArkClient
from src.knowledge_store import KnowledgeStore
from src.tool_handler import ToolHandler
from src.xiaozhi_prompt_sync import XiaozhiPromptSync


@dataclass
class PendingSongSelection:
    """Hold temporary search candidates waiting for user selection."""

    keywords: str
    candidates: list[dict[str, Any]]


class AssistantService:
    """Coordinate model reasoning and plugin tool execution."""

    # 工具使用指引，追加在角色 prompt 之后
    _TOOL_INSTRUCTIONS = (
        "请在需要时通过工具函数控制网易云音乐。"
        "对于“好听”优先调用 like_music；对于“收藏”优先调用 favorite_music。"
        "对于天气类问题调用 get_weather_forecast 并传 city。"
        "如果用户在问几点几分下雨、未来一小时会不会下雨、雨什么时候停、要不要带伞、"
        "今晚/明早/下午会不会下雨等问题，也调用 get_weather_forecast，并把原始时间诉求放进 time_query。"
    )

    def __init__(
        self,
        ark_client: ArkClient,
        tool_handler: ToolHandler,
        *,
        knowledge_store: KnowledgeStore | None = None,
        knowledge_context_max_chars: int = 6000,
        prompt_sync: XiaozhiPromptSync | None = None,
    ) -> None:
        self._ark_client = ark_client
        self._tool_handler = tool_handler
        self._knowledge_store = knowledge_store
        self._knowledge_context_max_chars = knowledge_context_max_chars
        self._prompt_sync = prompt_sync
        self._pending_song_selection: dict[str, PendingSongSelection] = {}

    def clear_session(self, session_id: str) -> None:
        """Clear all temporary conversation state for one websocket session."""
        self._pending_song_selection.pop(session_id, None)

    def _build_system_prompt(self) -> str:
        """小智 MySQL 角色 prompt（含新闻）+ 工具指引 + 可选知识库。"""
        role = ""
        if self._prompt_sync is not None and self._prompt_sync.enabled:
            role = self._prompt_sync.prompt.strip()
        if not role:
            role = "你是AI助手。"
        base = f"{role}\n\n{self._TOOL_INSTRUCTIONS}"
        if self._knowledge_store is None:
            return base
        kb_block = self._knowledge_store.build_context_block(self._knowledge_context_max_chars)
        return f"{base}\n\n{kb_block}" if kb_block else base

    def _extract_selection_index(self, user_text: str, max_count: int) -> int | None:
        """Extract human choice like '第2首' or '选三' into zero-based index."""
        digit_match = re.search(r"(\d+)", user_text)
        if digit_match:
            choice_number = int(digit_match.group(1))
            if 1 <= choice_number <= max_count:
                return choice_number - 1

        chinese_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
        for char, number in chinese_map.items():
            if f"第{char}" in user_text or f"选{char}" in user_text or f"{char}首" in user_text:
                if number <= max_count:
                    return number - 1
        return None

    async def _resolve_pending_selection(self, session_id: str, user_text: str) -> dict[str, Any] | None:
        """If selection is pending, interpret the user choice and trigger play."""
        pending = self._pending_song_selection.get(session_id)
        if not pending:
            return None

        if any(keyword in user_text for keyword in ("随机", "随便", "都行")):
            selection_index = 0
        else:
            selection_index = self._extract_selection_index(user_text, len(pending.candidates))

        if selection_index is None:
            option_lines = []
            for index, candidate in enumerate(pending.candidates[:5], start=1):
                option_lines.append(f"{index}. {candidate.get('name', '未知歌曲')} - {candidate.get('artist', '未知歌手')}")
            return {
                "assistant_text": "请告诉我你要第几首，例如“第2首”。\n" + "\n".join(option_lines),
                "tool_results": [],
            }

        selected_song = pending.candidates[selection_index]
        self._pending_song_selection.pop(session_id, None)
        play_call = [
            {
                "id": "selection-play",
                "function": {
                    "name": "play_music",
                    "arguments": json.dumps({"song_id": selected_song.get("song_id", "")}, ensure_ascii=False),
                },
            }
        ]
        tool_results = await self._tool_handler.execute_tool_calls(play_call)
        return {
            "assistant_text": f"正在为你播放：{selected_song.get('name', '未知歌曲')}",
            "tool_results": tool_results,
        }

    def _fallback_response(self, user_text: str) -> dict[str, Any]:
        """Return deterministic fallback when Ark API is not configured."""
        if self._is_weather_query(user_text):
            city = self._extract_weather_city(user_text) or "北京"
            time_query = self._extract_weather_time_query(user_text)
            query_label = "降雨情况" if time_query else "天气"
            return {
                "assistant_text": f"正在查询{city}{query_label}。",
                "tool_calls": [
                    {
                        "id": "fallback-weather",
                        "function": {
                            "name": "get_weather_forecast",
                            "arguments": json.dumps(
                                {"city": city, "time_query": time_query},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        if "登录" in user_text and "网易云" in user_text:
            return {
                "assistant_text": "正在为你生成网易云登录二维码。",
                "tool_calls": [
                    {
                        "id": "fallback-login",
                        "function": {"name": "get_netease_login_qrcode", "arguments": "{}"},
                    }
                ],
            }
        if "搜索" in user_text:
            keywords = user_text.replace("搜索", "").strip() or user_text.strip()
            return {
                "assistant_text": f"收到，我先帮你搜索：{keywords}",
                "tool_calls": [
                    {
                        "id": "fallback-search",
                        "function": {
                            "name": "search_music",
                            "arguments": json.dumps({"keywords": keywords}, ensure_ascii=False),
                        },
                    }
                ],
            }
        if "播放" in user_text:
            keywords = user_text.replace("播放", "").strip() or user_text.strip()
            return {
                "assistant_text": f"收到，我先帮你搜索：{keywords}",
                "tool_calls": [
                    {
                        "id": "fallback-search-play",
                        "function": {
                            "name": "search_music",
                            "arguments": json.dumps({"keywords": keywords}, ensure_ascii=False),
                        },
                    }
                ],
            }
        if "好听" in user_text:
            return {
                "assistant_text": "收到，我帮你点红心了。",
                "tool_calls": [
                    {
                        "id": "fallback-like",
                        "function": {"name": "like_music", "arguments": "{\"song_id\":\"10001\"}"},
                    }
                ],
            }
        if "收藏" in user_text:
            return {
                "assistant_text": "好的，已加入收藏。",
                "tool_calls": [
                    {
                        "id": "fallback-favorite",
                        "function": {"name": "favorite_music", "arguments": "{\"song_id\":\"10001\"}"},
                    }
                ],
            }
        return {"assistant_text": f"你说的是：{user_text}", "tool_calls": []}

    @staticmethod
    def _is_weather_query(user_text: str) -> bool:
        """Detect whether the user is asking about weather or rain."""
        keywords = (
            "天气",
            "下雨",
            "降雨",
            "降水",
            "带伞",
            "淋雨",
            "雨什么时候停",
            "什么时候停雨",
            "几点下雨",
            "几分下雨",
            "会不会下雨",
            "下不下雨",
            "有雨吗",
        )
        return any(keyword in user_text for keyword in keywords)

    @staticmethod
    def _extract_weather_city(user_text: str) -> str:
        """Guess the city portion from a casual Chinese weather question."""
        normalized = re.sub(r"[，。！？!?]", "", user_text).strip()
        normalized = re.sub(
            r"^(帮我|请问|麻烦|麻烦你|帮忙|查一下|查查|查询一下|查询|看看|我想知道|想知道|告诉我|问一下)+",
            "",
            normalized,
        )
        patterns = [
            r"(?:查|查询|看看)?([A-Za-z\u4e00-\u9fff]{2,20}?)(?:天气|会不会|下不下|有雨|几点|几分|什么时候|带伞|淋雨|降雨|降水)",
            r"(?:查|查询|看看)?([A-Za-z\u4e00-\u9fff]{2,20}?)(?:今天|今晚|明天|明早|明晚|下午|上午|中午|傍晚|凌晨|未来|现在)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                candidate = match.group(1).strip()
                if candidate not in {"今天", "今晚", "明天", "明早", "未来", "现在"}:
                    return candidate
        if "天气" in normalized:
            candidate = normalized.replace("天气", "").replace("查询", "").replace("查", "").strip()
            return candidate
        return ""

    @staticmethod
    def _extract_weather_time_query(user_text: str) -> str:
        """Preserve the original rain/time concern for the weather tool."""
        keywords = (
            "下雨",
            "降雨",
            "降水",
            "带伞",
            "淋雨",
            "雨什么时候停",
            "什么时候停雨",
            "几点",
            "几分",
            "未来一小时",
            "未来半小时",
            "半小时",
            "今晚",
            "今夜",
            "明早",
            "明晚",
            "下午",
            "上午",
            "中午",
            "傍晚",
            "凌晨",
            "会不会",
            "下不下",
            "有雨吗",
        )
        if any(keyword in user_text for keyword in keywords):
            return user_text.strip()
        return ""

    async def process_user_text(self, session_id: str, user_text: str) -> dict[str, Any]:
        """Produce assistant reply and optional tool execution results."""
        pending_result = await self._resolve_pending_selection(session_id, user_text)
        if pending_result is not None:
            return pending_result

        if self._ark_client.enabled:
            system_prompt = self._build_system_prompt()
            model_output = self._ark_client.chat_with_tools(
                user_text=user_text,
                tools=self._tool_handler.tool_schemas(),
                system_prompt=system_prompt,
            )
            assistant_text = model_output.get("content", "") or "收到。"
            tool_calls = model_output.get("tool_calls", [])
        else:
            fallback = self._fallback_response(user_text)
            assistant_text = fallback["assistant_text"]
            tool_calls = fallback["tool_calls"]

        tool_results = await self._tool_handler.execute_tool_calls(tool_calls)
        for tool_result in tool_results:
            if tool_result.get("name") == "search_music":
                search_data = tool_result.get("result", {})
                candidates = search_data.get("candidates", []) if isinstance(search_data, dict) else []
                if not candidates:
                    assistant_text = "我没有搜到匹配歌曲，你可以换个关键词试试。"
                    continue
                if len(candidates) == 1:
                    only_song = candidates[0]
                    play_call = [
                        {
                            "id": "auto-play-single",
                            "function": {
                                "name": "play_music",
                                "arguments": json.dumps({"song_id": only_song.get("song_id", "")}, ensure_ascii=False),
                            },
                        }
                    ]
                    play_result = await self._tool_handler.execute_tool_calls(play_call)
                    tool_results.extend(play_result)
                    assistant_text = f"只找到一首，正在播放：{only_song.get('name', '未知歌曲')}"
                    continue

                self._pending_song_selection[session_id] = PendingSongSelection(
                    keywords=str(search_data.get("keywords", "")),
                    candidates=candidates,
                )
                options = []
                for index, candidate in enumerate(candidates[:5], start=1):
                    options.append(f"{index}. {candidate.get('name', '未知歌曲')} - {candidate.get('artist', '未知歌手')}")
                assistant_text = "我找到了多个版本，请告诉我要第几首：\n" + "\n".join(options)
            if tool_result.get("name") == "get_weather_forecast":
                weather_data = tool_result.get("result", {})
                if not isinstance(weather_data, dict):
                    continue
                if not weather_data.get("ok"):
                    assistant_text = f"天气查询失败：{weather_data.get('error', '未知错误')}"
                    continue
                answer_text = str(weather_data.get("answer_text", "") or "").strip()
                if answer_text:
                    assistant_text = answer_text
                    continue
                city_name = weather_data.get("city", "")
                forecast_items = weather_data.get("forecast", [])
                if forecast_items:
                    day0 = forecast_items[0]
                    assistant_text = (
                        f"{city_name}今天天气{day0.get('text_day', '')}，"
                        f"气温{day0.get('temp_min', '')}~{day0.get('temp_max', '')}度。"
                    )

        return {
            "assistant_text": assistant_text,
            "tool_results": tool_results,
        }
