"""
示例：代码审查工作流

这个示例展示了如何使用 AgentFlow 创建一个代码审查系统，
包含多个专门的 Agent 协作完成代码审查任务。
"""
import asyncio
import os
from agentflow.core.workflow import WorkflowExecutor, WorkflowConfig, WorkflowPattern, WorkflowStep
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.agents.llm_agent import LLMAgent
from agentflow.adapters.openai import OpenAIAdapter


async def main():
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.environ["OPENAI_MODEL"]
    # 1. 配置 Agent
    agents = [
        AgentConfig(
            name="code-analyzer",
            role=AgentRole.WORKER,
            system_prompt="""你是一个代码分析专家。
            你的任务是：
            1. 分析代码结构和逻辑
            2. 识别潜在的 bug 和问题
            3. 检查代码规范和最佳实践

            请给出详细的分析报告。""",
            model=model,
            temperature=0.3,
        ),
        AgentConfig(
            name="security-checker",
            role=AgentRole.REVIEWER,
            system_prompt="""你是一个安全专家。
            你的任务是：
            1. 检查代码中的安全漏洞
            2. 识别潜在的安全风险
            3. 提供安全加固建议

            重点关注：SQL 注入、XSS、认证授权等问题。""",
            model=model,
            temperature=0.2,
        ),
        AgentConfig(
            name="performance-analyzer",
            role=AgentRole.REVIEWER,
            system_prompt="""你是一个性能优化专家。
            你的任务是：
            1. 分析代码性能瓶颈
            2. 识别低效的实现
            3. 提供优化建议

            重点关注：时间复杂度、空间复杂度、数据库查询等。""",
            model=model,
            temperature=0.3,
        ),
        AgentConfig(
            name="final-reviewer",
            role=AgentRole.COORDINATOR,
            system_prompt="""你是最终审查者。
            综合之前所有专家的反馈，给出：
            1. 总体评价
            2. 优先级排序的问题列表
            3. 具体的改进建议

            请以清晰的格式输出最终审查报告。""",
            model=model,
            temperature=0.4,
        ),
    ]

    # 2. 配置工作流步骤
    steps = [
        WorkflowStep(id="step1", agent_name="code-analyzer"),
        WorkflowStep(id="step2", agent_name="security-checker"),
        WorkflowStep(id="step3", agent_name="performance-analyzer"),
        WorkflowStep(id="step4", agent_name="final-reviewer"),
    ]

    # 3. 创建工作流配置
    workflow_config = WorkflowConfig(
        name="Code Review Workflow",
        pattern=WorkflowPattern.SEQUENTIAL,
        steps=steps,
        agents=agents,
    )

    # 4. 创建 LLM 适配器（需要设置 API Key）
    adapter = OpenAIAdapter(api_key=api_key)

    # 5. 创建工作流执行器
    executor = WorkflowExecutor(workflow_config)

    # 6. 创建并注册 Agent
    for agent_config in agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    # 7. 注册事件监听
    async def on_step_completed(data):
        print(f"\n{'='*60}")
        print(f"✅ {data['agent']} 完成")
        print(f"⏱  耗时: {data['duration']:.2f}s")
        print(f"📝 结果:\n{data['result'][:200]}...")
        print(f"{'='*60}\n")

    executor.on("step_completed", on_step_completed)

    # 8. 准备待审查的代码
    code_to_review = """
def login(username, password):
    query = "SELECT * FROM users WHERE username='" + username + "' AND password='" + password + "'"
    result = db.execute(query)
    if result:
        session['user'] = username
        return True
    return False
"""

    task = f"""请审查以下 Python 代码：

```python
{code_to_review}
```
"""

    # 9. 执行工作流
    print("🚀 开始代码审查...")
    print(f"📋 任务: {task[:100]}...")

    result = await executor.execute(task)

    # 10. 输出最终结果
    print("\n" + "="*60)
    print("🎉 代码审查完成！")
    print(f"⏱  总耗时: {result['elapsed_time']:.2f}s")
    print(f"💬 消息数: {result['messages']}")
    print("\n📊 最终审查报告:")
    print("="*60)
    print(result['result']['final_result'])
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
