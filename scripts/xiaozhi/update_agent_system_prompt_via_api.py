#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过智控台 manager-api 仅更新智能体的 systemPrompt（角色设定/系统提示）。

适用场景：
  - 方案 3：轻量机每日生成「新闻日报」文本，定时本脚本写入智控台，无需部署 RAGFlow。

依赖：
  - Python 3.10+，标准库 urllib 即可（无第三方包）。

使用前请配置环境变量（勿把真实 Token 写入代码或提交 Git）：
  XIAOZHI_MANAGER_BASE   必填，例如 http://124.223.174.173:8002
  XIAOZHI_AGENT_ID       必填，智控台里该智能体的 id（UUID）
  XIAOZHI_ADMIN_TOKEN    必填，浏览器登录后从 Network 里复制的 Bearer token（不含 Bearer 前缀）
  XIAOZHI_PROMPT_FILE    可选，若设置则从该 UTF-8 文件读取完整 systemPrompt 正文
  XIAOZHI_PROMPT_PREFIX   可选，与 PROMPT_FILE 联用：最终内容 = 前缀 + 文件内容（适合「固定人设 + 日报」）

若未设置 XIAOZHI_PROMPT_FILE，则从标准输入读取全文（适合 pipe）。

文档：docs/zhikongtai-cron-update-agent-prompt.md
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _load_prompt_text() -> str:
    """从文件、环境变量拼接或 stdin 读取要写入的完整 systemPrompt。"""
    path = os.environ.get("XIAOZHI_PROMPT_FILE", "").strip()
    prefix = os.environ.get("XIAOZHI_PROMPT_PREFIX", "")

    if path:
        with open(path, "r", encoding="utf-8") as f:
            body = f.read()
        return f"{prefix}{body}" if prefix else body

    if not sys.stdin.isatty():
        stdin = sys.stdin.read()
        if stdin.strip():
            return f"{prefix}{stdin}" if prefix else stdin

    print(
        "错误：未指定正文。请设置 XIAOZHI_PROMPT_FILE，或通过管道传入文本。",
        file=sys.stderr,
    )
    sys.exit(2)


def _put_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """向智控台发送 PUT JSON，返回解析后的 JSON 对象。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {err_body}", file=sys.stderr)
        sys.exit(1)

    if not raw.strip():
        return {}
    return json.loads(raw)


def main() -> None:
    base = os.environ.get("XIAOZHI_MANAGER_BASE", "").rstrip("/")
    agent_id = os.environ.get("XIAOZHI_AGENT_ID", "").strip()
    token = os.environ.get("XIAOZHI_ADMIN_TOKEN", "").strip()

    if not base or not agent_id or not token:
        print(
            "请设置环境变量：XIAOZHI_MANAGER_BASE、XIAOZHI_AGENT_ID、XIAOZHI_ADMIN_TOKEN",
            file=sys.stderr,
        )
        sys.exit(2)

    # manager-api 的 context-path 为 /xiaozhi
    url = f"{base}/xiaozhi/agent/{agent_id}"
    prompt = _load_prompt_text()
    if not prompt.strip():
        print("错误：systemPrompt 为空。", file=sys.stderr)
        sys.exit(2)

    result = _put_json(url, token, {"systemPrompt": prompt})
    # 上游 Result 常见结构：code == 0 表示成功（以实际返回为准）
    code = result.get("code")
    if code is not None and code != 0:
        print(f"接口返回非成功：{result}", file=sys.stderr)
        sys.exit(1)
    print("已更新 systemPrompt，返回：", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
