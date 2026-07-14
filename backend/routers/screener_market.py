"""
大盘状态 + 个股筛选 + 行业热力图
==============================
拆自 screener.py，包含：
  - /market-regime   大盘市场状态
  - /stock-reversal  个股弱转强/强转弱
  - /industries      行业列表
  - /industry-heat   行业热力图
  - POST /           按因子阈值筛选股票
  - /stock-to-etf    个股→ETF 反向联动
"""

from fastapi import APIRouter, Query
from sqlalchemy import func
from pydantic import BaseModel, Field
from typing import Optional, List
import structlog

from core.database import db_session
from models.quant_data import StockBasicInfo

router = APIRouter()
log = structlog.get_logger(__name__)


@router.get("/market-regime")
def get_market_regime():
    """大盘市场状态判定 — 路由层委托 service。"""
    from services.screener.market_service import get_market_regime as _regime
    with db_session() as db:
      try:
        return _regime(db)
      except Exception as e:
        log.error("market_regime_failed", error=str(e))
        return {"regime": "未知", "regime_color": "slate", "composite_score": 0, "error": str(e)}


@router.get("/stock-reversal")
def get_stock_reversal(top_n: int = Query(5, ge=1, le=20)):
    """个股弱转强/强转弱 — 路由层委托 service。"""
    from services.screener.market_service import get_stock_reversal as _reversal
    with db_session() as db:
      try:
        return _reversal(db, top_n=top_n)
      except Exception as e:
        log.error("stock_reversal_failed", error=str(e))
        return {"weak_to_strong": [], "strong_to_weak": [], "error": str(e)}



class ScreenerRequest(BaseModel):
    pe_max: Optional[float] = Field(None, description="市盈率上限")
    pb_max: Optional[float] = Field(None, description="市净率上限")
    roe_min: Optional[float] = Field(None, description="ROE 下限(%)")
    revenue_yoy_min: Optional[float] = Field(None, description="营收同比增长下限(%)")
    net_profit_yoy_min: Optional[float] = Field(None, description="净利润同比增长下限(%)")
    turnover_rate_min: Optional[float] = Field(None, description="换手率下限(%)")
    net_inflow_min: Optional[float] = Field(None, description="主力净流入下限(万元)")
    pct_chg_min: Optional[float] = Field(None, description="涨跌幅下限(%)")
    pct_chg_max: Optional[float] = Field(None, description="涨跌幅上限(%)")
    volume_ratio_min: Optional[float] = Field(None, description="量比下限(如 2 表示 2 倍放量)")
    gap_up: Optional[bool] = Field(None, description="仅显示跳空高开")
    holder_chg_max: Optional[float] = Field(None, description="股东户数变化率上限(%)，负值表示筹码集中")
    max_list_days: Optional[int] = Field(None, ge=1, description="上市天数上限（如365=次新股）")
    has_block_trade: Optional[bool] = Field(None, description="近5交易日有大宗交易")
    has_unlock: Optional[bool] = Field(None, description="近5交易日有解禁")
    has_top_list: Optional[bool] = Field(None, description="近5交易日上龙虎榜")
    margin_chg_min: Optional[float] = Field(None, description="融资余额5日变化率下限(%)")
    industries: Optional[List[str]] = Field(None, description="行业筛选 (多选)")
    index_filter: Optional[str] = Field(None, description="指数成分筛选: hs300/csi500/csi1000")
    sort_by: str = Field("score", description="排序字段: score/pe/pb/roe/pct_chg/turnover/revenue_yoy/net_profit_yoy/net_mf_amount/total_mv/holder_chg/margin_chg")
    sort_order: str = Field("desc", description="排序方向: asc/desc")
    page: int = Field(1, ge=1, description="页码（从1开始）")
    page_size: int = Field(50, ge=1, le=200, description="每页数量")
    limit: int = Field(50, ge=1, le=500, description="返回数量上限（兼容旧接口）")


@router.get("/industries")
def get_industries():
    """获取所有可选行业列表及包含的股票数量（按数量倒序）"""
    with db_session() as db:
        try:
            rows = (
                db.query(
                    StockBasicInfo.industry,
                    func.count(StockBasicInfo.code).label('stock_count')
                )
                .filter(StockBasicInfo.industry != None, StockBasicInfo.industry != "")
                .group_by(StockBasicInfo.industry)
                .order_by(func.count(StockBasicInfo.code).desc())
                .all()
            )
            industries = [{"name": r[0], "count": r[1]} for r in rows]
            return {"industries": industries, "total": len(industries)}
        except Exception as e:
            log.error("industries_query_failed", error=str(e))
            return {"industries": [], "total": 0, "error": str(e)}


@router.get("/industry-heat")
def get_industry_heat():
    """行业热力图 — 路由层委托 service。"""
    from services.screener.market_service import get_industry_heat as _heat
    with db_session() as db:
      try:
        return _heat(db)
      except Exception as e:
        log.error("industry_heat_failed", error=str(e))
        return {"heat": {}, "heat_5d": {}, "rankings": {}, "trade_date": None, "error": str(e)}


@router.post("/")
def screen_stocks(request: ScreenerRequest):
    """
    按因子阈值筛选股票 — 路由层委托 service。
    """
    from services.screener.market_service import screen_stocks as _screen
    with db_session() as db:
      try:
        return _screen(
            db,
            pe_max=request.pe_max, pb_max=request.pb_max,
            roe_min=request.roe_min,
            revenue_yoy_min=request.revenue_yoy_min,
            net_profit_yoy_min=request.net_profit_yoy_min,
            turnover_rate_min=request.turnover_rate_min,
            net_inflow_min=request.net_inflow_min,
            pct_chg_min=request.pct_chg_min, pct_chg_max=request.pct_chg_max,
            volume_ratio_min=request.volume_ratio_min,
            gap_up=request.gap_up,
            holder_chg_max=request.holder_chg_max,
            max_list_days=request.max_list_days,
            has_block_trade=request.has_block_trade,
            has_unlock=request.has_unlock,
            has_top_list=request.has_top_list,
            margin_chg_min=request.margin_chg_min,
            industries=request.industries,
            index_filter=request.index_filter,
            sort_by=request.sort_by, sort_order=request.sort_order,
            page=request.page,
            page_size=request.page_size or request.limit,
        )
      except Exception as e:
        log.error("screen_stocks_failed", error=str(e))
        return {"stocks": [], "total": 0, "error": str(e)}




# ==================== 个股→ETF 反向联动 ====================

@router.get("/stock-to-etf")
def get_stock_to_etf(code: str):
    """个股→ETF 反向联动 — 路由层委托 service。"""
    from services.screener.market_service import get_stock_to_etf as _s2e
    with db_session() as db:
      try:
        return _s2e(db, code=code)
      except Exception as e:
        log.error("stock_to_etf_failed", code=code, error=str(e))
        return {"code": code, "industry": None, "etfs": [], "error": str(e)}


class EventTagsRequest(BaseModel):
    codes: List[str] = Field(..., description="股票代码列表")


@router.post("/event-tags")
def get_event_tags(request: EventTagsRequest):
    """批量查询近5日事件标签 + 融资余额趋势。"""
    from services.screener.market_service import get_event_tags as _tags
    with db_session() as db:
      try:
        return _tags(db, request.codes)
      except Exception as e:
        log.error("event_tags_failed", error=str(e))
        return {}

