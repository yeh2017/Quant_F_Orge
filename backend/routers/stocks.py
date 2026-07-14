"""
股票 & 可转债 & 数据源 路由
============================
从 main.py 提取，保持 API 路径不变。
"""

from datetime import date, datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from services.stock_service import StockService
from utils.json_utils import sanitize as _sanitize

router = APIRouter(tags=["Stocks"])

_stock = StockService()



# -------------------- 股票 --------------------


@router.get("/stocks/info/{code}")
async def get_stock_info(code: str):
    """统一信息查询 — 自动识别股票/ETF/可转债"""
    from utils.bar_query import is_bond, is_etf
    if is_bond(code):
        info = _stock.get_bond_info(code)
    elif is_etf(code):
        info = _stock.get_etf_info(code)
    else:
        info = _stock.get_stock_info(code)
    if not info:
        raise HTTPException(status_code=404, detail=f"未找到 {code}")
    return info



@router.get("/stocks/history/{code}")
async def get_stock_history(
    code: str,
    start_date: str = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    adjust: str = Query("qfq", description="复权类型: qfq/hfq/none"),
):
    if not end_date:
        from utils.trade_date import get_table_latest_date
        end_date = get_table_latest_date("bars")
        if not end_date:
            return {"code": code, "data": [], "message": "无行情数据，请先同步"}
    if not start_date:
        # 不硬编码天数，查 DB 中该标的最早日期，有多少数据显示多少
        from core.database import db_session
        from utils.bar_query import get_bar_model, to_db_code
        from sqlalchemy import func as sqlfunc
        try:
            BarModel = get_bar_model(code)
            resolved = to_db_code(code)
            with db_session() as db:
                earliest = db.query(sqlfunc.min(BarModel.trade_date)).filter(
                    BarModel.code == resolved
                ).scalar()
            if earliest:
                start_date = str(earliest)
            else:
                start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        except Exception as _e:
            import structlog
            structlog.get_logger("stocks_router").debug("earliest_date_query_failed", code=code, error=str(_e))
            start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    history = _stock.get_stock_history(code, start_date, end_date, adjust)
    if not history:
        # 区分退市 vs 未同步，给出准确提示（统一覆盖三类资产）
        from utils.bar_query import is_bond, is_etf, to_db_code
        from core.database import db_session as _ds
        resolved = to_db_code(code)
        with _ds() as _db:
            if is_bond(code):
                from models.quant_data import ConvertibleBondBasic
                rec = _db.query(ConvertibleBondBasic).filter_by(code=code).first()
                if rec and not rec.listed:
                    return {"code": code, "data": [], "message": f"{code} ({rec.name or '未知'}) 已退市/到期，无历史行情"}
                if rec and (rec.issue_date is None or rec.issue_date > date.today()):
                    return {"code": code, "data": [], "message": f"{code} ({rec.name or '未知'}) 尚未上市，暂无历史行情"}
            elif is_etf(code):
                from models.quant_data import EtfBasicInfo
                rec = _db.query(EtfBasicInfo).filter(EtfBasicInfo.code == resolved).first()
                if rec and not rec.is_active:
                    if not rec.list_date or rec.list_date > date.today().isoformat():
                        return {"code": code, "data": [], "message": f"{code} ({rec.name or '未知'}) 尚未上市，暂无历史行情"}
                    return {"code": code, "data": [], "message": f"{code} ({rec.name or '未知'}) 已退市/终止，无历史行情"}
            else:
                from models.quant_data import StockBasicInfo
                rec = _db.query(StockBasicInfo).filter(StockBasicInfo.code == resolved).first()
                if rec and not rec.is_active:
                    return {"code": code, "data": [], "message": f"{code} ({rec.name or '未知'}) 已退市，无历史行情"}
        return {"code": code, "data": [], "message": f"{code} 暂无历史数据，请先在数据中台同步"}
    return _sanitize({"code": code, "data": history})



@router.get("/stocks/search")
async def search_stocks(keyword: str = Query(..., min_length=1)):
    """统一搜索 — 股票 + ETF 合并结果"""
    stocks = _stock.search_stocks(keyword)
    etfs = _stock.search_etf(keyword)
    return {"results": stocks[:15] + etfs[:5]}


@router.get("/stocks/margin/{code}")
async def get_margin_history(
    code: str,
    start_date: str = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
):
    """个股融资余额时序（K线叠加用）"""
    from core.database import db_session
    from models.quant_data import StockMarginData
    from utils.asset_type import to_ts_code  # margin 表存 Tushare 格式，非 bar 表
    resolved = to_ts_code(code)
    with db_session() as db:
        q = db.query(
            StockMarginData.trade_date, StockMarginData.rzye
        ).filter(StockMarginData.code == resolved)
        if start_date:
            q = q.filter(StockMarginData.trade_date >= start_date)
        if end_date:
            q = q.filter(StockMarginData.trade_date <= end_date)
        rows = q.order_by(StockMarginData.trade_date.asc()).all()
    return {
        "data": [
            {"date": str(r.trade_date), "rzye": r.rzye}
            for r in rows if r.rzye
        ]
    }



# -------------------- 可转债 --------------------


@router.get("/bonds/info/{code}")
async def get_bond_info(code: str):
    info = _stock.get_bond_info(code)
    if not info:
        raise HTTPException(status_code=404, detail=f"未找到可转债 {code}")
    return info



@router.get("/bonds/search")
async def search_bonds(keyword: str = Query(..., min_length=1)):
    results = _stock.search_bonds(keyword)
    return {"results": results}



# -------------------- 技术诊断 --------------------


@router.get("/stocks/diagnosis/{code}")
async def get_diagnosis(code: str, end_date: str = Query(None)):
    """单只完整诊断 — 6维+评分+支撑压力（给 VisualPanel）"""
    from services.technical_service import TechnicalService
    result = TechnicalService().diagnose(code, end_date)
    if not result:
        return None
    return _sanitize(result)


@router.post("/stocks/diagnosis/batch")
async def batch_diagnosis(payload: dict):
    """批量精简诊断 — 评分+趋势（给 Screener/Backtest 列表）"""
    codes = payload.get("codes", [])[:50]
    if not codes:
        return {}
    from services.technical_service import TechnicalService
    return _sanitize(TechnicalService().diagnose_batch(codes))

