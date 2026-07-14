"""
ETF 筛选 + 联动
===============
拆自 screener.py，包含：
  - /etf-stock-link   ETF→个股联动
  - /etf-reversal      ETF 弱转强/强转弱
  - /etf-smart         ETF 智能筛选
  - /etf-ranking       ETF 涨跌排行
  - /etf-overview      ETF 市场总览
  - /etf-rotation      ETF 板块轮动
"""

import structlog
from fastapi import APIRouter, Query

from core.database import db_session

log = structlog.get_logger("screener_etf")
router = APIRouter()


# ==================== ETF→个股跨资产联动 ====================

@router.get("/etf-stock-link")
def get_etf_stock_link(volume_ratio: float = 1.5, top_n: int = 5):
    """ETF 放量→个股推荐联动 — 路由层委托 service。"""
    from services.screener.etf_service import get_etf_stock_link as _link
    with db_session() as db:
      try:
        return _link(db, volume_ratio=volume_ratio, top_n=top_n)
      except Exception as e:
        log.error("etf_stock_link_failed", error=str(e))
        return {"today_links": [], "today_warnings": [],
                "week_links": [], "week_warnings": [], "error": str(e)}



@router.get("/etf-reversal")
def get_etf_reversal(top_n: int = Query(5, ge=1, le=20)):
    """ETF 弱转强/强转弱 — 路由层委托 service。"""
    from services.screener.etf_service import get_etf_reversal as _rev
    with db_session() as db:
      try:
        return _rev(db, top_n=top_n)
      except Exception as e:
        log.error("etf_reversal_failed", error=str(e))
        return {"weak_to_strong": [], "strong_to_weak": [], "error": str(e)}


@router.get("/etf-smart")
def etf_smart_screen(top_n: int = Query(20, ge=5, le=100), category: str = Query(None), sub_category: str = Query(None)):
    """ETF 智能筛选 — 路由层委托 service。"""
    from services.screener.etf_service import etf_smart_screen as _smart
    with db_session() as db:
      try:
        return _smart(db, top_n=top_n, category=category, sub_category=sub_category)
      except Exception as e:
        log.error("etf_smart_screen_failed", error=str(e))
        return {"etfs": [], "total": 0, "error": str(e)}


@router.get("/etf-ranking")
def get_etf_ranking(top_n: int = Query(10, ge=3, le=30)):
    """ETF 涨跌排行 — 路由层委托 service。"""
    from services.screener.etf_service import get_etf_ranking as _rank
    with db_session() as db:
      try:
        return _rank(db, top_n=top_n)
      except Exception as e:
        log.error("etf_ranking_failed", error=str(e))
        return {"today_top": [], "today_bottom": [],
                "fiveday_top": [], "fiveday_bottom": [], "error": str(e)}


@router.get("/etf-overview")
def get_etf_overview():
    """ETF 市场总览 — 路由层委托 service。"""
    from services.screener.etf_service import get_etf_overview as _overview
    with db_session() as db:
      try:
        return _overview(db)
      except Exception as e:
        log.error("etf_overview_failed", error=str(e))
        return {"overview": None, "category_heat": [], "error": str(e)}


@router.get("/etf-rotation")
def get_etf_rotation(days: int = Query(30, ge=5, le=60)):
    """ETF 板块轮动 — 路由层委托 service。"""
    from services.screener.etf_service import get_etf_rotation as _rot
    with db_session() as db:
      try:
        return _rot(db, days=days)
      except Exception as e:
        log.error("etf_rotation_failed", error=str(e))
        return {"dates": [], "categories": [], "matrix": [], "signals": [], "error": str(e)}
