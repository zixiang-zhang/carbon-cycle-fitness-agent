"""
Actor 节点。

职责：
1. 读取用户最近执行日志；
2. 把原始日志压缩成可分析摘要；
3. 在有数据库会话时，结合 Function Calling 做更丰富的工具分析。
"""

import json
from typing import Any, Optional
from uuid import UUID

from app.agent.state import AgentState, LogContext
from app.core.logging import get_logger, log_agent_decision
from app.llm.client import ModelType, get_llm_client
from app.llm.tools import get_tool_definitions
from app.memory.agent_memory import get_agent_memory

logger = get_logger(__name__)

# 限制工具调用轮数，防止模型反复调用工具造成死循环。
MAX_TOOL_ITERATIONS = 5


def _parse_log_data(logs: list[LogContext]) -> dict[str, Any]:
    """把日志列表压缩成 Actor 关心的最新执行摘要。"""
    if not logs:
        return {"status": "no_data", "summary": "没有饮食记录"}

    latest = logs[-1]
    return {
        "status": "success",
        "date": latest.get("date"),
        "actual_intake": {
            "calories": latest.get("actual_calories", 0),
            "protein": latest.get("actual_protein", 0),
            "carbs": latest.get("actual_carbs", 0),
            "fat": latest.get("actual_fat", 0),
        },
        "training_completed": latest.get("training_completed", False),
        "meal_count": latest.get("meal_count", 0),
    }


async def _run_tool_calling_loop(
    messages: list[dict[str, Any]],
    db_session: Any,
    tool_names: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    执行一轮“模型决定是否调用工具”的循环。

    流程是：
    1. 把 messages + tools 发给模型；
    2. 如果模型返回 tool_calls，就交给 ToolExecutor 执行；
    3. 把工具结果追加回 messages；
    4. 再次调用模型，直到它不再请求工具。
    """
    from app.llm.tool_executor import ToolExecutor

    llm = get_llm_client()
    tools = get_tool_definitions(tool_names)
    executor = ToolExecutor(db_session)

    for iteration in range(MAX_TOOL_ITERATIONS):
        response = await llm.chat(
            messages=messages,
            model_type=ModelType.BRAIN,
            tools=tools,
            temperature=0.3,
        )

        tool_calls = response.get("tool_calls")
        if not tool_calls:
            # 没有 tool_calls，说明模型已经给出了最终文本结论。
            return response

        logger.info(
            f"Tool calling iteration {iteration + 1}: "
            f"{len(tool_calls)} tool(s) called"
        )

        # 先把“模型准备调用哪些工具”的 assistant 消息追加进去。
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.get("content") or "",
        }
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": tc["function"],
            }
            for tc in tool_calls
        ]
        messages.append(assistant_msg)

        # 再依次执行每个工具，并把结果作为 tool 消息回填。
        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}

            logger.info(f"Executing tool: {func_name}({json.dumps(func_args, ensure_ascii=False)[:200]})")
            result = await executor.execute(func_name, func_args)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
            )

    logger.warning(f"Tool calling loop exhausted after {MAX_TOOL_ITERATIONS} iterations")
    return response


async def act_node(state: AgentState) -> dict[str, Any]:
    """
    Actor 节点主逻辑：把执行数据变成可供 Reflector 分析的结果。

    如果状态里有数据库会话，就允许模型做工具调用；
    否则退化成基础日志解析。
    """
    logger.info(f"Actor node executing for run {state.get('run_id')}")

    logs = state.get("logs", [])
    parsed = _parse_log_data(logs)

    db_session = state.get("db_session")
    tool_analysis = None

    if db_session and state.get("user"):
        user = state["user"]
        plan = state.get("plan")

        system_msg = (
            "你是饮食健身 Agent 的执行分析模块。"
            "你可以调用工具读取数据、分析偏差并补充营养信息。"
            "请基于用户最近执行情况给出分析，如果需要就主动调用工具。"
        )

        user_msg = (
            f"用户 {user.get('name', '')} 的最新执行数据如下：\n"
            f"{json.dumps(parsed, ensure_ascii=False, indent=2)}\n\n"
        )
        if plan:
            user_msg += (
                f"当前计划日型：{plan.get('day_type', 'unknown')}，"
                f"目标热量：{plan.get('target_calories', 0)} kcal\n"
            )
        user_msg += "\n请分析执行情况，如有必要请调用工具获取更多信息。"

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        try:
            response = await _run_tool_calling_loop(messages, db_session)
            tool_analysis = response.get("content")
            logger.info("Actor tool calling analysis completed")
        except Exception as e:
            logger.warning(f"Tool calling analysis failed, using basic parsing: {e}")

    decision = "parse_execution"
    reasoning = f"解析了 {len(logs)} 条饮食日志" + (" + 工具增强分析" if tool_analysis else "")
    log_agent_decision(
        logger,
        node="actor",
        decision=decision,
        reasoning=reasoning,
        context={"meal_count": parsed.get("meal_count", 0)},
    )
    try:
        await get_agent_memory().record_decision(
            run_id=UUID(state["run_id"]),
            node="actor",
            decision=decision,
            reasoning=reasoning,
            input_summary=f"log_count={len(logs)}",
            output_summary=json.dumps(parsed, ensure_ascii=False)[:500],
            confidence=0.8 if tool_analysis else 0.75,
        )
    except Exception as exc:
        logger.warning(f"Failed to persist actor decision: {exc}")

    result = {"actor_output": parsed}
    if tool_analysis:
        result["actor_output"]["tool_analysis"] = tool_analysis

    return result
