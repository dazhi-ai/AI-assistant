#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将「固定人设」与 OpenClaw（或其它任务）产出的「今日新闻简报」合并为整段 system_prompt。

背景：
  小智智控台在 MySQL 中只存一整段 ai_agent.system_prompt，没有单独的「今日新闻」列。
  因此自动化更新时要么每次写入「人设 + 新闻」全文（推荐），要么在模板中用标记只替换新闻区块。

用法：
  # 模式 append：全文 = 基础文件 + 标题 + 日报文件
  BASE_PROMPT_FILE=/path/base.txt DAILY_NEWS_FILE=/path/daily.txt \\
    MERGE_MODE=append python3 merge_system_prompt_for_daily_news.py > full_prompt.txt

  # 模式 markers：基础文件内需包含且仅包含一对标记（见下），中间内容会被日报替换
  MERGE_MODE=markers python3 merge_system_prompt_for_daily_news.py > full_prompt.txt

  # 模式 placeholder：把 BASE 中的占位符 {新闻日报} 整段替换为日报正文（与智控台文案一致时常用）
  MERGE_MODE=placeholder python3 merge_system_prompt_for_daily_news.py > full_prompt.txt

环境变量：
  BASE_PROMPT_FILE   必填，UTF-8，长期稳定的人设与规则
  DAILY_NEWS_FILE    必填，UTF-8，OpenClaw 输出的今日简报（可含多行）
  MERGE_MODE         可选，append（默认）| markers | placeholder
  DAILY_SECTION_TITLE 可选，append 模式下「今日新闻」小节标题，默认：【今日新闻简报】

标记模式（MERGE_MODE=markers）：
  在 BASE 中放置且仅放置一对（顺序固定）：
    <!-- DAILY_NEWS_START -->
    （此处任意占位内容，会被替换）
    <!-- DAILY_NEWS_END -->
  脚本会把 START 与 END 之间的内容换成 DAILY_NEWS_FILE 的正文（首尾换行会自动整理）。

占位符模式（MERGE_MODE=placeholder）：
  BASE 中需包含至少一处字面量 {新闻日报}（与智控台里写法一致）。
  会被替换为 DAILY_NEWS_FILE 的全文（首尾去空白）。若日报为空，替换为空字符串。

输出：
  合并后的 UTF-8 文本打印到 stdout，请重定向到文件再交给 update_agent_prompt_mysql_via_ssh.py 的 PROMPT_FILE。
"""

from __future__ import annotations

import os
import re
import sys

START_MARK = "<!-- DAILY_NEWS_START -->"
END_MARK = "<!-- DAILY_NEWS_END -->"
# 与智控台常见写法一致，勿改除非你在网页里用了别的占位符
NEWS_PLACEHOLDER = "{新闻日报}"


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def merge_append(base: str, daily: str, title: str) -> str:
    """在人设后追加固定标题 + 日报。"""
    base = base.rstrip()
    daily = daily.strip()
    if not daily:
        return base
    return f"{base}\n\n{title}\n{daily}\n"


def merge_markers(base: str, daily: str) -> str:
    """替换 START/END 之间的内容为日报。"""
    if START_MARK not in base or END_MARK not in base:
        print(
            f"错误：MERGE_MODE=markers 但 BASE 中缺少 {START_MARK!r} 或 {END_MARK!r}。",
            file=sys.stderr,
        )
        sys.exit(2)
    pattern = re.compile(
        re.escape(START_MARK) + r".*?" + re.escape(END_MARK),
        re.DOTALL,
    )
    daily_block = daily.strip()
    replacement = f"{START_MARK}\n{daily_block}\n{END_MARK}"
    merged, n = pattern.subn(replacement, base, count=1)
    if n != 1:
        print(
            "错误：标记模式要求 START/END 成对且唯一，请检查 BASE 模板。",
            file=sys.stderr,
        )
        sys.exit(2)
    return merged.rstrip() + "\n"


def merge_placeholder(base: str, daily: str) -> str:
    """将 {新闻日报} 替换为日报正文。"""
    if NEWS_PLACEHOLDER not in base:
        print(
            f"错误：MERGE_MODE=placeholder 但 BASE 中未找到 {NEWS_PLACEHOLDER!r}。",
            file=sys.stderr,
        )
        sys.exit(2)
    block = daily.strip()
    return base.replace(NEWS_PLACEHOLDER, block).rstrip() + "\n"


def main() -> None:
    base_path = os.environ.get("BASE_PROMPT_FILE", "").strip()
    daily_path = os.environ.get("DAILY_NEWS_FILE", "").strip()
    mode = os.environ.get("MERGE_MODE", "append").strip().lower()
    title = os.environ.get("DAILY_SECTION_TITLE", "【今日新闻简报】").strip()

    if not base_path or not daily_path:
        print("请设置 BASE_PROMPT_FILE 与 DAILY_NEWS_FILE", file=sys.stderr)
        sys.exit(2)

    base = _read(base_path)
    daily = _read(daily_path)

    if mode == "append":
        out = merge_append(base, daily, title)
    elif mode == "markers":
        out = merge_markers(base, daily)
    elif mode == "placeholder":
        out = merge_placeholder(base, daily)
    else:
        print("MERGE_MODE 只能是 append、markers 或 placeholder", file=sys.stderr)
        sys.exit(2)

    sys.stdout.write(out)


if __name__ == "__main__":
    main()
