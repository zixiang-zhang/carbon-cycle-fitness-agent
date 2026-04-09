"""
AgentState 及其子结构定义。

你可以把这个文件理解成：
“LangGraph 在各个节点之间传递的那份共享状态，到底长什么样。”
"""

from typing import Any, Optional, TypedDict


class UserContext(TypedDict):
    """Agent 节点共享的用户画像。"""

    user_id: str
    name: str
    gender: str
    age: int
    height_cm: float
    goal: str
    weight_kg: float
    target_weight_kg: float | None
    activity_level: str
    training_days: int
    dietary_preferences: str
    tdee: float


class PlanContext(TypedDict):
    """Agent 节点共享的当前计划快照。"""

    plan_id: str
    start_date: str
    current_day: int
    day_type: str
    target_calories: float
    target_protein: float
    target_carbs: float
    target_fat: float
    cycle_length: int
    num_cycles: int
    base_calories: float
    day_count: int


class LogContext(TypedDict):
    """Agent 节点读取的执行日志摘要。"""

    date: str
    actual_calories: float
    actual_protein: float
    actual_carbs: float
    actual_fat: float
    target_calories: float
    target_protein: float
    target_carbs: float
    target_fat: float
    training_completed: bool
    meal_count: int


class ReflectionResult(TypedDict):
    """Reflector 节点输出的偏差分析结果。"""

    severity: str
    deviation_type: str
    calorie_deviation_pct: float
    protein_deviation_pct: float
    needs_adjustment: bool
    patterns: list[str]


class AdjustmentResult(TypedDict):
    """Adjuster 节点输出的调整建议。"""

    adjustment_type: str
    calorie_adjustment: float
    immediate_actions: list[dict]
    behavioral_suggestions: list[dict]


class AgentState(TypedDict, total=False):
    """
    LangGraph 在节点之间流转的完整共享状态。

    可以把它按 4 个区块理解：
    1. 运行元信息：run_id / trigger
    2. 业务上下文：user / plan / logs
    3. 节点产出：planner_output / actor_output / reflection / adjustment
    4. 控制字段：error / should_adjust / iteration / messages
    """

    # 运行元信息：标识这次 Agent 运行是谁触发的、为什么触发。
    run_id: str
    trigger: str

    # 业务上下文：这是 Planner / Actor / Reflector / Adjuster 的共同输入。
    user: UserContext
    plan: PlanContext
    logs: list[LogContext]
    current_date: str

    # 节点产出：每个节点把自己的结果写回状态，后续节点继续读取。
    planner_output: Optional[dict[str, Any]]
    actor_output: Optional[dict[str, Any]]
    reflection: Optional[ReflectionResult]
    adjustment: Optional[AdjustmentResult]

    # 控制流字段：用于路由、异常控制和最终输出。
    final_output: Optional[dict[str, Any]]
    error: Optional[str]
    should_adjust: bool
    iteration: int
    max_iterations: int

    # 有些节点会走对话式 LLM 调用，因此把消息历史也放进共享状态。
    messages: list[dict[str, str]]

    # 如果某个节点需要执行工具调用，可以把数据库会话塞进状态里使用。
    db_session: Optional[Any]
