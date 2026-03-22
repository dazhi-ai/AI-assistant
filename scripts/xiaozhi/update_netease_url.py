#!/usr/bin/env python3
"""将 .config.yaml 中 netease_api_url 改为 Docker 网关 IP"""

TARGET = "/opt/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml"

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

old = 'netease_api_url: "http://124.223.174.173:3000"'
new = 'netease_api_url: "http://172.17.0.1:3000"'

if old in content:
    content = content.replace(old, new)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: netease_api_url 已更新为 http://172.17.0.1:3000")
elif "172.17.0.1:3000" in content:
    print("SKIP: 已经是正确的网关 IP")
else:
    print("WARN: 未找到 netease_api_url 配置项，请手动检查")

# 验证结果
print("\n--- 当前 plugins 配置 ---")
lines = content.splitlines()
in_plugins = False
for line in lines:
    if line.strip().startswith("plugins:"):
        in_plugins = True
    if in_plugins:
        print(line)
        if line.strip() == "" and in_plugins:
            break
