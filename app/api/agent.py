"""
Agent 相关接口。

这里暴露了两种运行 LangGraph 工作流的方式：
1. `/run`：同步执行，适合调试、排查或直接查看一次完整结果。
2. `/trigger` + `/status/{run_id}`：异步触发 + 轮询结果，适合前端页面调用。
"""

from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import run_agent
from app.agent.context import build_active_plan_context, build_logs_context, build_user_context
from app.core.database import get_db, get_session_factory
from app.core.logging import get_logger
from app.db.db_storage import DatabaseStorage

logger = get_logger(__name__)
router = APIRouter()


class AgentTriggerRequest(BaseModel):
    """手动触发 Agent 时使用的请求体。"""

    user_id: str
    trigger: str = "manual"


class AgentRunResponse(BaseModel):
    """异步提交 Agent 任务后立即返回的最小响应。"""

    run_id: str
    status: str
    message: str


class AgentResultResponse(BaseModel):
    """同步接口和异步轮询接口共用的结果结构。"""

    run_id: str
    status: str
    planner_output: Optional[dict[str, Any]] = None
    reflection: Optional[dict[str, Any]] = None
    adjustment: Optional[dict[str, Any]] = None
    reflection_summary: Optional[str] = None
    motivation: Optional[str] = None
    error: Optional[str] = None


# 这个缓存故意做得很轻，只用于保存“接口触发的异步运行结果”。
# 它不是长期持久化存储，真正的运行审计由 AgentMemory 负责。
_agent_results: dict[str, dict[str, Any]] = {}


async def _run_agent_for_user(user_id: str, trigger: str, storage: DatabaseStorage) -> dict[str, Any]:
    """
    读取用户运行 Agent 所需的数据，并执行 LangGraph 工作流。

    这里故意把流程收敛成一个帮助函数，方便理解接口主链路：
    取用户 -> 取当前计划/最近日志 -> 组装 Agent 上下文 -> 运行图。
    """
    user = await storage.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan = await storage.get_active_plan(user_id)
    logs = await storage.get_user_logs(user_id, limit=7)

    return await run_agent(
        user_id=user_id,
        trigger=trigger,
        user_context=build_user_context(user),
        plan_context=build_active_plan_context(plan),
        logs=build_logs_context(logs),
    )


@router.post("/run", response_model=AgentResultResponse)
async def run_agent_sync(
    request: AgentTriggerRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentResultResponse:
    """同步运行 Agent，并在一个响应里直接返回完整结果。"""
    result = await _run_agent_for_user(request.user_id, request.trigger, DatabaseStorage(db))
    return AgentResultResponse(
        run_id=result.get("run_id", ""),
        status=result.get("status", "unknown"),
        planner_output=result.get("planner_output"),
        reflection=result.get("reflection"),
        adjustment=result.get("adjustment"),
        reflection_summary=result.get("reflection_summary"),
        motivation=result.get("motivation"),
        error=result.get("error"),
    )


@router.post("/trigger", response_model=AgentRunResponse)
async def trigger_agent_async(
    request: AgentTriggerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    """后台启动一次 Agent 运行，并立即返回可轮询的 run_id。"""
    storage = DatabaseStorage(db)
    if not await storage.get_user(request.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    run_id = str(uuid4())
    _agent_results[run_id] = {"status": "running"}

    async def run_in_background() -> None:
        """
        后台任务必须自己重新创建数据库会话。

        原因是：FastAPI 请求结束后，原本注入的 db session 很可能已经被关闭。
        如果后台协程继续复用请求里的 session，就容易出现连接失效或事务异常。
        """
        session_factory = get_session_factory()
        async with session_factory() as session:
            try:
                result = await _run_agent_for_user(
                    request.user_id,
                    request.trigger,
                    DatabaseStorage(session),
                )
                _agent_results[run_id] = result
            except Exception as exc:
                logger.error(f"Background agent run failed: {exc}")
                _agent_results[run_id] = {"status": "error", "error": str(exc)}

    background_tasks.add_task(run_in_background)

    return AgentRunResponse(
        run_id=run_id,
        status="running",
        message="Agent run started",
    )


@router.get("/status/{run_id}", response_model=AgentResultResponse)
async def get_agent_status(run_id: str) -> AgentResultResponse:
    """轮询通过 `/trigger` 启动的异步 Agent 任务状态。"""
    if run_id not in _agent_results:
        return AgentResultResponse(run_id=run_id, status="not_found")

    result = _agent_results[run_id]
    return AgentResultResponse(
        run_id=run_id,
        status=result.get("status", "unknown"),
        planner_output=result.get("planner_output"),
        reflection=result.get("reflection"),
        adjustment=result.get("adjustment"),
        reflection_summary=result.get("reflection_summary"),
        motivation=result.get("motivation"),
        error=result.get("error"),
    )
