"""
把数据库里的领域对象，转换成 Agent 运行时使用的上下文结构。

这个模块的意义在于把两件事拆开：
1. API 层负责“取数据”；
2. context builder 负责“把数据整理成 LangGraph 需要的形状”。

这样入口代码会更清晰，也更适合面试时解释调用链。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional


def build_user_context(user: Any) -> dict[str, Any]:
    """把用户对象压缩成 Agent 需要的用户画像信息。"""
    return {
        "user_id": str(user.id),
        "name": user.name,
        "gender": user.gender.value if hasattr(user.gender, "value") else user.gender,
        "age": user.calculate_age() if hasattr(user, "calculate_age") else 30,
        "height_cm": user.height_cm,
        "weight_kg": user.weight_kg,
        "target_weight_kg": getattr(user, "target_weight_kg", None) or user.weight_kg,
        "goal": user.goal.value if hasattr(user.goal, "value") else user.goal,
        "activity_level": user.activity_level.value if hasattr(user.activity_level, "value") else user.activity_level,
        "training_days": getattr(user, "training_days_per_week", 4),
        "tdee": user.calculate_tdee() if hasattr(user, "calculate_tdee") else 2000,
        "dietary_preferences": ", ".join(getattr(user, "dietary_preferences", [])) or "none",
    }


def build_active_plan_context(plan: Any, reference_date: Optional[date] = None) -> dict[str, Any]:
    """
    构建“当前计划快照”。

    Agent 大多数时候关注的是“今天该怎么做”，
    所以这里会优先从计划里找到 reference_date 对应的那一天，
    并把今天的目标热量、宏量营养和训练安排提取出来。
    """
    if not plan:
        return {}

    target_date = reference_date or date.today()
    today_day = next((day for day in plan.days if day.date == target_date), None)

    if today_day:
        return {
            "plan_id": str(plan.id),
            "start_date": plan.start_date.isoformat(),
            "current_day": (target_date - plan.start_date).days + 1,
            "day_type": today_day.day_type.value if hasattr(today_day.day_type, "value") else today_day.day_type,
            "target_calories": today_day.target_calories,
            "target_protein": today_day.macros.protein_g,
            "target_carbs": today_day.macros.carbs_g,
            "target_fat": today_day.macros.fat_g,
            "cycle_length": len(plan.days),
        }

    # 如果当前日期不在计划内，就退化成整个计划的概览信息。
    return {
        "plan_id": str(plan.id),
        "start_date": plan.start_date.isoformat(),
        "target_calories": plan.average_daily_calories,
        "cycle_length": len(plan.days),
    }


def build_plan_targets(
    plan: Any,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[date, dict[str, float]]:
    """
    按日期建立“计划目标索引”。

    这个索引主要给 Reflector / 周报链路用，
    因为它们需要在同一条日志里同时看到 actual 和 target。
    """
    if not plan:
        return {}

    targets: dict[date, dict[str, float]] = {}
    for day in getattr(plan, "days", []):
        if start_date and day.date < start_date:
            continue
        if end_date and day.date > end_date:
            continue
        targets[day.date] = {
            "target_calories": day.target_calories,
            "target_protein": day.macros.protein_g,
            "target_carbs": day.macros.carbs_g,
            "target_fat": day.macros.fat_g,
        }
    return targets


def build_logs_context(
    logs: list[Any],
    targets_by_date: Optional[dict[date, dict[str, float]]] = None,
) -> list[dict[str, Any]]:
    """
    把数据库里的 DietLog 压平成 Agent 状态里使用的日志结构。

    AgentState 并不需要完整日志对象，只关心：
    - 日期
    - 实际摄入
    - 目标摄入
    - 是否完成训练
    - 当天记录了多少餐
    """
    payload: list[dict[str, Any]] = []
    for log in logs:
        targets = (targets_by_date or {}).get(log.date, {})
        payload.append(
            {
                "date": log.date.isoformat(),
                "actual_calories": log.total_calories or 0,
                "actual_protein": log.total_protein or 0,
                "actual_carbs": log.total_carbs or 0,
                "actual_fat": log.total_fat or 0,
                "target_calories": targets.get("target_calories", 0),
                "target_protein": targets.get("target_protein", 0),
                "target_carbs": targets.get("target_carbs", 0),
                "target_fat": targets.get("target_fat", 0),
                "training_completed": log.training_completed or False,
                "meal_count": len(log.meals) if log.meals else 0,
            }
        )
    return payload
