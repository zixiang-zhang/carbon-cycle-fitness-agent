"""周报相关接口：生成周报、查询周报历史、读取体重趋势。"""

from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import run_agent
from app.agent.context import build_logs_context, build_plan_targets, build_user_context
from app.core.database import get_db
from app.core.logging import get_logger
from app.db.db_storage import DatabaseStorage
from app.models.report import DailyStats, WeeklyReport
from app.services.execution_analysis import ExecutionAnalysisService
from app.services.report_service import ReportService

logger = get_logger(__name__)
router = APIRouter()


class WeeklyStats(BaseModel):
    """前端传入的周统计快照。"""

    calorieTarget: float
    calorieActual: float
    calorieRate: float
    trainingCompleted: int
    trainingTotal: int
    trainingRate: float
    avgProtein: float
    avgCarbs: float
    avgFat: float
    weightStart: Optional[float] = None
    weightEnd: Optional[float] = None
    weightChange: Optional[float] = None


class WeeklyReportRequest(BaseModel):
    """生成周报时的请求体。"""

    user_id: str
    stats: Optional[WeeklyStats] = None
    plan_id: Optional[str] = None
    week_start: Optional[date] = None


class WeeklyReportResponse(BaseModel):
    """生成周报后的响应结构。"""

    report_id: str
    report: str
    generated_at: str
    agent_used: bool = False
    latency_ms: Optional[int] = None


class ReportSummaryResponse(BaseModel):
    """周报列表页使用的摘要结构。"""

    id: str
    week_start: str
    week_end: str
    overall_adherence: float
    weight_change: Optional[float] = None
    trend: str
    created_at: str


class ReportDetailResponse(BaseModel):
    """周报详情页使用的详细结构。"""

    id: str
    user_id: str
    week_start: str
    week_end: str
    calorie_rate: float
    training_rate: float
    weight_change: Optional[float] = None
    avg_protein: float
    avg_carbs: float
    avg_fat: float
    summary: Optional[str] = None
    recommendations: list[str] = []
    created_at: str


def _week_bounds(anchor: Optional[date] = None) -> tuple[date, date]:
    """根据任意一天，计算它所在周的周一和周日。"""
    anchor = anchor or date.today()
    week_start = anchor - timedelta(days=anchor.weekday())
    return week_start, week_start + timedelta(days=6)


def _report_to_markdown(report: WeeklyReport) -> str:
    """把数据库中的周报对象渲染成前端直接展示的 Markdown。"""
    lines = [
        "## AI Weekly Report",
        "",
        f"- Diet adherence: **{report.diet_adherence:.1f}%**",
        f"- Training adherence: **{report.training_adherence:.1f}%**",
    ]

    if report.weight_change_kg is not None:
        lines.append(f"- Weight change: **{report.weight_change_kg:+.1f} kg**")

    if report.summary:
        lines.extend(["", "### Summary", report.summary])

    if report.recommendations:
        lines.extend(["", "### Recommendations"])
        lines.extend([f"{index}. {item}" for index, item in enumerate(report.recommendations, start=1)])

    return "\n".join(lines)


def _report_to_summary(report: WeeklyReport) -> ReportSummaryResponse:
    """把周报对象转换成前端列表页需要的摘要结构。"""
    return ReportSummaryResponse(
        id=str(report.id),
        week_start=report.week_start.isoformat(),
        week_end=report.week_end.isoformat(),
        overall_adherence=report.overall_adherence,
        weight_change=report.weight_change_kg,
        trend=report.get_trend(),
        created_at=report.created_at.isoformat(),
    )


def _report_to_detail(report: WeeklyReport) -> ReportDetailResponse:
    """把周报对象转换成前端详情页需要的结构。"""
    calorie_rate = report.diet_adherence
    if report.daily_stats:
        valid_days = [day for day in report.daily_stats if day.target_calories > 0]
        if valid_days:
            calorie_rate = round(
                sum((day.actual_calories / day.target_calories) * 100 for day in valid_days) / len(valid_days),
                1,
            )

    return ReportDetailResponse(
        id=str(report.id),
        user_id=str(report.user_id),
        week_start=report.week_start.isoformat(),
        week_end=report.week_end.isoformat(),
        calorie_rate=calorie_rate,
        training_rate=report.training_adherence,
        weight_change=report.weight_change_kg,
        avg_protein=report.average_protein,
        avg_carbs=report.average_carbs,
        avg_fat=report.average_fat,
        summary=report.summary,
        recommendations=report.recommendations,
        created_at=report.created_at.isoformat(),
    )


async def _generate_agent_insights(
    storage: DatabaseStorage,
    request: WeeklyReportRequest,
    week_start: date,
    week_end: date,
) -> tuple[Optional[str], list[str], Optional[int], bool]:
    """
    调用 LangGraph 生成周报摘要和调整建议。

    周报不是只看静态统计值，而是把“用户画像 + 计划目标 + 一周执行日志”
    重新送进 Agent，让 Reflector / Adjuster 再走一遍分析链路。
    """
    user = await storage.get_user(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan = await storage.get_active_plan(request.user_id)
    logs = await storage.get_user_logs(request.user_id, limit=14)
    week_logs = [log for log in logs if week_start <= log.date <= week_end]

    # 这里要把每天日志补齐“计划目标值”，这样 Reflector 才能在同一个 payload
    # 里同时读到 actual 和 target，做偏差分析会更稳定。
    targets_by_date = build_plan_targets(plan, week_start, week_end)

    result = await run_agent(
        user_id=request.user_id,
        trigger=f"weekly_report:{week_start.isoformat()}",
        user_context=build_user_context(user),
        plan_context={
            "plan_id": str(plan.id) if plan else request.plan_id,
            "start_date": week_start.isoformat(),
            "target_calories": request.stats.calorieTarget if request.stats else 0,
            "target_protein": request.stats.avgProtein if request.stats else 0,
            "target_carbs": request.stats.avgCarbs if request.stats else 0,
            "target_fat": request.stats.avgFat if request.stats else 0,
        },
        logs=build_logs_context(week_logs, targets_by_date),
    )

    if result.get("status") != "success":
        logger.warning("Weekly report agent run failed: %s", result.get("error"))
        return None, [], result.get("latency_ms"), False

    recommendations: list[str] = []
    adjustment = result.get("adjustment") or {}
    for action in adjustment.get("immediate_actions", []):
        if isinstance(action, dict) and action.get("action"):
            recommendations.append(str(action["action"]))
    for suggestion in adjustment.get("behavioral_suggestions", []):
        if isinstance(suggestion, dict) and suggestion.get("suggestion"):
            recommendations.append(str(suggestion["suggestion"]))

    # 去重是因为规则建议和 LLM 建议可能会表达同一件事。
    unique_recommendations: list[str] = []
    seen: set[str] = set()
    for item in recommendations:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_recommendations.append(normalized)

    return result.get("reflection_summary"), unique_recommendations[:5], result.get("latency_ms"), True


def _build_report_from_request(
    request: WeeklyReportRequest,
    week_start: date,
    week_end: date,
) -> WeeklyReport:
    """
    当数据库里缺少完整执行数据时，用前端上传的统计值兜底生成周报。

    这个兜底分支保证页面不会因为日志不足而完全不可用。
    """
    if request.stats is None:
        raise HTTPException(status_code=400, detail="stats is required when no stored execution data is available")

    stats = request.stats
    daily_stats = [
        DailyStats(
            date=week_start + timedelta(days=offset),
            target_calories=stats.calorieTarget,
            actual_calories=stats.calorieActual,
            target_protein=stats.avgProtein,
            actual_protein=stats.avgProtein,
            target_carbs=stats.avgCarbs,
            actual_carbs=stats.avgCarbs,
            target_fat=stats.avgFat,
            actual_fat=stats.avgFat,
            training_planned=stats.trainingTotal > 0,
            training_completed=offset < stats.trainingCompleted,
            adherence_score=stats.calorieRate,
        )
        for offset in range(7)
    ]

    return WeeklyReport(
        user_id=request.user_id,
        plan_id=request.plan_id,
        week_start=week_start,
        week_end=week_end,
        daily_stats=daily_stats,
        average_calories=stats.calorieActual,
        average_protein=stats.avgProtein,
        average_carbs=stats.avgCarbs,
        average_fat=stats.avgFat,
        total_training_sessions=stats.trainingCompleted,
        planned_training_sessions=stats.trainingTotal,
        training_adherence=stats.trainingRate,
        diet_adherence=stats.calorieRate,
        weight_start_kg=stats.weightStart,
        weight_end_kg=stats.weightEnd,
    )


async def _build_persisted_report(
    storage: DatabaseStorage,
    request: WeeklyReportRequest,
    week_start: date,
    week_end: date,
) -> WeeklyReport:
    """
    优先基于数据库里的真实计划、饮食日志、体重记录生成周报。

    这是最理想的分支，因为它走的是“计划 -> 执行分析 -> 周报汇总”的完整业务链路。
    """
    plan = await storage.get_active_plan(request.user_id)
    logs = await storage.get_user_logs(request.user_id, limit=30)
    weights = await storage.get_weight_by_date_range(request.user_id, week_start, week_end)

    week_logs = [log for log in logs if week_start <= log.date <= week_end]

    if plan and week_logs:
        analysis_service = ExecutionAnalysisService()
        report_service = ReportService()
        plan_days = [day for day in plan.days if week_start <= day.date <= week_end]
        plan_by_date = {day.date: day for day in plan_days}
        analyses = [
            analysis_service.analyze_day(plan_by_date[log.date], log)
            for log in week_logs
            if log.date in plan_by_date
        ]

        if analyses:
            weight_start = weights[0].weight_kg if weights else None
            weight_end = weights[-1].weight_kg if weights else None
            return report_service.generate_weekly_report(
                user_id=request.user_id,
                plan=plan,
                analyses=analyses,
                week_start=week_start,
                weight_start=weight_start,
                weight_end=weight_end,
            )

    return _build_report_from_request(request, week_start, week_end)


@router.post("/weekly", response_model=WeeklyReportResponse)
async def generate_weekly_report(
    request: WeeklyReportRequest,
    db: AsyncSession = Depends(get_db),
) -> WeeklyReportResponse:
    """生成周报、落库，并返回前端可直接展示的结果。"""
    storage = DatabaseStorage(db)
    week_start, week_end = _week_bounds(request.week_start)

    report = await _build_persisted_report(storage, request, week_start, week_end)
    summary, recommendations, latency_ms, agent_used = await _generate_agent_insights(
        storage,
        request,
        week_start,
        week_end,
    )

    if summary:
        report.summary = summary
    if recommendations:
        report.recommendations = recommendations

    persisted = await storage.upsert_weekly_report(report)
    return WeeklyReportResponse(
        report_id=str(persisted.id),
        report=_report_to_markdown(persisted),
        generated_at=persisted.created_at.date().isoformat(),
        agent_used=agent_used,
        latency_ms=latency_ms,
    )


@router.get("/user/{user_id}", response_model=list[ReportSummaryResponse])
async def list_user_reports(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ReportSummaryResponse]:
    """查询用户历史周报列表。"""
    storage = DatabaseStorage(db)
    if not await storage.get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")

    reports = await storage.get_user_weekly_reports(user_id)
    return [_report_to_summary(report) for report in reports]


@router.get("/user/{user_id}/weights")
async def get_user_weight_history(
    user_id: str,
    start: Optional[date] = Query(default=None),
    end: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """返回体重历史，用于前端趋势图。"""
    storage = DatabaseStorage(db)
    if not await storage.get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")

    if start and end:
        weights = await storage.get_weight_by_date_range(user_id, start, end)
    else:
        weights = await storage.get_user_weight_logs(user_id, limit=90)
        weights = list(reversed(weights))

    return [{"date": weight.date.isoformat(), "value": weight.weight_kg} for weight in weights]


@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report_by_id(
    report_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReportDetailResponse:
    """按周报 ID 查询详情。"""
    storage = DatabaseStorage(db)
    report = await storage.get_weekly_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_to_detail(report)
