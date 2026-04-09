"""
Weekly report repository.
"""

from datetime import date
from typing import Optional, Union
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WeeklyReportModel
from app.models.report import DailyStats, WeeklyReport


class ReportRepository:
    """Repository for weekly report persistence."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, report: WeeklyReport) -> WeeklyReport:
        """Create a weekly report."""
        db_report = WeeklyReportModel(
            id=str(report.id),
            user_id=str(report.user_id),
            plan_id=str(report.plan_id) if report.plan_id else None,
            week_start=report.week_start,
            week_end=report.week_end,
            daily_stats=[stat.model_dump(mode="json") for stat in report.daily_stats],
            average_calories=report.average_calories,
            average_protein=report.average_protein,
            average_carbs=report.average_carbs,
            average_fat=report.average_fat,
            total_training_sessions=report.total_training_sessions,
            planned_training_sessions=report.planned_training_sessions,
            training_adherence=report.training_adherence,
            diet_adherence=report.diet_adherence,
            weight_start_kg=report.weight_start_kg,
            weight_end_kg=report.weight_end_kg,
            summary=report.summary,
            recommendations=report.recommendations,
        )
        self.session.add(db_report)
        await self.session.flush()
        return report

    async def get_by_id(self, report_id: Union[UUID, str]) -> Optional[WeeklyReport]:
        """Get a weekly report by id."""
        result = await self.session.execute(
            select(WeeklyReportModel).where(WeeklyReportModel.id == str(report_id))
        )
        db_report = result.scalar_one_or_none()
        return self._to_pydantic(db_report) if db_report else None

    async def get_user_reports(self, user_id: Union[UUID, str]) -> list[WeeklyReport]:
        """List weekly reports for a user."""
        result = await self.session.execute(
            select(WeeklyReportModel)
            .where(WeeklyReportModel.user_id == str(user_id))
            .order_by(WeeklyReportModel.week_start.desc(), WeeklyReportModel.created_at.desc())
        )
        return [self._to_pydantic(report) for report in result.scalars().all()]

    async def get_by_week(
        self,
        user_id: Union[UUID, str],
        week_start: date,
        week_end: date,
    ) -> Optional[WeeklyReport]:
        """Get a report for a specific week."""
        result = await self.session.execute(
            select(WeeklyReportModel).where(
                WeeklyReportModel.user_id == str(user_id),
                WeeklyReportModel.week_start == week_start,
                WeeklyReportModel.week_end == week_end,
            )
        )
        db_report = result.scalar_one_or_none()
        return self._to_pydantic(db_report) if db_report else None

    async def upsert(self, report: WeeklyReport) -> WeeklyReport:
        """Create or update a report for the same user and week."""
        existing = await self.get_by_week(report.user_id, report.week_start, report.week_end)
        if not existing:
            return await self.create(report)
        await self.update(existing.id, report)
        return report

    async def update(
        self,
        report_id: Union[UUID, str],
        report: WeeklyReport,
    ) -> Optional[WeeklyReport]:
        """Replace a report payload."""
        result = await self.session.execute(
            select(WeeklyReportModel).where(WeeklyReportModel.id == str(report_id))
        )
        db_report = result.scalar_one_or_none()
        if not db_report:
            return None

        db_report.plan_id = str(report.plan_id) if report.plan_id else None
        db_report.week_start = report.week_start
        db_report.week_end = report.week_end
        db_report.daily_stats = [stat.model_dump(mode="json") for stat in report.daily_stats]
        db_report.average_calories = report.average_calories
        db_report.average_protein = report.average_protein
        db_report.average_carbs = report.average_carbs
        db_report.average_fat = report.average_fat
        db_report.total_training_sessions = report.total_training_sessions
        db_report.planned_training_sessions = report.planned_training_sessions
        db_report.training_adherence = report.training_adherence
        db_report.diet_adherence = report.diet_adherence
        db_report.weight_start_kg = report.weight_start_kg
        db_report.weight_end_kg = report.weight_end_kg
        db_report.summary = report.summary
        db_report.recommendations = report.recommendations

        await self.session.flush()
        return self._to_pydantic(db_report)

    def _to_pydantic(self, db_report: WeeklyReportModel) -> WeeklyReport:
        """Convert ORM model to Pydantic model."""
        daily_stats = [
            DailyStats.model_validate(item)
            for item in (db_report.daily_stats or [])
        ]
        return WeeklyReport(
            id=db_report.id,
            user_id=db_report.user_id,
            plan_id=db_report.plan_id,
            week_start=db_report.week_start,
            week_end=db_report.week_end,
            daily_stats=daily_stats,
            average_calories=db_report.average_calories,
            average_protein=db_report.average_protein,
            average_carbs=db_report.average_carbs,
            average_fat=db_report.average_fat,
            total_training_sessions=db_report.total_training_sessions,
            planned_training_sessions=db_report.planned_training_sessions,
            training_adherence=db_report.training_adherence,
            diet_adherence=db_report.diet_adherence,
            weight_start_kg=db_report.weight_start_kg,
            weight_end_kg=db_report.weight_end_kg,
            summary=db_report.summary,
            recommendations=list(db_report.recommendations or []),
            created_at=db_report.created_at,
        )
