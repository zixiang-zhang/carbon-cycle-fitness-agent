"""饮食计划相关接口：创建、查询、更新、删除、单日重生成。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.db.db_storage import DatabaseStorage
from app.models.plan import CarbonCyclePlan, DayPlan, PlanCreate, PlanSummary, PlanUpdate
from app.services.carbon_strategy import CarbonStrategyService
from app.services.plan_enrichment import PlanEnrichmentService

router = APIRouter()

strategy_service = CarbonStrategyService()


def _find_day_in_plan(plan: CarbonCyclePlan, day_date: str) -> tuple[int, DayPlan]:
    """根据日期字符串在计划中定位某一天，并返回下标与对象。"""
    for index, day in enumerate(plan.days):
        if str(day.date) == day_date:
            return index, day
    raise HTTPException(status_code=404, detail="Day not found in plan")


def _serialize_day(day: DayPlan) -> dict:
    """把单日计划转换成前端“单日重生成接口”需要的紧凑结构。"""
    return {
        "date": str(day.date),
        "day_type": day.day_type.value if hasattr(day.day_type, "value") else str(day.day_type),
        "target_calories": day.target_calories,
        "macros": {
            "protein_g": day.macros.protein_g,
            "carbs_g": day.macros.carbs_g,
            "fat_g": day.macros.fat_g,
            "fiber_g": day.macros.fiber_g,
        },
        "training_scheduled": day.training_scheduled,
        "training_type": day.training_type,
        "notes": day.notes,
    }


@router.post("/", response_model=CarbonCyclePlan, status_code=status.HTTP_201_CREATED)
async def create_plan(plan_data: PlanCreate, db: AsyncSession = Depends(get_db)) -> CarbonCyclePlan:
    """
    创建碳循环计划，并交给 Agent 做 AI 增强。

    这个接口本身只负责调度：
    1. 读取用户；
    2. 调用策略服务生成计划；
    3. 把生成结果持久化。
    """
    storage = DatabaseStorage(db)

    user = await storage.get_user(plan_data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_plan = await strategy_service.generate_plan_with_agent(user, plan_data)
    return await storage.add_plan(new_plan)


@router.get("/{plan_id}", response_model=CarbonCyclePlan)
async def get_plan(plan_id: str, db: AsyncSession = Depends(get_db)) -> CarbonCyclePlan:
    """按计划 ID 查询一条已持久化的计划。"""
    storage = DatabaseStorage(db)
    plan = await storage.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.patch("/{plan_id}", response_model=CarbonCyclePlan)
async def update_plan(
    plan_id: str,
    plan_update: PlanUpdate,
    db: AsyncSession = Depends(get_db),
) -> CarbonCyclePlan:
    """局部更新计划，支持直接替换 `days` 列表。"""
    storage = DatabaseStorage(db)
    updates = plan_update.model_dump(exclude_unset=True)

    updated_plan = await storage.update_plan(plan_id, **updates)
    if not updated_plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    return updated_plan


@router.get("/user/{user_id}", response_model=list[PlanSummary])
async def get_user_plans(user_id: str, db: AsyncSession = Depends(get_db)) -> list[PlanSummary]:
    """查询某个用户的全部计划，并返回前端列表页需要的摘要结构。"""
    storage = DatabaseStorage(db)
    if not await storage.get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")

    user_plans = await storage.get_user_plans(user_id)
    return [
        PlanSummary(
            id=plan.id,
            name=plan.name,
            start_date=plan.start_date,
            end_date=plan.end_date,
            is_active=plan.is_active,
            average_daily_calories=plan.average_daily_calories,
            day_type_counts={key.value: value for key, value in plan.count_day_types().items()},
        )
        for plan in user_plans
    ]


@router.get("/user/{user_id}/active", response_model=CarbonCyclePlan)
async def get_active_plan(user_id: str, db: AsyncSession = Depends(get_db)) -> CarbonCyclePlan:
    """获取用户当前生效中的计划。"""
    storage = DatabaseStorage(db)
    plan = await storage.get_active_plan(user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No active plan found")
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(plan_id: str, db: AsyncSession = Depends(get_db)) -> None:
    """删除一条已保存的计划。"""
    storage = DatabaseStorage(db)
    if not await storage.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail="Plan not found")


@router.patch("/{plan_id}/deactivate", response_model=CarbonCyclePlan)
async def deactivate_plan(plan_id: str, db: AsyncSession = Depends(get_db)) -> CarbonCyclePlan:
    """把计划真正持久化地标记为 inactive。"""
    storage = DatabaseStorage(db)
    updated_plan = await storage.update_plan(plan_id, is_active=False)
    if not updated_plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return updated_plan


@router.post("/{plan_id}/days/{day_date}/regenerate")
async def regenerate_day(
    plan_id: str,
    day_date: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    只重生成某一天的 LLM 文本增强内容。

    这里不会重新计算热量和宏量营养，
    只会刷新这一天展示给用户看的训练安排和饮食建议文本。
    """
    storage = DatabaseStorage(db)
    plan = await storage.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    user = await storage.get_user(str(plan.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    target_index, target_day = _find_day_in_plan(plan, day_date)

    enrichment_service = PlanEnrichmentService()
    await enrichment_service.enrich_day(target_day, user)

    # DayPlan 是列表里的嵌套对象，更新后需要把整个 days 列表重新回写数据库。
    plan.days[target_index] = target_day
    await storage.update_plan(plan_id, days=plan.days)

    return _serialize_day(target_day)
