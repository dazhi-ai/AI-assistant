#!/usr/bin/env python3
"""测试容器内通过不同IP访问网易云API的连通性"""
import urllib.request

for ip in ["172.17.0.1", "172.19.0.1", "172.18.0.1"]:
    url = f"http://{ip}:3000/banner?type=0"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            print(f"OK  {ip}:3000  status={r.status}")
    except Exception as e:
        print(f"FAIL {ip}:3000  {e}")
