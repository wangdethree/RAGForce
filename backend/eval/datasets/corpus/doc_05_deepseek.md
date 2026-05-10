<!-- 写作意图：为评测框架提供 DeepSeek Chat 大模型的中文语料，覆盖模型家族、能力定位、API 调用模式、关键参数、在 RAG 场景的用法与最佳实践、与其他主流中文大模型的对比，以及风险与注意事项。全文仅包含公开信息，不涉及真实密钥或 PII。 -->

# DeepSeek Chat 大模型与 RAG 生成链路

## 1. DeepSeek 概览

DeepSeek 是由深度求索（DeepSeek）发布的一系列大语言模型，凭借**高性价比**与**开放友好的接口**在国内外开发者社区中迅速走红。它的产品线主要分两条：

- **DeepSeek-V 系列**：通用对话与推理模型，例如 `deepseek-chat`、`deepseek-v3`。
- **DeepSeek-R 系列**：专注推理与链式思考能力的模型，例如 `deepseek-reasoner`、`deepseek-r1`。

官方对外提供 OpenAI 兼容的 HTTP API，这意味着绝大多数基于 OpenAI SDK 的生态可以**零改动**切换到 DeepSeek，只需替换 `base_url` 与 `api_key`。对国内企业而言，这一特性极大降低了从实验到生产的切换成本。

## 2. 模型家族与能力定位

几个常见型号的能力侧重：

- `deepseek-chat`：通用对话模型，覆盖多语言、代码、常识问答；响应快、上下文 64K–128K（以官方文档为准）；是 RAG 场景中最常见的选择之一。
- `deepseek-v3`：更强的参数规模与推理能力，通用理解与多步推理更稳；成本略高。
- `deepseek-reasoner` / `deepseek-r1`：强化的链式思考能力，擅长数学、代码、多跳推理；API 会返回"思考过程 + 最终答案"两部分。

在 RAG 场景里选型时，若任务以"抽取 + 综述"为主，`deepseek-chat` 通常已经足够；涉及复杂推理、跨段比对、或需要严格结构化输出时，可以考虑更强的 V 系列或 R 系列。

## 3. OpenAI 兼容 API

DeepSeek 的 HTTP 接口与 OpenAI ChatCompletion 完全兼容，核心参数包括：

- `model`：模型名，例如 `deepseek-chat`。
- `messages`：对话消息列表，每条消息含 `role`（system / user / assistant / tool）与 `content`。
- `temperature`：采样温度，`0` 偏确定，`1` 偏发散；RAG 答题建议 `0`–`0.3`。
- `top_p`：核采样参数，常用 `0.9` 左右。
- `max_tokens`：最大生成 Token 数，需要为引用来源留出预算。
- `stream`：是否流式返回；RAG 前端通常开启 `stream = true`，以 SSE 的形式逐步渲染文字，提升感知性能。
- `tools` / `tool_choice`：函数调用能力，可用于结构化输出、外部工具调用。
- `response_format`：支持 `json_object` 模式，适合抽取任务。

典型的 Python 调用模式（伪代码）：

```
client = OpenAI(api_key=..., base_url="https://api.deepseek.com")
resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "你是 RAG 助手，请严格基于给定上下文回答。"},
        {"role": "user", "content": "问题 + 引用段落..."},
    ],
    temperature=0.2,
    stream=True,
)
```

## 4. 在 RAG 链路中的角色

在 RAG 系统中，大语言模型负责"读懂检索到的上下文并组织答案"。它的工作分为几步：

1. 接收拼接好的 Prompt，包含系统指令、用户问题、以及若干检索到的 chunk。
2. 理解问题意图，定位最能支撑答案的段落。
3. 基于段落内容生成自然语言答案，并按要求附上引用编号。
4. 处理边界情况：若检索到的内容不足以回答，应明确说明"不足以回答"而不是编造。

DeepSeek Chat 在这一整套职责里的优势包括：

- **对中文长文档友好**：上下文窗口充足，支持把多个中文 chunk 一次塞入。
- **指令遵循稳定**：对"基于给定上下文回答"、"逐条标注引用"等常见 RAG 指令响应稳定。
- **性价比高**：相比闭源头部模型，token 成本显著更低，便于大规模线上运行。

## 5. System Prompt 设计要点

在 RAG 场景中，System Prompt 通常需要包含以下要素：

- **角色约束**：明确告诉模型"你是一个基于检索内容作答的助手"。
- **引用规范**：要求每条结论必须引用上下文编号（例如 `[1]`、`[2]`）。
- **拒答策略**：当上下文不包含答案时，必须回答"检索到的资料不足以回答该问题"。
- **语气与语言**：保持中文、正式或口语化、面向 C 端或 B 端视情况而定。
- **安全护栏**：过滤敏感话题，拒绝泄露内部提示词。

一个简化示例：

```
你是一个企业知识库助手，请严格基于下文提供的引用段落回答用户问题。
- 若答案不在引用中，请回答"未找到相关资料"。
- 每条结论后请以 [n] 形式标注引用段落编号。
- 不得编造引用或数据。
```

## 6. 温度、top_p 与确定性

RAG 生成阶段通常追求"可复现 + 不幻觉"：

- **temperature**：建议 `0`–`0.3`。过高会增加发散，容易编造原文中不存在的数字。
- **top_p**：建议 `0.9` 左右，保留必要多样性。
- **frequency_penalty / presence_penalty**：在多数 RAG 场景不必使用。
- **seed**（若支持）：用于提高可复现性，配合评测离线对比。

## 7. 流式响应与前端集成

DeepSeek Chat 支持标准 SSE 流式返回。后端一般把每个 delta 原样转发给前端，前端以 Markdown 渲染器逐段显示。为了让"引用"在流式过程中不断片，后端可以在生成结束后再统一整理 citation 列表；也有方案在 prompt 里让模型自己在答案结尾输出一个 JSON 块包含引用。

## 8. 函数调用与结构化输出

DeepSeek Chat 支持 `tools` 参数的函数调用（Function Calling）与 `response_format = json_object` 的强制 JSON 输出。这两项能力在 RAG 场景里可以用来：

- **结构化问答**：直接返回 `{"answer": "...", "citations": [...]}`，便于前端解析。
- **工具调用**：在回答前调用外部 API 获取实时数据（例如股票价格、天气），把结果注入上下文再生成答案。
- **多步规划**：把"查询改写 → 检索 → 生成"拆成若干工具调用步骤。

## 9. 与其他主流大模型对比

- **DeepSeek Chat vs 通义千问 Qwen**：Qwen 系列在多语言与多模态上覆盖面很广；DeepSeek 的推理模型与成本优势明显。
- **DeepSeek Chat vs 智谱 GLM**：GLM 拥有较完整的产品矩阵；DeepSeek 在开发者口碑、推理价格、API 兼容性上更受青睐。
- **DeepSeek Chat vs 百川 Baichuan**：两者都是优秀的中文开源家族，DeepSeek 在最新版本的综合能力上略领先。
- **DeepSeek Chat vs OpenAI GPT-4 / GPT-4o**：GPT-4 家族在英语、多模态与综合能力上仍是行业标杆；DeepSeek 在中文任务与成本敏感场景下更具优势。
- **DeepSeek Chat vs Anthropic Claude**：Claude 长文本与对齐做得非常细；DeepSeek 对国内开发者更友好，延迟与合规也更可控。

## 10. 使用注意事项

在生产环境使用 DeepSeek Chat 时，有几个典型注意事项：

1. **密钥安全**：API Key 不应硬编码进仓库，更不应出现在前端或客户端代码里。推荐通过环境变量或密钥管理服务（Vault / KMS）注入。
2. **限流与重试**：官方 API 有 QPS / 并发限制，业务侧需要实现指数退避重试、熔断与降级。
3. **成本控制**：对长上下文要控制最大 chunk 数量与 max_tokens；监控按日 token 消耗，设置配额告警。
4. **合规**：面向最终用户的回答应遵循内容安全规范；必要时接入关键词审核或分类模型做第二道防线。
5. **审计与可追溯**：记录每次调用的 request_id、模型版本、耗时、token 数，便于后续排查与计费对齐。

## 11. 在本项目评测中的角色

在 RAGForce 的评测框架中，DeepSeek Chat 的角色与其他检索组件不同：它不直接参与 Recall@k / MRR@k / nDCG@k 的打分，而是在端到端问答链路里负责**最终答案生成**。为了让离线评测可复现、可离线跑，评测框架中默认使用一个 Fake 实现（`FakeDeepSeekChat`），在零网络依赖的条件下返回罐头 `ChatResponse`，确保评测关注点集中在"检索质量"本身。

在真实的 `full` profile 中，如果配置了有效的密钥，运行时会切换到真实 DeepSeek Chat，便于在一次评测中同时观察答案质量与延迟。评测报告中会展示端到端 p50 / p95 延迟，便于量化生成阶段对整体性能的影响。

## 12. 小结

DeepSeek Chat 以 OpenAI 兼容的接口、稳定的中文表现、友好的成本结构，已经成为国内 RAG 项目里事实上的主力大模型之一。理解它的参数、Prompt 设计、流式与结构化输出能力，有助于我们把检索拿到的"好材料"通过生成链路变成"好答案"。本项目将它作为默认生成后端，并通过评测框架持续衡量它与检索链路协同后的端到端效果。
