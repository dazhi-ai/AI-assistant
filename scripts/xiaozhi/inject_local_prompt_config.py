#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小智本地模式（manager-api.url 为空）时，对话使用的 system prompt 来自 config["prompt"]，
agent-base-prompt.txt 仅为 Jinja 外壳，且必须包含 {{ base_prompt }} 占位符。

将合并后的人设+日报写入 data/.config.yaml 的 prompt 键，避免仍使用默认「小智/小志」短文。

用法（一般在容器内执行，data 为挂载目录）：
  python3 inject_local_prompt_config.py [/opt/xiaozhi-esp32-server/data]

依赖：PyYAML（小智镜像通常已带）。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("需要 PyYAML：pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/xiaozhi-esp32-server/data")
    merged_path = root / ".xiaozhi_merged_prompt_body.txt"
    cfg_path = root / ".config.yaml"
    if not merged_path.is_file():
        print(f"缺少合并正文：{merged_path}", file=sys.stderr)
        sys.exit(2)
    if not cfg_path.is_file():
        print(f"缺少配置：{cfg_path}", file=sys.stderr)
        sys.exit(2)
    merged = merged_path.read_text(encoding="utf-8").strip() + "\n"
    raw = cfg_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(raw)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg["prompt"] = merged
    out = yaml.dump(
        cfg,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )
    cfg_path.write_text(out, encoding="utf-8")
    print(f"inject_local_prompt_config: OK, prompt_chars={len(merged)}")


if __name__ == "__main__":
    main()
