# Langfuse 追踪集成说明

## 功能概述

AgentFlow 已集成 Langfuse 追踪功能，可以记录每次工作流执行的完整过程：

- **工作流级别追踪（Trace）**：记录整个执行的元信息
- **步骤级别追踪（Span）**：记录每个 Agent 步骤的输入、输出、用量和错误

## 快速开始

### 1. 安装 Langfuse 依赖（可选）

```bash
cd backend
pip install ".[tracing]"
```

> 追踪适配器是按 **Langfuse Python SDK 5.x（OpenTelemetry 内核）** 编写的，
> `pyproject.toml` 中限制为 `langfuse>=5,<6`。2.x/3.x 的 API 不同（没有
> `start_observation`），装了旧版本会静默降级成"追踪关闭"。

### 2. 配置环境变量

创建 `.env` 文件（或在已有文件中添加）：

```bash
# Langfuse API 凭据（从 https://cloud.langfuse.com 获取）
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_HOST=https://cloud.langfuse.com

# 启用追踪（默认关闭）
ENABLE_LANGFUSE_TRACING=true
```

### 3. 启动服务

```bash
# 后端
cd backend
python -m uvicorn agentflow.api.app:app --reload

# 前端
cd frontend
npm run dev
```

### 4. 使用应用

正常使用前端创建和执行工作流，所有执行会自动追踪到 Langfuse。

### 5. 查看追踪数据

访问 https://cloud.langfuse.com（或你的自托管地址），在「追踪」里按工作流名或 trace_id 查看完整调用树。

## 内容采集与隐私（重要）

第一批优化后，默认**不把任务、输入输出、错误正文和评分理由上传到 Langfuse**：

| 开关 | 默认 | 行为 |
| --- | --- | --- |
| `ENABLE_LANGFUSE_TRACING` | `false` | 关闭时完全本地运行，不初始化 Langfuse |
| `LANGFUSE_CAPTURE_CONTENT` | `false` | false：只上传 id、pattern、step_index、model、token 用量、耗时、level、脱敏错误摘要；true：允许上传内容，但先脱敏 |

开启内容采集后会自动脱敏：`sk-` / `pk-lf-` / `sk-lf-` 等 Key、Bearer/Authorization、
`*_KEY/*_SECRET/*_TOKEN` 形式的值、长十六进制/字母数字串；`host`/`base_url` 等连接配置直接丢弃。
API Key 与连接配置在任何模式下都不会上传。

追踪的任何失败（初始化、创建、更新、结束、flush）都只写日志与 `last_error`，不会改变业务结果，
也不会覆盖业务正在抛出的原始异常。

## 评分（Scores）

开启 `AUTO_EVALUATE=true` 后，每次工作流执行结束会调用评审模型（LLM-as-a-Judge）给这次运行打分，
并以 `auto-quality`（可配置）写入 Langfuse 的**评分**：

- 评分挂载在本次运行的 trace 上，打开「追踪」→ 对应 trace 也能看到这条评分
- 数值 0-100；评审理由写入 `comment`，但仅在 `LANGFUSE_CAPTURE_CONTENT=true` 时外发；
  `metadata` 始终记录评审模型和 run_id
- 评审失败只打印日志，不会影响工作流结果

### 在 Langfuse 里看评分

1. 左侧菜单「评分」（Scores）→ 列表里出现 `auto-quality` 及分数；
2. 左侧「分析」→ 可以看到分数随时间的趋势图；
3. 打开某条 trace → 详情里能看到挂在该 trace 上的评分和理由。

### 给历史运行补评分

追踪修复前的旧运行不会自动补评分，可手动批量补：

```bash
cd backend
python scripts/evaluate_existing_runs.py --limit 10        # 预览将要评估的运行
python scripts/evaluate_existing_runs.py --limit 10 --yes  # 真正调用评审模型并写入评分
```

> 旧运行可能没有对应的 trace（追踪修复前产生的），分数仍会写入，但可能在 Langfuse 里
> 找不到可点击的 trace。

## 追踪的数据

每次工作流执行会记录一棵完整的 trace 树：

### Trace（工作流级别）
- `run_id` → **trace_id**：由 `client.create_trace_id(seed=run_id)` 稳定推导，
  一条运行就是一个 trace，可用 trace_id 直接定位
- `name`：工作流名称
- `metadata`：
  - `workflow_id`：工作流 ID
  - `run_id`：运行 ID
  - `pattern`：执行模式（sequential/parallel）
  - `task`：初始任务（仅内容采集开启时）
- `output`：结束时写入状态、步骤数、token 总量
- 执行失败时 `level=ERROR`，并带 `status_message`

### Generation（步骤级别，挂在 trace 下）
- `step_id`：步骤 ID
- `agent_name`：执行的 Agent
- `input` / `output`：输入输出内容（仅内容采集开启时）
- `model`：使用的模型
- `usage_details`：Token 用量（`input` / `output` / `total`）
- `error`：错误信息（失败时 `level=ERROR`，`status_message` 记录脱敏摘要）
- `metadata`：
  - `step_index`：步骤索引
  - `agent_model`：使用的模型

## 配置选项

### 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `LANGFUSE_PUBLIC_KEY` | 启用时必需 | - | Langfuse 公钥 |
| `LANGFUSE_SECRET_KEY` | 启用时必需 | - | Langfuse 密钥 |
| `LANGFUSE_HOST` | 否 | `https://cloud.langfuse.com` | Langfuse 服务器地址 |
| `ENABLE_LANGFUSE_TRACING` | 否 | `false` | 是否启用追踪 |
| `LANGFUSE_CAPTURE_CONTENT` | 否 | `false` | 是否允许上传任务/输入输出等内容（开启后会脱敏） |
| `AUTO_EVALUATE` | 否 | `false` | 执行结束后是否自动评估并写入评分 |
| `OPENAI_API_KEY` | 评估时必需 | - | 评审模型密钥（兼容 OpenRouter） |
| `OPENAI_BASE_URL` | 否 | `https://api.openai.com/v1` | 评审模型接口地址 |
| `EVAL_MODEL` | 否 | `openai/gpt-4o-mini` | 评审模型 |
| `EVAL_SCORE_NAME` | 否 | `auto-quality` | 写入 Langfuse 的评分名称 |

### 自托管 Langfuse

如果使用自托管的 Langfuse 实例：

```bash
LANGFUSE_HOST=https://your-langfuse-instance.com
```

## 优雅降级

### 无配置时
- 追踪自动关闭
- 使用 `_DummyTracer` 占位
- 不影响业务执行
- 不会报错

### 无依赖时
- 未安装 `langfuse` 包时自动跳过
- `TRACING_AVAILABLE = False`
- 不影响应用启动

### 追踪失败时
- 追踪错误不会中断工作流执行
- 业务逻辑优先

## 测试

```bash
cd backend

# 运行所有测试
python -m pytest tests/ -v

# 只运行 Langfuse / 评分相关测试（全部离线，不联网）
python -m pytest tests/test_langfuse_integration.py tests/test_tracing_v5.py tests/test_auto_evaluate.py -v

# 端到端验证追踪链路（真的推数据到 Langfuse 并回查校验，使用假 LLM，不产生模型费用）
python scripts/verify_langfuse_tracing.py
```

## 架构说明

### 集成点

1. **`agentflow/tracing/langfuse.py`**
   - `LangfuseTracer` 类（Langfuse 5.x / OTel）
   - `TraceHandle`：根 trace 句柄（真正的 OTel trace_id）
   - `_DummyTrace` / `_DummySpan` 降级实现
   - `optional_tracing` 上下文管理器

2. **`agentflow/core/workflow.py`**
   - `WorkflowExecutor.__init__` 接收 `enable_tracing` 参数
   - `execute()` 创建 trace，`finally` 中调用 `end_trace()` 结束根 span
   - sequential / parallel / debate / voting 都会创建步骤 span
   - 步骤完成/失败时 `update_step()` 更新并结束 span

3. **`agentflow/api/routes/workflow.py`**
   - `_is_tracing_enabled()` 读取环境变量
   - 创建 `WorkflowExecutor` 时传入 `enable_tracing`

4. **`agentflow/core/auto_evaluate.py`**
   - `auto_evaluate_workflow()`：LLM-as-a-Judge，执行结束后由 `WorkflowExecutor` 调用
   - 用 `client.create_score(name, value, trace_id, data_type="NUMERIC", comment=...)` 写评分
   - trace_id 由 `tracer.trace_id_for_run(run_id)` 推导，不能用 run_id 代替

### 数据流

```
用户请求
    ↓
API 检查 ENABLE_LANGFUSE_TRACING
    ↓
WorkflowExecutor(enable_tracing=True/False)
    ↓
execute() → trace = tracer.trace_workflow(...)   # trace_id = seed(run_id)
    ↓
_execute_*() → span = tracer.trace_step(...)     # 父 span 派生，同一 trace
    ↓
步骤完成 → tracer.update_step(span, output, usage)  # update + end
    ↓
执行结束 → tracer.end_trace(trace, ...)          # 根 span 必须 end
    ↓
AUTO_EVALUATE=true → auto_evaluate_workflow()     # 评审模型打分 → create_score
    ↓
tracer.flush() → OTel 批量导出到 Langfuse
```

> ⚠️ Langfuse 5.x 语义：observation 只有 `end()` 之后才会被批量导出；
> 子 observation 必须从父 observation 派生（或显式传 `trace_context`），
> 否则每个 span 会成为独立 trace。这两点是"组件初始化正常但看不到数据"的典型原因。

## 常见问题

### Q: 为什么追踪没有数据？

A: 先跑端到端验证脚本定位是"没启用"还是"没发送"：

```bash
cd backend
python scripts/verify_langfuse_tracing.py
```

- 报"追踪未启用" → 检查 `ENABLE_LANGFUSE_TRACING=true`、密钥、以及**启动后端时的工作目录**
  （`.env` 在 `backend/` 下，dotenv 按当前目录查找）。
- 报"服务端没收到 trace" → 检查网络/代理、`LANGFUSE_HOST` 区域是否与账号一致
  （例如美区账号需 `https://us.cloud.langfuse.com`）、后端日志里的 `[Langfuse]` 报错。
- 以前 `diagnose.py` 只验证"组件初始化成功"，无法发现"根 span 未 end / 子 span 挂错 trace"
  这类问题，所以会出现"诊断全部正常但看不到数据"。现在由 `tests/test_tracing_v5.py`
  和验证脚本覆盖这些点。

### Q: 为什么「评分」页是空的？

A: 评分页只显示**已写入的 score**，它不是自动根据 trace 生成的。检查：

1. `AUTO_EVALUATE=true` 是否设置（默认关闭）——注意 `WorkflowExecutor` 在**创建工作流时**读取该变量，
   改完 `.env` 后要重新创建工作流/重启后端；
2. `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `EVAL_MODEL` 是否可用（评审模型走 OpenRouter 兼容接口）；
3. 工作流是否有最终输出（失败的运行没有可评估内容）；
4. 后端日志里是否有 `[自动评估] 评分 xx/100 已写入 Langfuse`；若显示"评估失败（不影响工作流）"，
   里面会带评审模型返回的错误；
5. 评分入队到能在 UI 看到通常有几秒延迟；
6. 想给历史运行补评分：`python scripts/evaluate_existing_runs.py --limit 10 --yes`。

### Q: 评分是怎么写进 Langfuse 的？

A: 用 Langfuse 5.x 的 `client.create_score(...)`，挂到本次运行的真实 trace 上
（`trace_id = create_trace_id(seed=run_id)`，不是 run_id 本身）。
评分名默认 `auto-quality`，数值 0-100，`comment` 是评审理由，`metadata` 记录评审模型与 run_id。

### Q: 追踪会影响性能吗？

A: 影响很小：
- 异步发送数据
- 批量上传
- 失败自动重试
- 不阻塞业务逻辑

### Q: 可以只追踪特定工作流吗？

A: 当前是全局开关，未来可以扩展为按工作流配置。

### Q: 追踪数据会保留多久？

A: 由 Langfuse 服务端配置决定，通常：
- 云端版本：根据订阅计划
- 自托管版本：自行配置

## 下一步

- [ ] 添加自定义标签和元数据
- [ ] 支持按工作流启用/禁用追踪
- [x] 自动评估并写入 Langfuse 评分（LLM-as-a-Judge）
- [ ] 收集用户反馈评分（点赞/点踩）
- [ ] 添加追踪数据的可视化面板

## 参考资料

- [Langfuse 官方文档](https://langfuse.com/docs)
- [Python SDK 文档](https://langfuse.com/docs/sdk/python)
- [自托管指南](https://langfuse.com/docs/deployment/self-host)
