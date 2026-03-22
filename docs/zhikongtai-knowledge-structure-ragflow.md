# 智控台「知识库」配置结构说明（RAGFlow）

本文档根据 **智控台界面** 与官方 **[ragflow 集成指南](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/docs/ragflow-integration.md)** 整理，便于与 **外部定时写入聊天素材** 的方案对齐。

---

## 1. 菜单位置

- 顶部：**模型配置**
- 左侧：**知识库**（需先在 **参数字典 → 系统功能配置** 中勾选启用「知识库」后才会出现）
- 与 **语音活动检测 / 语音识别 / 大语言模型 / … / 记忆** 等并列

---

## 2. 列表页字段（与你截图一致）

| 列名 | 含义 |
|------|------|
| 选择 | 批量操作复选框 |
| 模型ID | 内置示例常为 `RAG_RAGFlow` |
| 模型名称 | 展示名，如 `RAGFlow` |
| 接口类型 | `ragflow`（表示走 RAGFlow 协议） |
| 是否启用 | 开关 |
| 是否默认 | 是否作为默认知识库后端 |
| 操作 | 修改 / 创建副本 / 删除 |

底部常见按钮：**全选**、**新增**、**删除**；支持按模型名称搜索。

---

## 3. 「修改模型」弹窗结构

### 3.1 模型信息

| 项 | 说明 |
|----|------|
| 是否启用 | 总开关 |
| 模型名称 | 如 `RAGFlow` |
| 模型编码 | 如 `ragflow` |
| 供应商 | 下拉选 `RAGFlow` |
| 排序号 | 数字 |
| 文档地址 | 可填 RAGFlow 文档链接（如 GitHub README） |
| 备注 | 官方常提示部署教程与取 Key 方式 |

备注中通常会引用：

- RAGFlow 中文 README：<https://github.com/infiniflow/ragflow/blob/main/README_zh.md>
- 小智侧集成教程：<https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/docs/ragflow-integration.md>  
  （部署 RAGFlow、智控台填服务地址与 API Key、建知识库、智能体绑定知识库等 **以该文档为准**）

### 3.2 调用信息（核心）

| 项 | 说明 |
|----|------|
| **服务地址** | RAGFlow Web/API 根地址，例如 `http://<宿主机或内网IP>:8008`。**必须能被 `xiaozhi-esp32-server`（Docker）访问到**。若填 `http://localhost`，仅当 RAGFlow 与小智服务在同一网络命名空间且 localhost 语义一致时才有效；**跨容器时一般用宿主机 IP、`host.docker.internal` 或 Docker 网络内服务名**。 |
| **API 密钥** | 在 RAGFlow 登录后，右上角 **头像 → API → Create new Key** 生成。 |

保存后，小智在对话中检索知识会通过该地址与 Key 调用 RAGFlow。

---

## 4. 与「外部服务器定时写入」的关系

- **智控台这一页只配置「连哪一个 RAGFlow、用什么 Key」**，不负责接收第三方 HTTP 推送正文。
- **聊天素材的实际存储与索引在 RAGFlow（及你在智控台「知识库」菜单里创建的知识库/文档）**。
- 因此：**外部定时任务应把内容写入 RAGFlow 侧**（例如其 **HTTP API 上传文档**、或官方支持的批量导入方式），使与智能体绑定的知识库持续更新。  
  具体 API 路径与鉴权以 **当前部署的 RAGFlow 版本文档** 为准（见 [RAGFlow 文档](https://github.com/infiniflow/ragflow)）。
- 若仅少量更新，也可在智控台 **知识库 → 详情 → 上传文档 → 解析**，但不适合高频自动化。

---

## 5. 智能体如何用上知识库

在智控台 **智能体 → 配置角色** 中，通过 **编辑功能** 等为该智能体勾选已创建的知识库（官方集成文档「第三步」）。  
未绑定时，即使 RAGFlow 配置正确，对话也可能不检索该库。

---

## 6. 版本与功能开关

- 官方说明建议智控台 **≥ 0.8.7** 再配置 RAGFlow 知识库接口。
- 「知识库」总开关在 **参数字典 → 系统功能配置**。

---

## 7. 与本仓库 `AI-assistant` 中本地 ingest 的区别

| 方式 | 作用范围 |
|------|----------|
| 智控台 + RAGFlow（本文） | **小智设备日常对话** 的检索素材 |
| 本仓库 `KNOWLEDGE_HTTP_PORT` / `knowledge_base.jsonl` | 仅 **`python main.py` WebSocket 助手**，与小智/RAGFlow **无关** |

二者勿混用；给小智用的素材请走 **RAGFlow（+ 智控台维护与绑定）**。
