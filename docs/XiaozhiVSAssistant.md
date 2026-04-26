# 小智（Xiaozhi）与 ai-assistant 网页端体验差异说明

本文说明：为何同一类问题（例如问天气、多轮追问）在**小智硬件 / xiaozhi-esp32-server** 上表现正常，而在 **ai-assistant 的 WebSocket 网页对话**上却可能出现「答非所问、不记得上文、默认城市不一致」等现象。结论来自本仓库当前实现，而非设备固件内部细节。

---

## 1. 核心结论（一句话）

**两条链路不是同一个「对话大脑」。**  
小智设备连的是 **xiaozhi-esp32-server** 的完整会话与插件管线；网页连的是 **ai-assistant**，由本服务直接调用 **火山 Ark** 完成推理。二者最多在**角色文案（system prompt）**上通过智控台 MySQL 保持部分一致，**会话记忆、天气插件默认城市、工具实现**均可能不同。

---

## 2. 小智端：对话在 xiaozhi-server 内闭环

典型路径：

- 设备 WebSocket 接入 xiaozhi-esp32-server（如 `/xiaozhi/v1/`）。
- 服务端维护**会话与多轮上下文**（历史在小智进程内累积）。
- 配置中常见 **Intent: function_call**，调用自带 **`get_weather`** 等插件。
- 天气等能力在 **`data/.config.yaml`** 中配置，例如 **`default_location`**（用户可设为武汉等）。

因此「明天/后天指哪一天」「未说城市时默认某地」等行为，主要来自：**小智后端的会话状态 + 插件与 yaml 配置 + 该环境下的 LLM 调用方式**。

---

## 3. 网页端：ai-assistant 独立调 Ark，且当前为单轮消息

网页客户端连接的是 **ai-assistant 的 WebSocket**。文本对话由 `AssistantService` 协调，模型调用在 `ArkClient.chat_with_tools`。

**当前实现每次请求只发送两条消息**：一条 `system`、一条**当前用户输入**，**不包含历史多轮**：

- 文件：`src/ark_client.py`
- 逻辑：`messages` 仅含 `system_prompt` 与本轮 `user_text`。

因此用户会感到网页端**「不记得上下文」**——这是当前代码层面的设计（未维护可传入 Ark 的多轮 `messages` 列表），并非「接了小智就会自动带记忆」。

---

## 4. 「assistant 也接了小智」具体接了什么？

本仓库与小智生态的常见衔接包括：

| 机制 | 作用 | 是否让网页问题走小智 LLM |
|------|------|---------------------------|
| **XiaozhiPromptSync** | 从智控台 MySQL 拉取**角色 prompt**，拼入网页助手的 system 文案 | **否**，仅同步文案 |
| **tabletMirrorPatch**（脚本/补丁说明） | 小智**生成完回复后**，将文本推到 ai-assistant，供平板等展示 | **否**，方向是小智 → 助手，不是网页用户话 → 小智推理 |

也就是说：**网页上的每一句用户问题，推理路径仍是 ai-assistant → Ark（+ 本仓库内的 ToolHandler）**，并没有把该句转发给 xiaozhi-esp32-server 的 LLM/Intent 去算。

相关入口可参考：`src/server.py`（组装 `AssistantService`、`XiaozhiPromptSync`）、`scripts/xiaozhi/patches/tabletMirrorPatch.py`（镜像桥接说明）。

---

## 5. 天气等行为不一致的补充原因

1. **默认城市**  
   - 小智：依赖 `.config.yaml` 中天气插件的 **`default_location`**。  
   - ai-assistant：工具由模型传 `city`；在**未启用 Ark、走 fallback** 时，提取不到城市会默认 **北京**（见 `src/assistant_service.py` 中 `_fallback_response` 与 `_extract_weather_city`），与小智配置的武汉等**不一定一致**。

2. **工具名称与实现**  
   - 小智侧多为 **`get_weather`** 插件实现。  
   - ai-assistant 侧为 **`get_weather_forecast`**（`WeatherService` + 和风等配置），参数与解析逻辑不同。

3. **单轮模型 + 工具执行**  
   - 网页路径通常在**一轮**内让模型决定是否调用工具，执行后再组装回复；**未**实现「把 tool 结果再丢回模型做多轮 function 对话」的完整 OpenAI 式多步（若未来要与小智体感完全一致，需单独设计）。

---

## 6. 若要对齐体验，可考虑的改进方向（概览）

以下为产品/架构选项，不在本文展开实现细节：

- **多轮上下文**：在 WebSocket 会话维度维护 `messages` 列表，调用 Ark 时传入历史（注意 token 上限与隐私）。
- **默认城市配置化**：为 `get_weather_forecast` 或 prompt 增加与小智一致的默认城市环境变量/配置。
- **代理到小智**：网页对话改为连接或通过后端转发到 xiaozhi-esp32-server 的会话接口（架构变动大，需统一鉴权与协议）。

---

## 7. 相关源码索引

| 主题 | 路径 |
|------|------|
| Ark 仅 system + 单条 user | `src/ark_client.py` |
| 对话编排、天气 fallback、工具后处理 | `src/assistant_service.py` |
| 工具注册与执行 | `src/tool_handler.py` |
| 服务启动、天气与 prompt 同步 | `src/server.py` |
| 小智配置模板（含天气插件示例） | `scripts/xiaozhi/.config.yaml.*.example`、`deploy-xiaozhi-linux.sh` |
| 小智 → 平板/助手镜像补丁说明 | `scripts/xiaozhi/patches/tabletMirrorPatch.py` |

---

*文档随仓库实现演进，若行为变更请同步更新本节与代码引用。*
