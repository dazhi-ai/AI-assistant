# AI助手非 Docker 部署说明（systemd）

## 1. 部署前提
- 目标系统：Linux（systemd）
- 已安装：Python 3.10+、Node.js 18+、npm、git
- 项目路径示例：
  - AI 助手后端：`/opt/ai-assistant`
  - 网易云 API：`/opt/NeteaseCloudMusicApi`

## 2. AI助手后端部署
1. 拷贝代码到 `/opt/ai-assistant`
2. 创建虚拟环境并安装依赖
   - `python3 -m venv /opt/ai-assistant/.venv`
   - `/opt/ai-assistant/.venv/bin/pip install -r /opt/ai-assistant/requirements.txt`
3. 复制 `.env.example` 为 `.env` 并填入密钥

## 3. 网易云 API 部署
由于原始 GitHub 仓库已不再维护，建议使用官方增强版 npm 包部署：
1. 创建目录：`sudo mkdir -p /opt/netease-api-runtime`
2. 初始化并安装包：
   - `cd /opt/netease-api-runtime`
   - `npm init -y`
   - `npm install @neteasecloudmusicapienhanced/api`
3. 手动启动验证：
   - `HOST=127.0.0.1 PORT=3000 node ./node_modules/@neteasecloudmusicapienhanced/api/app.js`
4. 接口检查：
   - `curl "http://127.0.0.1:3000/banner?type=0"`

## 4. systemd 服务安装
将本项目中的服务文件拷贝到 `/etc/systemd/system/`：
- `scripts/systemd/ai-assistant.service`
- `scripts/systemd/netease-api.service`

执行命令：
- `sudo systemctl daemon-reload`
- `sudo systemctl enable netease-api`
- `sudo systemctl enable ai-assistant`
- `sudo systemctl start netease-api`
- `sudo systemctl start ai-assistant`

## 5. 状态检查
- `sudo systemctl status netease-api`
- `sudo systemctl status ai-assistant`
- `sudo journalctl -u ai-assistant -f`
- `sudo journalctl -u netease-api -f`

## 6. 安全建议
- `.env` 权限设为仅服务用户可读
- 网易云 API 建议仅监听 `127.0.0.1`
- 对 WebSocket 开启 token 鉴权（`WS_TOKEN`）
