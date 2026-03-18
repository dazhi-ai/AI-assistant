#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 小智后端一键配置脚本（全 API 方案，火山引擎 ASR + TTS + 豆包 LLM）
#
# 用法：
#   bash deploy-xiaozhi-linux.sh \
#       /opt/xiaozhi-esp32-server \
#       <ARK_API_KEY> \
#       <VOLC_APP_ID> \
#       <VOLC_ACCESS_TOKEN> \
#       [SERVER_IP]
#
# 参数说明：
#   $1  INSTALL_DIR        - xiaozhi-esp32-server 源码根目录（需提前 git clone）
#   $2  ARK_API_KEY        - 火山引擎 Ark 平台 API Key（豆包大模型）
#   $3  VOLC_APP_ID        - 火山引擎语音服务 App ID
#   $4  VOLC_ACCESS_TOKEN  - 火山引擎语音服务 Access Token
#   $5  SERVER_IP          - （可选）服务器局域网 IP，默认 127.0.0.1
#
# 前提：
#   - 已安装 conda
#   - 已克隆 xiaozhi-esp32-server：
#       git clone https://github.com/xinnan-tech/xiaozhi-esp32-server.git /opt/xiaozhi-esp32-server
#   - 已在火山引擎控制台开通「语音识别」和「语音合成」服务（开通后等待约 30 分钟生效）
# =============================================================================

INSTALL_DIR="${1:-/opt/xiaozhi-esp32-server}"
ARK_API_KEY="${2:-}"
VOLC_APP_ID="${3:-}"
VOLC_ACCESS_TOKEN="${4:-}"
SERVER_IP="${5:-127.0.0.1}"

# ── 参数校验 ──────────────────────────────────────────────────────────────────
if [[ -z "${ARK_API_KEY}" ]]; then
  echo "[ERROR] ARK_API_KEY (第 2 个参数) 不能为空"
  exit 1
fi
if [[ -z "${VOLC_APP_ID}" ]]; then
  echo "[ERROR] VOLC_APP_ID (第 3 个参数) 不能为空"
  exit 1
fi
if [[ -z "${VOLC_ACCESS_TOKEN}" ]]; then
  echo "[ERROR] VOLC_ACCESS_TOKEN (第 4 个参数) 不能为空"
  exit 1
fi
if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "[ERROR] 目录不存在: ${INSTALL_DIR}"
  echo "  请先执行: git clone https://github.com/xinnan-tech/xiaozhi-esp32-server.git ${INSTALL_DIR}"
  exit 1
fi

XIAOZHI_DIR="${INSTALL_DIR}/main/xiaozhi-server"
if [[ ! -d "${XIAOZHI_DIR}" ]]; then
  echo "[ERROR] 未找到 xiaozhi-server 子目录: ${XIAOZHI_DIR}"
  echo "  请确认 INSTALL_DIR 指向 xiaozhi-esp32-server 仓库根目录"
  exit 1
fi

# ── 创建 Python 环境并安装依赖 ────────────────────────────────────────────────
echo "[INFO] 创建 conda 环境 xiaozhi-esp32-server (python=3.10) ..."
conda create -n xiaozhi-esp32-server python=3.10 -y
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate xiaozhi-esp32-server

echo "[INFO] 安装 Python 依赖 ..."
cd "${XIAOZHI_DIR}"
pip install -r requirements.txt

# ── 生成配置文件 ───────────────────────────────────────────────────────────────
mkdir -p data

cat > data/.config.yaml <<EOF
# 小智后端配置（全 API 方案，无本地模型）
# 自动生成于 deploy-xiaozhi-linux.sh
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  websocket: ws://${SERVER_IP}:8000/xiaozhi/v1/

selected_module:
  LLM: DoubaoLLM
  ASR: DoubaoASR
  TTS: HuoshanDoubleStreamTTS
  Intent: function_call

LLM:
  DoubaoLLM:
    type: openai
    base_url: https://ark.cn-beijing.volces.com/api/v3
    model_name: doubao-1-5-pro-32k-250115
    api_key: ${ARK_API_KEY}

ASR:
  DoubaoASR:
    type: doubao
    appid: ${VOLC_APP_ID}
    access_token: ${VOLC_ACCESS_TOKEN}
    cluster: volcengine_input_common

TTS:
  HuoshanDoubleStreamTTS:
    type: huoshan
    appid: ${VOLC_APP_ID}
    access_token: ${VOLC_ACCESS_TOKEN}
    voice: zh_female_wanwanxiaohe_moon_bigtts
    cluster: volcano_tts
    output_dir: tmp/

Intent:
  function_call:
    type: function_call
    functions:
      - get_time
      - get_weather
      - play_music
      - open_app
EOF

# ── 输出结果 ───────────────────────────────────────────────────────────────────
echo ""
echo "========================================================="
echo "[SUCCESS] 配置文件已生成: ${XIAOZHI_DIR}/data/.config.yaml"
echo "========================================================="
echo ""
echo "下一步：手动启动验证（仅需 Python Server，无需本地模型）："
echo ""
echo "  conda activate xiaozhi-esp32-server"
echo "  cd ${XIAOZHI_DIR}"
echo "  python app.py"
echo ""
echo "启动成功标志（日志中出现以下内容）："
echo "  OTA  地址: http://${SERVER_IP}:8003/xiaozhi/ota/"
echo "  WS   地址: ws://${SERVER_IP}:8000/xiaozhi/v1/"
echo ""
echo "智控台（全模块安装后才有）访问地址："
echo "  http://${SERVER_IP}:8002"
echo ""
echo "若需要智控台（设备管理/OTA/多用户），请参考："
echo "  docs/任务1.3-智控台部署与接入指南.md"
