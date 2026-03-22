# 小智对话知识库：应走服务端 + 智控台

## 结论（产品/架构）

**日常和小智硬件对话** → 链路是 **Docker 内 `xiaozhi-esp32-server`（Python）**，配置与内容以 **智控台（Java/Web，通常 8002）+ MySQL 等** 为准。

若「外部服务器定时注入」的知识是 **给聊天当素材**，应：

- **落在小智服务端能读到的存储**（与智控台维护的数据一致或同源），  
- **而不是** 本仓库 `d:\AI-assistant` 里为 `python main.py` 单独做的 `data/knowledge_base.jsonl` + `/v1/knowledge/ingest`（那条只服务本仓库 WebSocket 助手）。

## 智控台能维护什么（常见情况）

全模块部署下，智控台通常提供：

- **智能体 / 提示词**：系统提示、人设（适合短、稳定指令）。  
- **若上游版本带「知识库 / 文档 / RAG / 记忆」类菜单**：优先用该能力做「可维护知识」；外部定时任务应对接 **同一套后端 API 或同一数据库表**，这样智控台里也能增删改查。

具体菜单名称与 API 以你当前 **xiaozhi-esp32-server + 智控台** 版本为准（不同版本差异较大）。

## 外部定时写入的推荐落点

1. **官方/智控台若已提供「知识库导入 API」或数据库表文档**  
   → 外部服务按文档 **POST 到智控台后端或写库**（需在安全域内，配 Token / 内网）。

2. **若当前版本没有现成写入接口**  
   → 需要在 **`xiaozhi-esp32-server` Python 服务** 侧增加 **ingest HTTP 接口**（或消费消息队列），写入与智控台共用的存储；智控台只做展示/编辑。  
   → 实现位置在 **小智上游仓库**（如 `xinnan-tech/xiaozhi-esp32-server`），不在本 `AI-assistant` 仓库的 `main.py` 里。

3. **仅少量、低频素材**  
   → 可暂用智控台 **智能体系统提示词** 手工维护；不适合大批量外部定时注入。

## 与本仓库 `KNOWLEDGE_*` 的关系

| 组件 | 用途 |
|------|------|
| 本仓库 `KNOWLEDGE_HTTP_PORT` / `knowledge_base.jsonl` | 仅 **`python main.py` 平板/WebSocket 助手** |
| 小智 Docker + 智控台 | **小智设备日常对话**（你当前目标） |

二者 **不自动打通**；要统一素材，需在 **小智/智控台一侧** 做接入或数据同步。

## 参考部署说明

- 智控台与全模块架构：`任务1.3-智控台部署与接入指南.md`
- 智控台「知识库」界面结构（RAGFlow、`服务地址`/`API 密钥` 等）：[`zhikongtai-knowledge-structure-ragflow.md`](zhikongtai-knowledge-structure-ragflow.md)
- 官方 RAGFlow 部署与智控台对接步骤：[xinnan-tech/xiaozhi-esp32-server `docs/ragflow-integration.md`](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/docs/ragflow-integration.md)
