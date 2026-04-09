"""
LangGraph 状态图定义。

这份图就是整个 Agent 工作流的“骨架”：
Planner -> Actor -> Reflector -> Adjuster
"""

from typing import Any, Optional
from uuid import UUID, uuid4

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes import act_node, adjust_node, plan_node, reflect_node
from app.agent.router import should_adjust, should_continue_to_reflect, should_skip_after_planner
from app.agent.state import AgentState, LogContext, PlanContext, UserContext
from app.core.logging import agent_run_id_var, get_logger
from app.memory.agent_memory import get_agent_memory

logger = get_logger(__name__)


def create_agent_graph() -> CompiledStateGraph:
    """
    创建并编译 LangGraph 状态图。

    这张图的主链路是线性的，但通过条件边来决定是否提前结束：
    - create_plan 场景：Planner 后直接结束
    - 执行分析场景：Planner -> Actor -> Reflector
    - 需要调整时：Reflector -> Adjuster
    """
    graph = StateGraph(AgentState)

    # 1. 注册节点：每个节点本质上都是一个“读状态 -> 写状态”的异步函数。
    graph.add_node("planner", plan_node)
    graph.add_node("actor", act_node)
    graph.add_node("reflector", reflect_node)
    graph.add_node("adjuster", adjust_node)

    # 2. 指定入口节点：所有运行都先从 Planner 开始。
    graph.set_entry_point("planner")

    # 3. Planner 之后根据 trigger 决定：
    #    是直接结束，还是进入 Actor 继续分析执行情况。
    graph.add_conditional_edges(
        "planner",
        should_skip_after_planner,
        {
            "skip": END,
            "continue": "actor",
        },
    )

    # 4. Actor 之后如果没有日志或出现错误，就可以直接结束。
    graph.add_conditional_edges(
        "actor",
        should_continue_to_reflect,
        {
            "reflect": "reflector",
            "end": END,
        },
    )

    # 5. Reflector 根据偏差严重程度决定是否进入 Adjuster。
    graph.add_conditional_edges(
        "reflector",
        should_adjust,
        {
            "adjust": "adjuster",
            "end": END,
        },
    )

    # 6. Adjuster 是最后一个节点，执行完就结束。
    graph.add_edge("adjuster", END)

    return graph.compile()


# 单例图对象：避免每次请求都重新构图。
_agent_graph: Optional[CompiledStateGraph] = None


def get_agent_graph() -> CompiledStateGraph:
    """获取全局唯一的 Agent 图对象；如果不存在就先创建。"""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = create_agent_graph()
    return _agent_graph


async def run_agent(
    user_id: str,
    trigger: str,
    user_context: dict[str, Any],
    plan_context: dict[str, Any],
    logs: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    执行一次完整的 Agent 运行。

    外部调用方只需要传入松散的 dict 数据；
    这里会先把它们标准化成 AgentState 需要的结构，再交给 LangGraph。
    """
    import time

    start_time = time.time()

    run_id = str(uuid4())
    run_uuid = UUID(run_id)
    logger.info(f"Starting agent run {run_id} for user {user_id}")
    agent_run_token = agent_run_id_var.set(run_id)

    # 先在入口统一做一次“字段标准化”，后面的所有节点都读同一份格式，
    # 这样不会出现某个节点拿不到 age / gender / cycle_length 之类字段的问题。
    typed_user_context: UserContext = {
        "user_id": str(user_context.get("user_id", "")),
        "name": str(user_context.get("name", "User")),
        "gender": str(user_context.get("gender", "unknown")),
        "age": int(user_context.get("age", 30)),
        "height_cm": float(user_context.get("height_cm", 170)),
        "goal": str(user_context.get("goal", "maintain")),
        "weight_kg": float(user_context.get("weight_kg", 70)),
        "target_weight_kg": (
            float(user_context["target_weight_kg"])
            if user_context.get("target_weight_kg") is not None
            else None
        ),
        "activity_level": str(user_context.get("activity_level", "moderate")),
        "training_days": int(user_context.get("training_days", 4)),
        "dietary_preferences": str(user_context.get("dietary_preferences", "none")),
        "tdee": float(user_context.get("tdee", 2000)),
    }

    typed_plan_context: PlanContext = {
        "plan_id": str(plan_context.get("plan_id", "")),
        "start_date": str(plan_context.get("start_date", "")),
        "current_day": int(plan_context.get("current_day", 1)),
        "day_type": str(plan_context.get("day_type", "medium_carb")),
        "target_calories": float(plan_context.get("target_calories", 2000)),
        "target_protein": float(plan_context.get("target_protein", 150)),
        "target_carbs": float(plan_context.get("target_carbs", 200)),
        "target_fat": float(plan_context.get("target_fat", 60)),
        "cycle_length": int(plan_context.get("cycle_length", 7)),
        "num_cycles": int(plan_context.get("num_cycles", 1)),
        "base_calories": float(plan_context.get("base_calories", plan_context.get("target_calories", 2000))),
        "day_count": int(plan_context.get("day_count", 0)),
    }

    typed_logs: list[LogContext] = [
        {
            "date": str(log.get("date", "")),
            "actual_calories": float(log.get("actual_calories", 0)),
            "actual_protein": float(log.get("actual_protein", 0)),
            "actual_carbs": float(log.get("actual_carbs", 0)),
            "actual_fat": float(log.get("actual_fat", 0)),
            "target_calories": float(log.get("target_calories", 0)),
            "target_protein": float(log.get("target_protein", 0)),
            "target_carbs": float(log.get("target_carbs", 0)),
            "target_fat": float(log.get("target_fat", 0)),
            "training_completed": bool(log.get("training_completed", False)),
            "meal_count": int(log.get("meal_count", 0)),
        }
        for log in logs
    ]

    # 这是第一次真正构造 AgentState，也就是整张图的初始状态。
    initial_state: AgentState = {
        "run_id": run_id,
        "trigger": trigger,
        "user": typed_user_context,
        "plan": typed_plan_context,
        "logs": typed_logs,
        "current_date": "",
        "planner_output": None,
        "actor_output": None,
        "reflection": None,
        "adjustment": None,
        "final_output": None,
        "error": None,
        "should_adjust": False,
        "iteration": 0,
        "max_iterations": 10,
        "messages": [],
    }

    graph = get_agent_graph()
    agent_memory = get_agent_memory()
    await agent_memory.start_run(
        user_id=UUID(str(user_id)),
        trigger=trigger,
        run_id=run_uuid,
    )

    try:
        result = await graph.ainvoke(initial_state)

        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Agent run {run_id} completed successfully in {latency_ms}ms")

        response = {
            "run_id": run_id,
            "status": "success",
            "latency_ms": latency_ms,
            "planner_output": result.get("planner_output"),
            "reflection": result.get("reflection"),
            "adjustment": result.get("adjustment"),
            "reflection_summary": result.get("reflection_summary"),
            "trends": result.get("trends"),
        }
        await agent_memory.complete_run(run_uuid, response)
        return response

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Agent run {run_id} failed in {latency_ms}ms: {e}")
        await agent_memory.fail_run(run_uuid, str(e))
        return {
            "run_id": run_id,
            "status": "error",
            "latency_ms": latency_ms,
            "error": str(e),
        }
    finally:
        # 这里把日志上下文里的 run_id 恢复掉，避免串到后续请求。
        agent_run_id_var.reset(agent_run_token)
