"""
play_music 插件 - 网易云音乐版本

替换小智默认的本地文件播放，改为调用自建网易云 API：
  1. 按歌名搜索：/cloudsearch → 取第一条 song_id
  2. 按歌单播放：/user/playlist → 列出所有歌单 → 模糊匹配 → /playlist/track/all 取曲目
  3. 用 /song/url/v1 获取可播放 URL
  4. 通过 HTTP 将音频流下载到 tmp/ 临时文件后推给小智设备

函数参数说明：
  song_name    : 具体歌曲名称（按名搜索时填写，歌单模式时填空字符串）
  playlist_name: 歌单名称关键词（歌单模式时填写，如'摇滚'/'我喜欢'/'工作'，空=我喜欢的音乐）
  song_index   : 歌单第几首（1-based），0 或不填=随机
  single_loop  : 用户明确要求单曲循环时为 True，服务端在整首 Opus 下发结束后按估算时长再次入队，直到新播放或打断

部署步骤：
  1. scp 本文件到服务器 /tmp/，再 docker cp 进容器
  2. 删除容器内 __pycache__，docker restart xiaozhi-esp32-server
"""

import os
import asyncio
import time
import uuid
import random
import json
import urllib.request
import urllib.parse
from pathlib import Path

from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__


def schedule_netease_resume_prompt(conn: "ConnectionHandler") -> None:
    """用户在下一句非唤醒语音后，待助理播报结束再询问是否继续单曲循环。"""
    loop = getattr(conn, "loop", None)
    if loop is None or not loop.is_running():
        return
    old = getattr(conn, "netease_resume_prompt_task", None)
    if old is not None and not old.done():
        old.cancel()
    try:
        conn.netease_resume_prompt_task = loop.create_task(
            _netease_resume_prompt_worker(conn)
        )
    except Exception:
        pass


async def _netease_resume_prompt_worker(conn: "ConnectionHandler") -> None:
    log = conn.logger.bind(tag=TAG)
    try:
        if getattr(conn, "netease_resume_prompt_state", None) != "waiting_assistant_done":
            return
        deadline = time.monotonic() + 180.0
        stable = 0
        while time.monotonic() < deadline:
            if getattr(conn, "netease_resume_prompt_state", None) != "waiting_assistant_done":
                log.info("[单曲循环恢复提示] 状态已变更，取消")
                return
            if not getattr(conn, "client_is_speaking", False):
                stable += 1
                if stable >= 2:
                    await asyncio.sleep(0.35)
                    if not getattr(conn, "client_is_speaking", False):
                        break
                else:
                    await asyncio.sleep(0.2)
            else:
                stable = 0
                await asyncio.sleep(0.2)
        else:
            log.warning("[单曲循环恢复提示] 等待助理播报结束超时，不再询问")
            conn.netease_resume_prompt_state = None
            return

        if getattr(conn, "netease_resume_prompt_state", None) != "waiting_assistant_done":
            return
        conn.netease_resume_prompt_state = None
        snap = getattr(conn, "netease_resume_snapshot", None) or {}
        title = snap.get("title") or "刚才的歌曲"
        prompt = (
            f"刚才的《{title}》单曲循环已暂停。"
            f"需要继续单曲循环吗？说「继续播放」或「接着放」即可；不需要就接着说别的。"
        )
        log.info("[单曲循环恢复提示] 播报询问语")
        sid = uuid.uuid4().hex
        conn.sentence_id = sid
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.FIRST,
                content_type=ContentType.ACTION,
            )
        )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail=prompt,
            )
        )
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=sid,
                sentence_type=SentenceType.LAST,
                content_type=ContentType.ACTION,
            )
        )
    except asyncio.CancelledError:
        log.info("[单曲循环恢复提示] 已取消")
        raise
    except Exception as exc:
        log.error(f"[单曲循环恢复提示] 异常：{exc}")


# 网易云直连音乐写入播放队列后，在 abortHandle 中忽略设备 abort 的时长（秒）。
# 用于降低唤醒词误触导致「歌刚开就断」；需与 core/handle/abortHandle.py 补丁配合部署。
NETEASE_MUSIC_ANTI_INTERRUPT_SEC = 15.0

# 单曲循环时，估算每帧时长（秒）。与设备 hello 里 frame_duration=60 对齐。
NETEASE_OPUS_FRAME_SEC = 60.0 / 1000.0
# 每轮之间多等一小段时间，避免与设备尾包竞态导致叠音
NETEASE_LOOP_GAP_SEC = 0.35

# ============================================================
# 配置：Cookie / User ID 必须通过环境变量提供，禁止将真实密钥提交 Git。
# 网易云 API 常用 Docker 网关 IP 172.17.0.1（容器内访问宿主机 API）。
# ============================================================
_NETEASE_API_URL = os.environ.get("NETEASE_API_URL", "http://172.17.0.1:3000").strip()
_NETEASE_COOKIE = os.environ.get("NETEASE_COOKIE", "").strip()
_FALLBACK_MUSIC_DIR = "./music"
_TIMEOUT = 15
_NETEASE_USER_ID = os.environ.get("NETEASE_USER_ID", "").strip()

# ============================================================
# 函数描述（三参数模式，LLM 根据此描述决定如何调用）
# ============================================================
play_music_function_desc = {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": (
            "唱歌、听歌、播放音乐的方法。"
            "仅在用户明确要求'播放/放歌/听歌/唱歌'时调用，纯查询类问题（如'我有几个歌单'）不要调用此函数。"
            "支持三种模式：①按歌名搜索 ②从指定歌单随机/按序播放 ③从默认歌单（我喜欢的音乐）播放。"
            "用户明确要求单曲循环、单首歌循环、一直放这首时，将 single_loop 设为 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "single_loop": {
                    "type": "boolean",
                    "description": (
                        "是否单曲循环。仅当用户明确说「单曲循环」「单首循环」「循环播放这首歌」「一直放这首」等时设为 true；"
                        "普通播放、随机播放、歌单顺序播均为 false。开启后当前这一首会反复播放直到用户发起新的播放指令或断开连接。"
                    ),
                },
                "song_name": {
                    "type": "string",
                    "description": (
                        "具体歌曲名称。用户明确说了歌名时填写，否则填空字符串。\n"
                        "示例：用户说'播放两只老虎' → 填'两只老虎'；"
                        "用户说'随机播放' → 填空字符串''"
                    ),
                },
                "playlist_name": {
                    "type": "string",
                    "description": (
                        "歌单名称或序号（歌单播放模式时填写）。\n"
                        "重要：尽量保留用户原话里的中英文混合歌单名，不要擅自删掉英文。"
                        "例如用户说「王歌 music」「王哥 music」→ playlist_name 填完整「王歌 music」或「王哥 music」，"
                        "不要只填「王歌」导致匹配失败。\n"
                        "规则：\n"
                        "- 用户说播放音乐/随机播放/播放我喜欢的 → 填'我喜欢的音乐'\n"
                        "- 用户说播放某个歌单 → 填用户提到的歌单名原样或核心词（含英文后缀）\n"
                        "- 用户说播放第N个歌单 → 填纯数字，如'3'（表示第3个歌单）\n"
                        "- 用户说了具体歌名、未提歌单 → 填空字符串''\n"
                        "示例：\n"
                        "  用户:播放王哥music歌单 → playlist_name='王哥music'或'王哥 music'\n"
                        "  用户:播放我喜欢的歌 → playlist_name='我喜欢的音乐'\n"
                        "  用户:播放第3个歌单 → playlist_name='3'\n"
                        "  用户:播放两只老虎（只说歌名） → playlist_name=''"
                    ),
                },
                "song_index": {
                    "type": "integer",
                    "description": (
                        "歌单中第几首歌（1开始计数）。0或不填表示随机播放。"
                        "仅在 playlist_name 非空时有效。\n"
                        "示例：\n"
                        "  用户:播放摇滚歌单第3首 → song_index=3\n"
                        "  用户:播放歌单第5首 → song_index=5\n"
                        "  用户:随机播放 → song_index=0"
                    ),
                },
            },
            "required": ["song_name", "playlist_name"],
        },
    },
}

# 小智 core 在连接初始化时会 `from plugins_func.functions.play_music import initialize_music_handler`。
# 若本文件作为 play_music.py 部署却缺少该符号，会导致组件初始化失败并回退「快速提示词」，
# 对话侧将丢失智控台/合并后含「今日新闻简报」的正文（表现为「找不到新闻」）。
MUSIC_CACHE: dict = {}


def _get_music_files_for_init(music_dir: str, music_ext) -> tuple[list, list]:
    """扫描本地音乐目录；与上游 play_music.initialize_music_handler 行为对齐。"""
    root = Path(music_dir)
    files: list[str] = []
    names: list[str] = []
    if not root.is_dir():
        return files, names
    if isinstance(music_ext, str):
        ext_tuple = (music_ext,)
    else:
        ext_tuple = tuple(music_ext) if music_ext else (".mp3", ".wav", ".p3")
    for f in root.rglob("*"):
        if f.is_file() and f.suffix.lower() in ext_tuple:
            rel = str(f.relative_to(root))
            files.append(rel)
            names.append(os.path.splitext(rel)[0])
    return files, names


def initialize_music_handler(conn: "ConnectionHandler"):
    """供 core 调用：预热本地音乐缓存（网易云主路径仍走 play_music 内逻辑）。"""
    global MUSIC_CACHE
    if MUSIC_CACHE == {}:
        plugins_config = conn.config.get("plugins", {}) if conn.config else {}
        if "play_music" in plugins_config:
            raw = plugins_config["play_music"]
            if isinstance(raw, str):
                try:
                    mc = json.loads(raw)
                except Exception:
                    mc = {}
            else:
                mc = raw if isinstance(raw, dict) else {}
            MUSIC_CACHE["music_config"] = mc
            MUSIC_CACHE["music_dir"] = os.path.abspath(mc.get("music_dir", "./music"))
            MUSIC_CACHE["music_ext"] = mc.get("music_ext", (".mp3", ".wav", ".p3"))
            MUSIC_CACHE["refresh_time"] = int(mc.get("refresh_time", 60) or 60)
        else:
            MUSIC_CACHE["music_dir"] = os.path.abspath("./music")
            MUSIC_CACHE["music_ext"] = (".mp3", ".wav", ".p3")
            MUSIC_CACHE["refresh_time"] = 60
        MUSIC_CACHE["music_files"], MUSIC_CACHE["music_file_names"] = (
            _get_music_files_for_init(
                MUSIC_CACHE["music_dir"], MUSIC_CACHE["music_ext"]
            )
        )
        MUSIC_CACHE["scan_time"] = time.time()
    return MUSIC_CACHE


# ============================================================
# 配置读取
# ============================================================
def _get_netease_config(conn: "ConnectionHandler") -> dict:
    """读取网易云插件配置：conn.config 中 plugins.play_music 优先，否则用环境变量默认值。"""
    plugins_config = conn.config.get("plugins", {}) if conn.config else {}
    netease_cfg = plugins_config.get("play_music", {})
    if isinstance(netease_cfg, str):
        try:
            netease_cfg = json.loads(netease_cfg)
        except Exception:
            netease_cfg = {}
    api_url = netease_cfg.get("netease_api_url", "") or _NETEASE_API_URL
    cookie = netease_cfg.get("netease_cookie", "") or _NETEASE_COOKIE
    timeout = int(netease_cfg.get("timeout", 0) or _TIMEOUT)
    fallback = netease_cfg.get("fallback_music_dir", "") or _FALLBACK_MUSIC_DIR
    user_id = netease_cfg.get("netease_user_id", "") or _NETEASE_USER_ID
    conn.logger.bind(tag=TAG).info(
        f"[配置] netease_api_url={api_url.rstrip('/')}, user_id={user_id}"
    )
    return {
        "api_url": api_url.rstrip("/"),
        "cookie": cookie,
        "timeout": timeout,
        "fallback_music_dir": fallback,
        "user_id": user_id,
    }


# ============================================================
# HTTP 工具
# ============================================================
def _http_get_json(url: str, timeout: int = 15) -> dict:
    """同步 HTTP GET 并解析 JSON，出错返回带 error 键的 dict。"""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _build_url(api_url: str, path: str, params: dict, cookie: str) -> str:
    """拼接网易云 API URL，附带 cookie。"""
    query = dict(params)
    if cookie:
        query["cookie"] = cookie
    return f"{api_url}{path}?{urllib.parse.urlencode(query)}"


# ============================================================
# 歌曲搜索（按名）
# ============================================================
def _search_song(api_url: str, cookie: str, keywords: str, timeout: int) -> dict | None:
    """搜索歌曲，返回第一条命中的 {song_id, name, artist} 或 None。"""
    url = _build_url(api_url, "/cloudsearch", {"keywords": keywords, "limit": "5"}, cookie)
    result = _http_get_json(url, timeout)
    songs = result.get("result", {}).get("songs", []) or []
    if not songs:
        return None
    song = songs[0]
    artists = song.get("ar", []) or []
    artist_names = [a.get("name", "") for a in artists if a.get("name")]
    return {
        "song_id": str(song.get("id", "")),
        "name": song.get("name", ""),
        "artist": "/".join(artist_names),
    }


# ============================================================
# 歌曲 URL 获取
# ============================================================
def _get_song_url(api_url: str, cookie: str, song_id: str, timeout: int) -> str:
    """获取歌曲可播放 URL，失败或版权受限返回空字符串。"""
    url = _build_url(
        api_url, "/song/url/v1", {"id": song_id, "level": "standard"}, cookie
    )
    result = _http_get_json(url, timeout)
    data = result.get("data", []) or []
    first = data[0] if data else {}
    return first.get("url", "") or ""


# ============================================================
# 歌单管理（新增：支持任意歌单）
# ============================================================
def _get_user_playlists(api_url: str, cookie: str, user_id: str, timeout: int) -> list:
    """获取用户所有歌单（最多50个），返回 [{id, name, track_count}, ...]。"""
    if not user_id:
        return []
    url = _build_url(
        api_url, "/user/playlist", {"uid": user_id, "limit": "50"}, cookie
    )
    result = _http_get_json(url, timeout)
    playlists = result.get("playlist", []) or []
    return [
        {
            "id": str(p.get("id", "")),
            "name": p.get("name", ""),
            "track_count": p.get("trackCount", 0),
        }
        for p in playlists
        if p.get("id")
    ]


def _parse_ordinal(text: str) -> int:
    """
    从字符串中解析「选第几个歌单」的序号，返回整数（1-based），无法解析返回 0。

    注意：旧实现用「若字符串中任意位置出现中文数字则当序号」会误伤歌名/歌单关键词
    （例如「王歌」里若被误判为序号会选错歌单）。此处仅识别明确的序号表达：
      - 整串为阿拉伯数字：'3'
      - 以「第」开头：'第3'、'第3个'、'第三'、'第三个'
    """
    import re

    CN_NUM = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    t = (text or "").strip().lower()
    if not t:
        return 0
    # 整串就是数字 → 用户说「播放3」选第3个歌单
    if re.fullmatch(r"\d+", t):
        return int(t)
    # 「第」+ 阿拉伯数字（允许整句里出现，如「播放第3个歌单」）
    m = re.search(r"第\s*(\d+)", t)
    if m:
        return int(m.group(1))
    # 「第」+ 简单中文数字（十以内）
    m = re.search(r"第\s*([一二三四五六七八九十]+)", t)
    if m:
        chunk = m.group(1)
        for ch, val in CN_NUM.items():
            if ch in chunk:
                return val
    return 0


def _fuzzy_match_playlist(playlists: list, keyword: str) -> dict | None:
    """
    从歌单列表中匹配，返回最佳匹配歌单或 None。

    匹配优先级（从高到低）：
      1. 序号引用：用户说"第3个"/"第三"/"3号" → 返回第 N 个歌单
      2. 特殊关键词：'我喜欢'/'喜欢'/'liked' → 第一个歌单
      3. 完全匹配歌单名
      4. 歌单名包含关键词（关键词是歌单名子串）
      5. 关键词包含歌单名（歌单名是关键词子串）
      6. difflib 相似度 ≥ 0.4（模糊匹配）
    """
    import difflib

    if not playlists:
        return None
    if not keyword:
        return playlists[0]

    kw = keyword.strip().lower()

    # 1. 序号引用（如 "第3个"、"3"、"第三"）
    ordinal = _parse_ordinal(kw)
    if ordinal >= 1:
        idx = max(0, min(ordinal - 1, len(playlists) - 1))
        return playlists[idx]

    # 2. 特殊关键词 → 第一个歌单（我喜欢的音乐）
    liked_keywords = {"我喜欢", "喜欢", "liked", "我喜欢的音乐", "favorite", "favourite",
                      "喜欢的音乐", "我喜欢的"}
    if kw in liked_keywords or any(lk in kw for lk in liked_keywords):
        return playlists[0]

    # 3. 完全匹配
    for p in playlists:
        if p["name"].lower() == kw:
            return p

    # 4. 歌单名包含关键词
    candidates = [p for p in playlists if kw in p["name"].lower()]
    if candidates:
        return candidates[0]

    # 5. 关键词包含歌单名
    candidates2 = [p for p in playlists if p["name"].lower() in kw]
    if candidates2:
        return candidates2[0]

    import re

    def _cn_only(s: str) -> str:
        """去掉英文与数字与空白，仅保留中文等，用于「王歌 music」vs「王哥music」。"""
        return re.sub(r"[a-zA-Z0-9\s]+", "", s)

    # 5a. 中文核心互含（≥2 字），解决 LLM/ASR 带空格或英文而后缀与歌单名不一致
    # 例：关键词「王歌 music」→ kw_cn「王歌」；歌单「王哥music」→ ncn「王哥」；需靠 6/7 步
    # 例：关键词较长含完整歌单中文核：ncn in kw_cn
    kw_cn_early = _cn_only(kw)
    if len(kw_cn_early) >= 2:
        by_in_name = [
            p for p in playlists if kw_cn_early in _cn_only(p["name"].lower())
        ]
        if by_in_name:
            # 优先更短的歌单名（通常更贴近用户说的专名，如「王哥music」）
            by_in_name.sort(key=lambda p: len(_cn_only(p["name"].lower())))
            return by_in_name[0]
        by_name_in_kw = [
            p
            for p in playlists
            if len(_cn_only(p["name"].lower())) >= 2
            and _cn_only(p["name"].lower()) in kw_cn_early
        ]
        if by_name_in_kw:
            by_name_in_kw.sort(key=lambda p: -len(_cn_only(p["name"].lower())))
            return by_name_in_kw[0]

    # 5b. 英文/数字 token：用户说「王歌 music」而歌单名是「王哥music」
    tokens = re.findall(r"[a-zA-Z]{2,}|\d+", kw)
    for t in tokens:
        tl = t.lower()
        hits = [p for p in playlists if tl in p["name"].lower()]
        if not hits:
            continue
        if len(hits) == 1:
            return hits[0]
        # 多个歌单都含 music 等词时，用中文首字缩小范围
        if kw_cn_early:
            narrowed = [
                p
                for p in hits
                if kw_cn_early[0] in _cn_only(p["name"].lower())
            ]
            if narrowed:
                narrowed.sort(key=lambda p: len(_cn_only(p["name"].lower())))
                return narrowed[0]
        hits.sort(key=lambda p: len(p["name"]))
        return hits[0]

    def _first_char_gate(kw_cn: str, name_cn: str) -> bool:
        """
        关键词≥2个中文时，要求首字出现在歌单中文核心里。
        避免「王歌」仅因与「的歌」共现「歌」而误匹配「66的歌」。
        """
        if len(kw_cn) < 2:
            return True
        return kw_cn[0] in name_cn

    names = [p["name"].lower() for p in playlists]
    kw_cn = kw_cn_early if kw_cn_early else _cn_only(kw)

    # 5.5 中文关键词≥2 字时，只在「歌单中文核心里包含首字」的子集中模糊匹配
    # 日志曾出现：关键词「王歌」误匹配「66的歌」（仅因 difflib 与「歌」字干扰）
    if len(kw_cn) >= 2:
        restricted = [
            p for p in playlists if kw_cn[0] in _cn_only(p["name"].lower())
        ]
        if restricted:
            names_r = [p["name"].lower() for p in restricted]
            close_r = difflib.get_close_matches(kw, names_r, n=5, cutoff=0.25)
            for cand in close_r:
                for p in restricted:
                    if p["name"].lower() == cand:
                        return p

    # 6. difflib 全名模糊匹配（多候选 + 首字门槛）
    close = difflib.get_close_matches(kw, names, n=5, cutoff=0.35)
    for cand in close:
        idx = names.index(cand)
        n_cn = _cn_only(cand)
        if kw_cn and len(kw_cn) >= 2 and not _first_char_gate(kw_cn, n_cn):
            continue
        return playlists[idx]

    # 7. 剥离 ASCII 后再比较 + 常见误识「王歌」→「王哥」
    # 例：关键词'王歌'(来自'王歌 music') vs 歌单名'王哥music'
    names_cn = [_cn_only(p["name"].lower()) for p in playlists]
    kw_variants = list(
        dict.fromkeys(
            [kw_cn, kw_cn.replace("歌", "哥"), kw_cn.replace("哥", "歌")]
        )
    )
    for kvar in kw_variants:
        if not kvar:
            continue
        close_cn = difflib.get_close_matches(kvar, names_cn, n=5, cutoff=0.35)
        for cand_cn in close_cn:
            idx = names_cn.index(cand_cn)
            if len(kvar) >= 2 and not _first_char_gate(kvar, cand_cn):
                continue
            return playlists[idx]

    # 8. 全局相似度兜底（不设首字门槛），尽量避免「完全找不到」
    best_p, best_r = None, 0.0
    for p in playlists:
        n = p["name"].lower()
        r = difflib.SequenceMatcher(None, kw, n).ratio()
        if kw_cn:
            r = max(r, difflib.SequenceMatcher(None, kw_cn, _cn_only(n)).ratio())
            for alt in (kw_cn.replace("歌", "哥"), kw_cn.replace("哥", "歌")):
                if alt != kw_cn:
                    r = max(
                        r, difflib.SequenceMatcher(None, alt, _cn_only(n)).ratio()
                    )
        if r > best_r:
            best_r, best_p = r, p
    if best_p and best_r >= 0.30:
        return best_p

    return None


def _get_playlist_songs(api_url: str, cookie: str, playlist_id: str, timeout: int) -> list:
    """获取指定歌单的完整曲目列表（最多200首），返回 [{song_id, name, artist}, ...]。"""
    if not playlist_id:
        return []
    url = _build_url(
        api_url,
        "/playlist/track/all",
        {"id": playlist_id, "limit": "200"},
        cookie,
    )
    tracks_result = _http_get_json(url, timeout)
    songs = tracks_result.get("songs", []) or []
    result_list = []
    for song in songs:
        artists = song.get("ar", []) or []
        artist_names = [a.get("name", "") for a in artists if a.get("name")]
        result_list.append(
            {
                "song_id": str(song.get("id", "")),
                "name": song.get("name", ""),
                "artist": "/".join(artist_names),
            }
        )
    return result_list


def _pick_song_from_playlist(songs: list, index: int) -> dict | None:
    """
    从曲目列表取一首。
      index <= 0 → 随机
      index >= 1 → 第 index 首（1-based，越界时取最近边界）
    """
    if not songs:
        return None
    if index >= 1:
        idx = max(0, min(index - 1, len(songs) - 1))
        return songs[idx]
    return random.choice(songs)


# ============================================================
# 下载 & 随机文案
# ============================================================
def _download_audio(audio_url: str, dest_path: str, timeout: int = 30) -> bool:
    """将网易云音频 URL 下载到临时文件，成功返回 True。"""
    try:
        req = urllib.request.Request(audio_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0
    except Exception:
        return False


def _random_prompt(song_name: str) -> str:
    """随机生成播放引导语。"""
    prompts = [
        f"正在为您播放，《{song_name}》",
        f"请欣赏歌曲，《{song_name}》",
        f"即将为您播放，《{song_name}》",
        f"现在为您带来，《{song_name}》",
        f"让我们一起聆听，《{song_name}》",
        f"接下来请欣赏，《{song_name}》",
        f"此刻为您献上，《{song_name}》",
    ]
    return random.choice(prompts)


# ============================================================
# 本地回退
# ============================================================
def _find_local_fallback(
    conn: "ConnectionHandler", music_dir: str, song_name: str | None
) -> str | None:
    """在本地 music/ 目录里找歌，找不到返回 None。"""
    import difflib

    music_dir = os.path.abspath(music_dir)
    if not os.path.exists(music_dir):
        return None
    exts = {".mp3", ".wav", ".p3"}
    all_files = [
        f for f in os.listdir(music_dir)
        if os.path.splitext(f)[1].lower() in exts
    ]
    if not all_files:
        return None
    if song_name:
        names = [os.path.splitext(f)[0] for f in all_files]
        matches = difflib.get_close_matches(song_name, names, n=1, cutoff=0.4)
        if matches:
            idx = names.index(matches[0])
            return os.path.join(music_dir, all_files[idx])
    return os.path.join(music_dir, random.choice(all_files))


# ============================================================
# 插件入口
# ============================================================
@register_function("play_music", play_music_function_desc, ToolType.SYSTEM_CTL)
def play_music(
    conn: "ConnectionHandler",
    song_name: str = "",
    playlist_name: str = "",
    song_index: int = 0,
    single_loop: bool = False,
):
    """小智 play_music 入口：异步调度 _handle_netease_play。"""
    try:
        if not conn.loop.is_running():
            return ActionResponse(
                action=Action.RESPONSE, result="系统繁忙", response="请稍后再试"
            )

        task = conn.loop.create_task(
            _handle_netease_play(
                conn, song_name, playlist_name, song_index, single_loop=single_loop
            )
        )

        def _done(f):
            try:
                f.result()
            except Exception as exc:
                conn.logger.bind(tag=TAG).error(f"播放任务异常: {exc}")

        task.add_done_callback(_done)

        # 返回 NONE + 空 response，防止主流程立即发 LAST 结束本轮
        # FIRST / LAST 完全由异步任务自己控制
        return ActionResponse(action=Action.NONE, result="指令已接收", response="")
    except Exception as exc:
        conn.logger.bind(tag=TAG).error(f"play_music 入口异常: {exc}")
        return ActionResponse(
            action=Action.RESPONSE, result=str(exc), response="播放音乐时出错了"
        )


async def _enqueue_music_opus_direct(
    conn: "ConnectionHandler",
    music_path: str,
    title: str,
    music_sid: str,
    *,
    single_loop: bool = False,
    loop_generation: int = 0,
) -> None:
    """
    直连播放：不经过火山 TTS 的 FILE→before_stop_play_files→SessionFinished 链路。

    线上日志多次出现：MP3 已「添加音频文件到待播放列表」，但始终无 SentenceType.LAST，
    即 _process_before_stop_play_files 未被调用，设备无声。本函数在 TTS 会话结束
    (activate_session=False) 后，将文件转为 Opus 帧并写入 tts_audio_queue，与设备播放线程
    走同一通道，不依赖豆包下行 EVENT_SessionFinished。

    另：线上曾出现 phase=2 等待 120s 仍无 activate_session=False（火山未回 EVENT_SessionFinished
    或 finish_session 异常），导致「口播正常、音乐永远不下发」。故 phase2 增加「强制超时」
    兜底，在口播任务已走远后仍强制编码下发。
    """
    log = conn.logger.bind(tag=TAG)
    try:
        max_wait = 120.0
        # 已进入 phase2（会话已 start）后，若长期收不到 SessionFinished，最长再等这么多秒就强制下发
        phase2_force_after = 8.0
        slept = 0.0
        step = 0.15
        # 文本队列里在插件 FIRST 之前常有框架的 FIRST/LAST，不能只看 activate_session，
        # 否则会话 A 结束后就误判「已结束」，音乐会在口播前发出。
        # 火山 FIRST 会把 conn.sentence_id 设为 DTO 里的 music_sid，以此为「本会话已开始」标志。
        phase = 0  # 0=等 sentence_id 切到 music_sid；1=等 activate True；2=等 activate False
        t_phase1 = 0.0  # monotonic，进入 phase1 的时间
        t_phase2 = 0.0  # monotonic，进入 phase2 的时间（用于强制兜底）
        while slept < max_wait:
            # 用户点了新歌或新工具调用会递增 loop_generation，旧直连任务应退出
            if getattr(conn, "netease_loop_generation", -1) != loop_generation:
                log.info("[直连音乐] 已有新的播放任务，取消本次直连等待")
                return
            if conn.stop_event.is_set():
                log.info("[直连音乐] 连接已停止，取消播放")
                return
            if getattr(conn, "client_abort", False):
                log.info("[直连音乐] 用户打断，取消播放")
                return
            sid = getattr(conn, "sentence_id", None)
            active = getattr(conn.tts, "activate_session", False)
            if phase == 0 and sid == music_sid:
                phase = 1
                t_phase1 = time.monotonic()
                log.info(f"[直连音乐] 已进入网易云 TTS 会话 sentence_id={music_sid[:12]}…")
            if phase == 1:
                if active:
                    phase = 2
                    t_phase2 = time.monotonic()
                # sid 已匹配但长时间从未见到 active（轮询漏采样或会话极短）
                elif t_phase1 and (time.monotonic() - t_phase1) > 2.5:
                    log.info("[直连音乐] sid 已匹配但未采到激活态，按会话已结束处理并下发")
                    break
            if phase == 2:
                if not active:
                    log.info("[直连音乐] 本会话已结束，开始编码 MP3 并下发")
                    break
                # 火山侧偶发不将 activate_session 置 False，避免无声死等满 max_wait
                if t_phase2 and (time.monotonic() - t_phase2) > phase2_force_after:
                    log.warning(
                        f"[直连音乐] phase2 已等待 {phase2_force_after:.0f}s 仍未结束会话，"
                        "强制编码下发（activate_session 可能未复位）"
                    )
                    break
            await asyncio.sleep(step)
            slept += step
        else:
            log.warning(
                f"[直连音乐] 等待超时 phase={phase}，放弃下发（sid={getattr(conn,'sentence_id',None)!r}）"
            )
            return

        # 给 TTS 音频线程一点时间把语音帧送完，避免与口播尾帧交错
        await asyncio.sleep(0.4)

        if conn.stop_event.is_set():
            return
        # 长等待期间若曾触发过唤醒 abort，client_abort 可能一直为 True，会导致
        # base._audio_play_priority_thread 丢弃整段音乐队列；下发前清除并打日志。
        if getattr(conn, "client_abort", False):
            log.warning("[直连音乐] 下发前清除 client_abort=True，避免音频线程跳过整首歌")
            conn.client_abort = False

        opus_chunks: list[bytes] = []

        def _on_opus_frame(frame_data):
            # util.pcm_to_data_stream 按帧回调 bytes
            if isinstance(frame_data, bytes) and frame_data:
                opus_chunks.append(frame_data)

        await asyncio.to_thread(
            conn.tts.audio_to_opus_data_stream,
            music_path,
            _on_opus_frame,
        )

        # Opus 编码完成，临时 MP3 不再需要，立即清理避免磁盘泄漏
        if music_path and os.path.basename(music_path).startswith("netease_"):
            try:
                os.remove(music_path)
                log.info(f"[直连音乐] 已清理临时文件：{music_path}")
            except OSError:
                pass

        if not opus_chunks:
            log.error(f"[直连音乐] Opus 编码结果为空，文件={music_path}")
            return

        if getattr(conn, "netease_loop_generation", -1) != loop_generation:
            log.info("[直连音乐] 编码完成后发现新播放任务，跳过本次下发")
            return

        # 本轮估算播放时长（秒），用于单曲循环的等待间隔；单曲循环时防打断需覆盖整首，否则约 15s 后
        # 设备 abort 仍会清空队列并置 client_abort，循环任务会在首轮等待中被误判「用户打断」而退出。
        est_play_sec = (
            len(opus_chunks) * NETEASE_OPUS_FRAME_SEC + NETEASE_LOOP_GAP_SEC
        )
        shield_slack = 15.0  # 流控/设备节拍与估算误差的缓冲

        # 将一轮 FIRST+MIDDLE*+LAST 写入队列；每轮换新 sentence_id 避免流控串台
        def _put_one_round(loop_round: int) -> bool:
            if getattr(conn, "netease_loop_generation", -1) != loop_generation:
                return False
            conn.sentence_id = uuid.uuid4().hex
            log.info(
                f"[直连音乐] 已切换 conn.sentence_id 用于音乐流控：{conn.sentence_id[:12]}…"
            )
            conn.tts.tts_audio_queue.put((SentenceType.FIRST, None, title))
            for chunk in opus_chunks:
                conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, chunk, title))
            conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
            if single_loop:
                shield_sec = max(
                    NETEASE_MUSIC_ANTI_INTERRUPT_SEC, est_play_sec + shield_slack
                )
            else:
                shield_sec = NETEASE_MUSIC_ANTI_INTERRUPT_SEC
            conn.netease_music_shield_until = time.monotonic() + shield_sec
            if single_loop:
                conn.netease_resume_snapshot = {
                    "single_loop": True,
                    "music_path": music_path,
                    "title": title,
                }
            if loop_round == 0:
                log.info(
                    f"[直连音乐] 下发设备：{title}，Opus帧数={len(opus_chunks)}，文件={music_path}"
                )
                log.info("[直连音乐] 已全部写入 tts_audio_queue")
                log.info(
                    f"[直连音乐] 已启用防打断约 {shield_sec:.0f}s"
                    + (
                        "（单曲循环：覆盖本首估算播放时长，避免误触 abort 断循环）"
                        if single_loop
                        else "（设备 abort 由服务端忽略，降误触）"
                    )
                )
            else:
                log.info(
                    f"[直连音乐] 单曲循环 第 {loop_round + 1} 轮已入队（帧数={len(opus_chunks)}）"
                )
            return True

        if not _put_one_round(0):
            log.info("[直连音乐] 下发前检测到新播放任务，已取消")
            return

        if single_loop:
            log.info("[直连音乐] 单曲循环已开启，曲目按估算时长结束后自动再次入队")
            round_idx = 1
            round_duration = est_play_sec
            while True:
                target = time.monotonic() + round_duration
                while time.monotonic() < target:
                    if conn.stop_event.is_set():
                        log.info("[直连音乐] 连接已停止，结束单曲循环")
                        return
                    if getattr(conn, "netease_loop_generation", -1) != loop_generation:
                        log.info("[直连音乐] 新播放任务已提交，结束单曲循环")
                        return
                    if getattr(conn, "client_abort", False):
                        log.info("[直连音乐] 用户打断，结束单曲循环")
                        return
                    await asyncio.sleep(min(0.25, max(0.0, target - time.monotonic())))
                if not _put_one_round(round_idx):
                    log.info("[直连音乐] 单曲循环：入队前已取消")
                    return
                round_idx += 1
    except Exception as exc:
        log.error(f"[直连音乐] 异常：{exc}")


async def _handle_netease_play(
    conn: "ConnectionHandler",
    song_name: str,
    playlist_name: str,
    song_index: int,
    *,
    single_loop: bool = False,
):
    """
    核心播放逻辑。

    时序（LAST 提前发送 + session 冲突）：
      ① 生成本次音乐专用的 music_sid，只写入每条 TTSMessageDTO.sentence_id，
         绝不提前改写 conn.sentence_id（否则框架队列里的 LAST(A) 会用错 id 去 finish_session，
         豆包侧会话错乱，音乐仍无法播出）。
         同时需配合 huoshan_double_stream：FIRST/LAST 使用 message.sentence_id。
      ② FIRST(ACTION) + MIDDLE(TEXT 占位) → 立即压队，防止 TTS 1秒超时关闭本轮
      ③ 网络请求（搜索/歌单）
      ④ MIDDLE(TEXT 公告)
      ⑤ 下载音频
      ⑥ LAST(ACTION) 结束 TTS 会话；MP3 改由 _enqueue_music_opus_direct 在会话结束后直送
         tts_audio_queue（绕过 SessionFinished 才能触发的 FILE 管道，解决「待播放列表有、设备无声」）
    """

    # 每次新播放递增代数，用于取消仍在等待/单曲循环中的旧直连任务
    _prev_gen = int(getattr(conn, "netease_loop_generation", 0))
    conn.netease_loop_generation = _prev_gen + 1
    loop_generation = conn.netease_loop_generation
    conn.netease_resume_prompt_armed = False

    # ① 独立会话 id：只放在 DTO 里，由火山 TTS 线程在收到 FIRST 时写入 conn.sentence_id
    music_sid = uuid.uuid4().hex

    cfg = _get_netease_config(conn)
    api_url = cfg["api_url"]
    cookie = cfg["cookie"]
    timeout = cfg["timeout"]
    user_id = cfg["user_id"]

    # 判断播放模式
    sn = (song_name or "").strip()
    pl = (playlist_name or "").strip()
    is_playlist_mode = bool(pl)          # playlist_name 非空 → 歌单模式
    is_search_mode = bool(sn)            # song_name 非空 → 搜索模式
    # 两者都为空时，默认走歌单模式（我喜欢的音乐随机）
    if not is_playlist_mode and not is_search_mode:
        is_playlist_mode = True
        pl = "我喜欢的音乐"

    conn.logger.bind(tag=TAG).info(
        f"[play] 模式={'歌单' if is_playlist_mode else '搜索'} "
        f"song_name={sn!r} playlist_name={pl!r} song_index={song_index} "
        f"single_loop={single_loop}"
    )

    # ① 最先占住本轮：FIRST(ACTION) + 占位 TEXT（必须在任何网络请求之前）
    if is_playlist_mode:
        pos_hint = f"第{song_index}首" if song_index >= 1 else "一首"
        pl_hint = pl if pl != "我喜欢的音乐" else "我喜欢的音乐"
        placeholder = f"正在为您从「{pl_hint}」查找{pos_hint}，请稍候..."
    else:
        placeholder = f"正在为您搜索《{sn}》，请稍候..."

    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=music_sid,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=music_sid,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=placeholder,
        )
    )

    # ② 网络请求
    song_id = None
    display_name = None

    if is_playlist_mode:
        # 获取用户歌单列表，模糊匹配目标歌单
        conn.logger.bind(tag=TAG).info(f"获取用户歌单列表，user_id={user_id}")
        playlists = await asyncio.to_thread(
            _get_user_playlists, api_url, cookie, user_id, timeout
        )
        # 打印所有歌单名，方便调试
        playlist_names = [p["name"] for p in playlists]
        conn.logger.bind(tag=TAG).info(f"账号歌单列表（共{len(playlists)}个）：{playlist_names}")
        matched = _fuzzy_match_playlist(playlists, pl)
        if matched:
            conn.logger.bind(tag=TAG).info(
                f"歌单匹配：{matched['name']} (id={matched['id']}, "
                f"tracks={matched['track_count']})"
            )
            songs = await asyncio.to_thread(
                _get_playlist_songs, api_url, cookie, matched["id"], timeout
            )
            song_info = _pick_song_from_playlist(songs, song_index)
            if song_info:
                song_id = song_info["song_id"]
                display_name = song_info["name"]
                conn.logger.bind(tag=TAG).info(
                    f"歌单命中：{display_name} ({song_id})"
                )
            else:
                conn.logger.bind(tag=TAG).warning(f"歌单「{matched['name']}」无曲目")
        else:
            conn.logger.bind(tag=TAG).warning(
                f"未找到关键词「{pl}」对应的歌单，可用歌单：{playlist_names}"
            )
            # 带序号读出歌单列表，用户可以用"第N个"来精确选择（ASR识别数字更准确）
            if playlist_names:
                numbered = "、".join(
                    f"第{i+1}个{name}"
                    for i, name in enumerate(playlist_names[:5])
                )
                no_match_tip = (
                    f"没有找到叫{pl}这个歌单。"
                    f"您共有{len(playlist_names)}个歌单：{numbered}。"
                    f"您可以说播放第几个歌单来选择。"
                )
            else:
                no_match_tip = "没有获取到您的歌单信息，请检查账号配置。"
            conn.logger.bind(tag=TAG).info(f"未匹配提示：{no_match_tip}")
            conn.dialogue.put(Message(role="assistant", content=no_match_tip))
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=music_sid,
                    sentence_type=SentenceType.MIDDLE,
                    content_type=ContentType.TEXT,
                    content_detail=no_match_tip,
                )
            )
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=music_sid,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )
            return  # 无需继续，直接结束本轮

    elif is_search_mode:
        conn.logger.bind(tag=TAG).info(f"网易云搜索：{sn}")
        song_info = await asyncio.to_thread(
            _search_song, api_url, cookie, sn, timeout
        )
        if song_info and song_info.get("song_id"):
            song_id = song_info["song_id"]
            display_name = song_info["name"]
            conn.logger.bind(tag=TAG).info(f"搜索命中：{display_name} ({song_id})")
        else:
            conn.logger.bind(tag=TAG).warning(f"未搜索到「{sn}」")

    # ③ 公告 TEXT（歌名确定后立即发，TTS 排在占位语之后播报）
    announce_name = display_name or sn or "音乐"
    prompt = _random_prompt(announce_name)
    conn.logger.bind(tag=TAG).info(f"发送公告：{prompt}")
    conn.dialogue.put(Message(role="assistant", content=prompt))
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=music_sid,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=prompt,
        )
    )
    # 单曲循环时口播一句，避免用户不知道会反复播放
    if single_loop:
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=music_sid,
                sentence_type=SentenceType.MIDDLE,
                content_type=ContentType.TEXT,
                content_detail="这首歌将单曲循环播放；若要换歌，请直接说播放别的歌曲。",
            )
        )

    # ④ 获取播放 URL（版权失败时对歌单模式自动换一首重试）
    audio_url = ""
    if song_id:
        audio_url = await asyncio.to_thread(
            _get_song_url, api_url, cookie, song_id, timeout
        )
        if not audio_url and is_playlist_mode:
            conn.logger.bind(tag=TAG).warning(f"{display_name} 版权受限，自动换一首")
            # 重新获取歌单，随机挑选最多3首重试
            playlists = await asyncio.to_thread(
                _get_user_playlists, api_url, cookie, user_id, timeout
            )
            matched = _fuzzy_match_playlist(playlists, pl)
            if matched:
                songs = await asyncio.to_thread(
                    _get_playlist_songs, api_url, cookie, matched["id"], timeout
                )
                for _ in range(3):
                    retry_info = _pick_song_from_playlist(songs, 0)  # 0=随机
                    if retry_info and retry_info.get("song_id"):
                        retry_url = await asyncio.to_thread(
                            _get_song_url, api_url, cookie, retry_info["song_id"], timeout
                        )
                        if retry_url:
                            audio_url = retry_url
                            display_name = retry_info["name"]
                            conn.logger.bind(tag=TAG).info(f"换歌成功：{display_name}")
                            break
        if not audio_url:
            conn.logger.bind(tag=TAG).warning(
                f"song_id={song_id} 无播放链接，尝试回退本地"
            )

    # ④ 下载到临时文件
    music_path = None
    if audio_url:
        tmp_dir = os.path.abspath("./tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, f"netease_{uuid.uuid4().hex}.mp3")
        conn.logger.bind(tag=TAG).info(f"下载音频：{audio_url}")
        ok = await asyncio.to_thread(_download_audio, audio_url, tmp_file, 30)
        if ok:
            music_path = tmp_file
            conn.logger.bind(tag=TAG).info(f"下载成功：{tmp_file}")
        else:
            conn.logger.bind(tag=TAG).warning("音频下载失败，尝试回退本地")

    # 回退：本地 music/ 目录
    if not music_path:
        music_path = await asyncio.to_thread(
            _find_local_fallback, conn, cfg["fallback_music_dir"], display_name or sn
        )
        if music_path:
            display_name = os.path.splitext(os.path.basename(music_path))[0]
            conn.logger.bind(tag=TAG).info(f"回退播放本地文件：{music_path}")

    # ⑤ 先压 LAST 结束火山会话，再调度直连音乐（保证口播先发完）
    play_title = display_name or announce_name or "音乐"
    if not music_path:
        conn.logger.bind(tag=TAG).error("网易云和本地均无可播放文件，通知用户")

    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=music_sid,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )
    if music_path:
        conn.logger.bind(tag=TAG).info(
            f"已下载音频，LAST 已入队；将经直连队列播放：{music_path}"
        )
        asyncio.create_task(
            _enqueue_music_opus_direct(
                conn,
                music_path,
                play_title,
                music_sid,
                single_loop=single_loop,
                loop_generation=loop_generation,
            )
        )
    conn.logger.bind(tag=TAG).info("播放流程完成（音乐由直连任务在 TTS 结束后下发）")
