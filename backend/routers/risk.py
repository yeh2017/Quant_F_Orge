"""
风险分析路由
============
POST /risk/analyze
  — 接收持仓 codes[] + date range，返回完整风险报告
  — 可独立运行，无需先跑回测
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from services.risk_service import RiskService

router = APIRouter(prefix="/risk", tags=["Risk"])

_risk = RiskService()


class AnalyzeRequest(BaseModel):
    codes: List[str]
    start_date: str
    end_date: str
    weights: Optional[List[float]] = None  # 若为 None 则等权
    include_benchmark: bool = True



@router.post("/analyze")
def analyze_risk(req: AnalyzeRequest):
    """
    基于持仓代码+时间范围计算风险指标。
    从本地 StockDailyBar 读取历史行情，构造组合收益率序列后分析。
    """
    from utils.json_utils import sanitize as _sanitize

    try:
        import numpy as np
        from core.database import db_session
        from utils.bar_query import get_bar_model, to_db_code
        from sqlalchemy import and_

        codes = req.codes
        if not codes:
            raise HTTPException(status_code=400, detail="codes 不能为空")

        weights = req.weights
        if not weights or len(weights) != len(codes):
            weights = [1.0 / len(codes)] * len(codes)
        weights = np.array(weights, dtype=float)
        weights = weights / weights.sum()

        # 读取各股/ETF历史收益率（自动路由到正确的表）
        stock_returns = {}
        all_dates = []
        with db_session() as db:
            for code in codes:
                BarModel = get_bar_model(code)
                db_code = to_db_code(code)
                rows = (db.query(BarModel.trade_date, BarModel.close)
                        .filter(and_(
                            BarModel.code == db_code,
                            BarModel.trade_date >= req.start_date,
                            BarModel.trade_date <= req.end_date,
                        ))
                        .order_by(BarModel.trade_date.asc())
                        .all())
                if len(rows) >= 10:
                    if not all_dates:  # 只取第一只有效股的日期序列，避免循环覆盖
                        all_dates = [r.trade_date for r in rows]
                    closes = np.array([r.close for r in rows], dtype=float)
                    # 清除 NaN 价格
                    closes = np.where(np.isnan(closes), 0.0, closes)
                    valid = closes > 0
                    if valid.sum() >= 10:
                        stock_returns[code] = np.diff(closes) / np.where(closes[:-1] > 0, closes[:-1], 1.0)

        if not stock_returns:
            raise HTTPException(status_code=400,
                detail="未找到有效行情数据，请先在数据中台同步指定时间段的行情")

        # 对齐序列
        min_len = min(len(v) for v in stock_returns.values())
        aligned_codes = [c for c in codes if c in stock_returns]
        aligned_weights = np.array([weights[codes.index(c)] for c in aligned_codes])
        aligned_weights = aligned_weights / aligned_weights.sum()

        returns_matrix = np.array([stock_returns[c][-min_len:] for c in aligned_codes])
        portfolio_returns = aligned_weights @ returns_matrix
        portfolio_returns = np.nan_to_num(portfolio_returns, nan=0.0, posinf=0.0, neginf=0.0)
        net_values = np.cumprod(1 + portfolio_returns).tolist()

        # 日期序列（安全取值）
        date_strs = [str(d) for d in all_dates[-min_len:]] if all_dates else None

        # 基准收益
        benchmark_returns = None
        if req.include_benchmark:
            benchmark_returns = _risk.get_benchmark_returns(req.start_date, req.end_date) or None

        result = _risk.analyze(
            portfolio_returns=portfolio_returns.tolist(),
            benchmark_returns=benchmark_returns,
            net_values=net_values,
            dates=date_strs,
        )

        return _sanitize({
            "status": "success",
            "codes": aligned_codes,
            "weights": aligned_weights.tolist(),
            "data_points": min_len,
            "requested_start_date": req.start_date,
            "requested_end_date": req.end_date,
            "actual_start_date": str(all_dates[0]) if all_dates else None,
            "actual_end_date": str(all_dates[-1]) if all_dates else None,
            "risk": result,
        })

    except HTTPException:
        raise
    except Exception as e:
        import structlog as _sl
        _sl.get_logger("risk_router").exception("risk_analyze_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
