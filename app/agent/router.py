"""
Agent 状态图中的条件路由逻辑。

这个文件只做一件事：根据当前状态，决定 LangGraph 下一步该走哪个节点。
"""

from typing import Literal

from app.agent.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)


def should_continue_to_reflect(state: AgentState) -> Literal["reflect", "end"]:
    """
    判断 Actor 节点之后是否需要进入 Reflector。

    只要发生错误，或者根本没有可分析的执行数据，就直接结束。
    """
    if state.get("error"):
        logger.info("Routing to end due to error")
        return "end"

    actor_output = state.get("actor_output") or {}
    if actor_output.get("status") == "no_data":
        logger.info("Routing to end due to no data")
        return "end"

    return "reflect"


def should_adjust(state: AgentState) -> Literal["adjust", "end"]:
    """
    判断 Reflector 之后是否需要进入 Adjuster。

    Reflector 会把是否需要调整写回 `should_adjust`，
    这里的职责只是读取这个标志并做路由。
    """
    if state.get("error"):
        return "end"

    if state.get("should_adjust", False):
        logger.info("Routing to adjust based on reflection")
        return "adjust"

    logger.info("No adjustment needed, routing to end")
    return "end"


def check_iteration_limit(state: AgentState) -> Literal["continue", "end"]:
    """检查是否超过最大迭代次数。"""
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 10)

    if iteration >= max_iter:
        logger.warning(f"Max iterations ({max_iter}) reached")
        return "end"

    return "continue"


def should_skip_after_planner(state: AgentState) -> Literal["skip", "continue"]:
    """
    判断 Planner 之后是否可以直接结束。

    对于 `create_plan`、`plan_only`、`generate_plan` 这类触发词，
    我们只需要 Planner 产出的规划建议，不需要再去分析执行日志。
    """
    trigger = state.get("trigger", "")

    # 计划生成类触发只需要 Planner 节点，
    # 后面的 Actor / Reflector / Adjuster 留给“执行分析与动态调整”场景。
    planner_only_triggers = {"create_plan", "plan_only", "generate_plan"}

    if trigger in planner_only_triggers:
        logger.info(f"Skipping to end for trigger: {trigger}")
        return "skip"

    return "continue"
