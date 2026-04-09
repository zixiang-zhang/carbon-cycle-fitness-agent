"""聚合所有 FastAPI 子路由，形成统一的 `/api` 路由树。"""

from fastapi import APIRouter

from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.food import router as food_router
from app.api.health import router as health_router
from app.api.log import router as log_router
from app.api.plan import router as plan_router
from app.api.report import router as report_router
from app.api.user import router as user_router
from app.api.weight import router as weight_router

api_router = APIRouter()

# 健康检查接口保持最短路径，便于部署后做存活探针和监控探针。
api_router.include_router(health_router, tags=["health"])

# 其他业务接口按资源维度拆分并挂载，阅读时可以把这里看成后端接口总目录。
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(user_router, prefix="/users", tags=["users"])
api_router.include_router(plan_router, prefix="/plans", tags=["plans"])
api_router.include_router(log_router, prefix="/logs", tags=["logs"])
api_router.include_router(weight_router, prefix="/weights", tags=["weights"])
api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(report_router, prefix="/reports", tags=["reports"])
api_router.include_router(food_router, prefix="/food", tags=["food"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])

__all__ = ["api_router"]
