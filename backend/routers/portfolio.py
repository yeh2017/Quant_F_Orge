"""
组合优化路由
============
POST /portfolio/optimize
  — 接收 codes[] + 优化方法，返回权重分配方案
  — 独立运行，无需先跑回测
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict

from services.portfolio_service import PortfolioService
from settings import TRADING_DAYS

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])

_portfolio = PortfolioService()


class OptimizeRequest(BaseModel):
    codes: List[str]
    method: str = "max_sharpe"            # max_sharpe | risk_parity | min_variance | equal_weight
    lookback_days: int = TRADING_DAYS              # 历史窗口（交易日）
    expected_returns: Optional[Dict[str, float]] = None  # 可注入因子评分
    stock_names: Optional[Dict[str, str]] = None         # {code: name} 用于展示


class OptimizeAllRequest(BaseModel):
    codes: List[str]
    lookback_days: int = TRADING_DAYS
    expected_returns: Optional[Dict[str, float]] = None
    stock_names: Optional[Dict[str, str]] = None


def _fill_names(result: dict, stock_names: Optional[Dict[str, str]]):
    """填充真实名称（兼容 6位/带后缀 两种格式）"""
    if not stock_names:
        return
    name_lookup = dict(stock_names)
    for k, v in stock_names.items():
        name_lookup[k.split('.')[0]] = v
    for h in result.get("holdings", []):
        code = h["code"]
        clean = code.split('.')[0]
        h["name"] = name_lookup.get(code) or name_lookup.get(clean) or code


@router.post("/optimize")
def optimize_portfolio(req: OptimizeRequest):
    """计算单种方法的组合最优权重。"""
    try:
        if not req.codes:
            raise HTTPException(status_code=400, detail="codes 不能为空")
        if len(req.codes) > 100:
            raise HTTPException(status_code=400, detail="单次最多支持 100 只标的")

        result = _portfolio.optimize(
            codes=req.codes,
            method=req.method,
            lookback_days=req.lookback_days,
            expected_returns_override=req.expected_returns,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        _fill_names(result, req.stock_names)
        return {"status": "success", **result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize-all")
def optimize_all(req: OptimizeAllRequest):
    """一次加载数据，计算全部 4 种优化方法。"""
    try:
        if not req.codes:
            raise HTTPException(status_code=400, detail="codes 不能为空")
        if len(req.codes) > 100:
            raise HTTPException(status_code=400, detail="单次最多支持 100 只标的")

        result = _portfolio.optimize_all(
            codes=req.codes,
            lookback_days=req.lookback_days,
            expected_returns_override=req.expected_returns,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # 给每种方法的结果填充名称
        for method_result in result.get("results", {}).values():
            if "error" not in method_result:
                _fill_names(method_result, req.stock_names)

        return {"status": "success", **result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ── 再平衡模拟 ──

class RebalanceSimRequest(BaseModel):
    codes: List[str]
    method: str = "max_sharpe"
    period: str = "monthly"           # monthly | quarterly
    lookback_days: int = TRADING_DAYS
    commission_rate: float = 0.001    # 单边手续费率
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None


@router.post("/rebalance-sim")
def rebalance_simulation(req: RebalanceSimRequest):
    """模拟定期再平衡"""
    try:
        result = _portfolio.rebalance_simulation(
            codes=req.codes,
            method=req.method,
            period=req.period,
            lookback_days=req.lookback_days,
            commission_rate=req.commission_rate,
            start_date=req.start_date,
            end_date=req.end_date,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return {"status": "success", **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

