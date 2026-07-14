"""
因子计算 & 策略参数 路由
========================
从 main.py 提取，保持 API 路径不变。
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
import threading
import time as _time
import structlog

log = structlog.get_logger(__name__)

from services.stock_service import StockService
from services.factor_service import FactorService

router = APIRouter(tags=["Factors"])

_stock = StockService()
_factor = FactorService(_stock)


# ── 因子计算 TTL 缓存（5分钟，线程安全）──

_factor_cache: dict = {}
_factor_cache_lock = threading.Lock()
_FACTOR_TTL = 300


def _cache_key(codes, start_date, end_date, selected_factors, factor_weights=None):
    return hash((
        tuple(sorted(codes)),
        start_date, end_date,
        tuple(sorted((selected_factors or {}).items())),
        tuple(sorted((factor_weights or {}).items())),
    ))


def _cache_get(key):
    with _factor_cache_lock:
        entry = _factor_cache.get(key)
        if entry and (_time.time() - entry['ts']) < _FACTOR_TTL:
            return entry['data']
        return None


def _cache_set(key, data):
    with _factor_cache_lock:
        _factor_cache[key] = {'data': data, 'ts': _time.time()}
        if len(_factor_cache) > 100:
            oldest = min(_factor_cache, key=lambda k: _factor_cache[k]['ts'])
            del _factor_cache[oldest]


from utils.json_utils import sanitize as _sanitize


# ── 请求模型 ──

class FactorRequest(BaseModel):
    codes: List[str] = Field(..., description="股票代码列表")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")
    selected_factors: Optional[Dict[str, bool]] = Field(None, description="选中的因子")
    factor_weights: Optional[Dict[str, float]] = Field(None, description="因子权重")


# ── 因子元数据 ──

@router.get("/factors/meta")
async def get_factor_meta():
    from services.factors.calculator import get_factor_cards, get_factor_weights
    return {
        "cards": get_factor_cards(),
        "weights": get_factor_weights(),
    }


# ── 因子计算 ──

@router.post("/factors/calculate")
async def calculate_factors(request: FactorRequest):
    from utils.trade_date import get_table_latest_date
    end_date = request.end_date or get_table_latest_date("bars")
    if not end_date:
        return {"factor_scores": [], "total": 0, "message": "无行情数据"}
    start_date = request.start_date or (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")

    # 构建请求级权重副本（不修改共享单例，线程安全）
    local_weights = None
    if request.factor_weights:
        local_weights = FactorService.normalize_weights(request.factor_weights)

    ck = _cache_key(request.codes, start_date, end_date, request.selected_factors, request.factor_weights)
    cached = _cache_get(ck)
    if cached:
        return cached

    results = _factor.calculate_factor_scores_fast(
        request.codes, start_date, end_date, request.selected_factors,
        factor_weights=local_weights,
    )
    errors = []

    # 降级慢路径：限制最多 50 只，避免 300+ codes 触发全量逐只计算
    if len(results) < max(5, len(request.codes) // 3):
        slow_codes = request.codes[:50]
        if local_weights:
            _factor.set_factor_weights(local_weights)
        results, errors = _factor.calculate_factors(
            slow_codes, start_date, end_date, request.selected_factors
        )

    industry_exposure = _factor.get_industry_exposure(results)

    # 查询实际数据范围（轻量 MIN/MAX，走索引）
    actual_start, actual_end = start_date, end_date
    try:
        from core.database import db_session
        from models.quant_data import StockDailyBar
        from sqlalchemy import func, and_
        with db_session() as db:
            row = db.query(
                func.min(StockDailyBar.trade_date),
                func.max(StockDailyBar.trade_date),
            ).filter(and_(
                StockDailyBar.code.in_(request.codes[:10]),  # 抽样即可
                StockDailyBar.trade_date >= start_date,
                StockDailyBar.trade_date <= end_date,
            )).one()
            if row[0]:
                actual_start = str(row[0])
            if row[1]:
                actual_end = str(row[1])
    except Exception as e:
        import structlog as _sl
        _sl.get_logger("factors").warning("actual_date_range_query_failed", error=str(e))

    result = _sanitize({
        "factor_scores": results,
        "industry_exposure": industry_exposure,
        "total": len(results),
        "errors": errors,
        "requested_start_date": start_date,
        "actual_start_date": actual_start,
        "actual_end_date": actual_end,
    })
    _cache_set(ck, result)

    # 持久化到 factor_snapshot（strategy_type='default'），重启后可恢复
    if results:
        import json as _json
        import threading as _th
        def _persist():
            try:
                from core.database import db_session
                from models.quant_data import FactorSnapshot
                from sqlalchemy import text as _text
                import pandas as _pd
                td = _pd.to_datetime(actual_end, errors="coerce")
                if _pd.isna(td):
                    return
                td_date = td.date()
                factor_keys = list(_factor.factor_weights.keys())
                with db_session() as db:
                    db.execute(_text(
                        "DELETE FROM factor_snapshot WHERE strategy_type = 'default'"
                    ))
                    db.flush()
                    for rank_idx, r in enumerate(results, 1):
                        db.add(FactorSnapshot(
                            code=r["code"],
                            trade_date=td_date,
                            strategy_type="default",
                            composite=r.get("composite", 0.0),
                            rank=rank_idx,
                            factors_json=_json.dumps(
                                {k: r.get(k) for k in factor_keys if k in r},
                                ensure_ascii=False,
                            ),
                        ))
            except Exception as e:
                import structlog as _sl
                _sl.get_logger("factors").warning("snapshot_persist_failed", error=str(e))
        _th.Thread(target=_persist, daemon=True).start()

    return result


# ── 因子 IC 分析 ──

@router.post("/factors/ic_analysis")
async def factor_ic_analysis(request: FactorRequest):
    from utils.trade_date import get_table_latest_date
    end_date = request.end_date or get_table_latest_date("bars")
    if not end_date:
        return {"error": "无行情数据"}
    start_date = request.start_date or (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    result = _factor.analyze_factor_ic(request.codes, start_date, end_date)
    result["requested_start_date"] = start_date
    result["actual_end_date"] = end_date
    return _sanitize(result)



@router.get("/strategies/params/{strategy_id}")
def get_strategy_params(strategy_id: str):
    from services.strategies import get_strategy_params as _get_params
    params = _get_params(strategy_id)
    if params is None:
        raise HTTPException(status_code=404, detail=f"策略 {strategy_id} 不存在")
    return params


# ── IC 衰减曲线 ──

@router.get("/factors/ic-decay")
async def factor_ic_decay():
    """各因子在不同前瞻期的 Rank IC 衰减曲线"""
    from services.factors.scoring import compute_ic_decay
    return compute_ic_decay()


# ── 因子快照（前端挂载时直接读取最新评分，避免重复计算）──

@router.get("/factors/snapshot/latest")
async def get_latest_snapshot():
    """读取最新日期的因子评分快照"""
    from core.database import db_session
    from models.quant_data import FactorSnapshot, StockBasicInfo
    from sqlalchemy import func

    with db_session() as db:
        latest_date = db.query(func.max(FactorSnapshot.trade_date)).filter(
            FactorSnapshot.strategy_type == "default"
        ).scalar()
        if not latest_date:
            return {"scores": [], "trade_date": None}

        rows = db.query(FactorSnapshot, StockBasicInfo.name).outerjoin(
            StockBasicInfo, FactorSnapshot.code == StockBasicInfo.code
        ).filter(
            FactorSnapshot.trade_date == latest_date,
            FactorSnapshot.strategy_type == "default",
        ).order_by(FactorSnapshot.rank).all()

        import json
        scores = []
        for r in rows:
            item = {
                "code": r.FactorSnapshot.code,
                "name": r.name or r.FactorSnapshot.code,
                "composite": r.FactorSnapshot.composite,
                "rank": r.FactorSnapshot.rank,
                "trade_date": str(r.FactorSnapshot.trade_date),
            }
            # 展开各因子分项分数（重启后前端能直接渲染）
            if r.FactorSnapshot.factors_json:
                try:
                    item.update(json.loads(r.FactorSnapshot.factors_json))
                except (json.JSONDecodeError, TypeError) as e:
                    log.warning("factor_json_parse_error", code=r.FactorSnapshot.code, error=str(e)[:60])
            scores.append(item)

    return {"scores": scores, "trade_date": str(latest_date)}

