"""
自动选股器 API — 路由聚合
========================
将 screener_market（大盘/个股）和 screener_etf（ETF）子路由统一注册到 /screener 前缀下。
"""

from fastapi import APIRouter
from routers.screener_market import router as market_router
from routers.screener_etf import router as etf_router

router = APIRouter(prefix="/screener", tags=["Screener"])
router.include_router(market_router)
router.include_router(etf_router)
