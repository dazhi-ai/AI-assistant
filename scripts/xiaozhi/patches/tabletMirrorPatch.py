"""
小智 → 平板镜像补丁（tabletMirrorPatch.py）

作用：每当 xiaozhi-esp32-server 完成一次 AI 对话回复后，
      将用户说的话和 AI 的完整回复文字通过 WebSocket 推送给 ai-assistant 服务，
      由 ai-assistant 服务负责转发给平板网页并合成语音播放。

部署路径（宿主机）：
  /opt/xiaozhi-esp32-server/main/xiaozhi-server/core/handle/tabletMirrorPatch.py

容器内路径（docker cp 后）：
  /opt/xiaozhi-esp32-server/core/handle/tabletMirrorPatch.py

配置（在小智 docker-compose.yml 或宿主机环境变量中设置）：
  TABLET_BRIDGE_URL   = ws://127.0.0.1:8765   # ai-assistant WebSocket 地址
  TABLET_BRIDGE_TOKEN = <与 ai-assistant .env 中 MIRROR_TOKEN 相同的值>

调用方式（在 connection.py 的 LLM 回复完成后添加）：
  if text_buff:
      try:
          from core.handle.tabletMirrorPatch import mirror_text_to_tablet
          asyncio.run_coroutine_threadsafe(
              mirror_text_to_tablet(query, text_buff),
              self.loop
          )
      except Exception:
          pass
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

# ai-assistant WebSocket 服务地址（与小智同机则用 localhost）
TABLET_BRIDGE_URL = os.getenv("TABLET_BRIDGE_URL", "ws://127.0.0.1:8765")
# 与 ai-assistant .env 中 MIRROR_TOKEN 保持一致
TABLET_BRIDGE_TOKEN = os.getenv("TABLET_BRIDGE_TOKEN", "")

# 持久 WebSocket 连接（懒初始化，断线自动重连）
_ws = None
_lock = asyncio.Lock()


async def _get_connection():
    """获取或重建到 ai-assistant 的 WebSocket 连接。"""
    global _ws
    # 检查连接是否健康
    if _ws is not None:
        try:
            if not _ws.closed:
                return _ws
        except Exception:
            pass
        _ws = None

    # 延迟导入，避免在不需要时引入 websockets 依赖
    try:
        import websockets  # noqa: PLC0415
    except ImportError:
        logger.warning("[TabletMirror] websockets 库未安装，无法桥接平板。")
        return None

    try:
        _ws = await asyncio.wait_for(
            websockets.connect(TABLET_BRIDGE_URL),
            timeout=3,
        )
        # 发送 MIRROR_INIT 握手，以 mirror_token 身份认证
        await _ws.send(json.dumps({
            "type": "MIRROR_INIT",
            "payload": {"token": TABLET_BRIDGE_TOKEN},
        }))
        logger.info("[TabletMirror] 已连接到 %s", TABLET_BRIDGE_URL)
    except Exception as e:
        logger.warning("[TabletMirror] 连接失败: %s", e)
        _ws = None

    return _ws


async def mirror_text_to_tablet(user_text: str, ai_text: str) -> None:
    """
    将 xiaozhi AI 回复推送给 ai-assistant，由其广播给平板网页。

    Args:
        user_text: 用户（语音识别后）的原始文字
        ai_text:   AI 完整回复文字
    """
    if not TABLET_BRIDGE_TOKEN:
        # 未配置 token，静默跳过（不影响正常小智功能）
        return
    if not ai_text:
        return

    try:
        async with _lock:
            ws = await _get_connection()
            if ws is None:
                return
            payload = json.dumps({
                "type": "XIAOZHI_TEXT",
                "payload": {
                    "token": TABLET_BRIDGE_TOKEN,
                    "user_text": user_text,
                    "ai_text": ai_text,
                },
            })
            await ws.send(payload)
            logger.info("[TabletMirror] 已推送至平板: %s…", ai_text[:30])
    except Exception as e:
        logger.warning("[TabletMirror] 推送失败: %s", e)
        # 下次调用时会重连
        global _ws
        _ws = None
