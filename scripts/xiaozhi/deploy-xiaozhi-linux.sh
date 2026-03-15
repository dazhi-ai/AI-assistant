#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash deploy-xiaozhi-linux.sh /opt/xiaozhi-esp32-server YOUR_ARK_API_KEY
#
# Note:
# - Requires conda installed and available in PATH.
# - This script configures xiaozhi-server to use DoubaoLLM.

INSTALL_DIR="${1:-/opt/xiaozhi-esp32-server}"
ARK_API_KEY="${2:-}"

if [[ -z "${ARK_API_KEY}" ]]; then
  echo "ARK API key is required as second argument."
  exit 1
fi

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "Directory not found: ${INSTALL_DIR}"
  echo "Please clone xiaozhi-esp32-server first."
  exit 1
fi

XIAOZHI_DIR="${INSTALL_DIR}/main/xiaozhi-server"
if [[ ! -d "${XIAOZHI_DIR}" ]]; then
  echo "Missing xiaozhi-server directory: ${XIAOZHI_DIR}"
  exit 1
fi

conda create -n xiaozhi-esp32-server python=3.10 -y
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate xiaozhi-esp32-server

cd "${XIAOZHI_DIR}"
pip install -r requirements.txt
mkdir -p data

cat > data/.config.yaml <<EOF
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  websocket: ws://YOUR_SERVER_IP:8000/xiaozhi/v1/

selected_module:
  LLM: DoubaoLLM
  Intent: function_call
  TTS: EdgeTTS

LLM:
  DoubaoLLM:
    type: openai
    base_url: https://ark.cn-beijing.volces.com/api/v3
    model_name: doubao-1-5-pro-32k-250115
    api_key: ${ARK_API_KEY}
EOF

echo "Config generated: ${XIAOZHI_DIR}/data/.config.yaml"
echo "Run manually for smoke test:"
echo "  conda activate xiaozhi-esp32-server && cd ${XIAOZHI_DIR} && python app.py"
