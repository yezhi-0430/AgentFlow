# 批量评估脚本使用说明

## 功能
自动评估 Langfuse 中已有的追踪记录，使用 GPT-4 打分（0-100分）

## 前置条件

### 1. 环境变量配置
在 `backend/.env` 中添加配置：

```bash
# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
ENABLE_LANGFUSE_TRACING=true

# OpenRouter（用于评估）
OPENAI_API_KEY=sk-or-v1-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
EVAL_MODEL=openai/gpt-4o-mini

# 或使用其他 OpenRouter 模型：
# EVAL_MODEL=anthropic/claude-3-haiku
# EVAL_MODEL=google/gemini-flash-1.5
```

### 2. 安装依赖
```bash
pip install openai
```

## 使用方法

### 评估最近 10 条记录（默认）
```bash
cd backend
python scripts/evaluate_existing_runs.py
```

### 评估更多记录
修改 `scripts/evaluate_existing_runs.py` 最后一行：
```python
evaluator.evaluate_traces(limit=50)  # 评估 50 条
```

## 评估标准

脚本会根据以下维度评分（总分100）：
- **内容相关性**（25分）：是否切题、有用
- **完整性**（25分）：内容是否完整、结构清晰
- **准确性**（25分）：信息是否准确、逻辑清晰
- **表达质量**（25分）：语言流畅、易懂

## 输出示例

```
开始批量评估（最多 10 条）...
============================================================

找到 10 条追踪记录

[1/10] 评估: Langfuse 测试工作流 (20392fe9...)
  输出长度: 245 字符
  评分: 85/100
  理由: 内容质量很高，结构完整，但缺少具体案例...
  [成功] 分数已提交

[2/10] 评估: AI 文章生成 (a42c6f91...)
  输出长度: 680 字符
  评分: 92/100
  理由: 文章切题且深入，语言流畅，有具体例子...
  [成功] 分数已提交

...

============================================================
批量评估完成！
  已评估: 8 条
  已跳过: 2 条
  总计: 10 条

请访问 Langfuse 查看评分：
  https://cloud.langfuse.com
```

## 在 Langfuse 中查看

1. 访问 https://cloud.langfuse.com
2. 进入你的项目
3. 点击任意 Trace
4. 查看 **Scores** 部分
5. 你会看到：
   ```
   llm-judge-quality: 85/100
   "内容质量很高，结构完整，但缺少具体案例"
   ```

## 自定义评估标准

修改 `evaluate_output_quality()` 方法中的 `eval_prompt`：

```python
eval_prompt = f"""
你是文章质量专家。评估标准：

1. 创意性 (0-30分)
2. 可读性 (0-30分)
3. 实用性 (0-40分)

内容: {output}

返回 JSON: {{"score": 85, "reasoning": "..."}}
"""
```

## 成本估算

- 使用模型：`gpt-4o-mini`
- 每次评估约：500-1000 tokens
- 每条评估成本：约 $0.001
- 评估 100 条：约 $0.10

## 注意事项

1. **API Key 安全**：不要提交 `.env` 文件到 Git
2. **输出长度**：自动截断超过 2000 字符的输出
3. **速率限制**：大批量评估时注意 OpenAI API 限制
4. **跳过条件**：
   - 没有输出的追踪会被跳过
   - 获取失败的追踪会被跳过

## 扩展功能

### 只评估特定类型的追踪
```python
# 修改脚本，添加过滤条件
traces = self.langfuse.fetch_traces(
    limit=limit,
    name="文章生成工作流"  # 只评估这个工作流
)
```

### 评估特定时间段
```python
from datetime import datetime, timedelta

# 评估最近 7 天的数据
seven_days_ago = datetime.now() - timedelta(days=7)
traces = self.langfuse.fetch_traces(
    limit=limit,
    from_timestamp=seven_days_ago
)
```

### 导出评分报告
```python
# 在脚本末尾添加
import pandas as pd

results = []
for trace in traces:
    results.append({
        "trace_id": trace.id,
        "name": trace.name,
        "score": evaluation["score"],
        "reasoning": evaluation["reasoning"]
    })

df = pd.DataFrame(results)
df.to_csv("evaluation_report.csv", index=False)
print("报告已保存到 evaluation_report.csv")
```
