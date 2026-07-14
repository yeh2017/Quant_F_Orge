"""
回测路由
========
从 main.py 提取，保持 API 路径不变。
"""

import json
import numpy as np
import structlog

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from core.database import get_db
from models import all_models
from services.stock_service import StockService
from services.backtest_service import BacktestService
from utils.task_store import task_store, TaskStatus

router = APIRouter(prefix="/backtest", tags=["Backtest"])

_log = structlog.get_logger("backtest_router")
_stock = StockService()
_backtest = BacktestService(_stock)


from utils.json_utils import sanitize as _sanitize


# ── 请求模型 ──

class BacktestRequest(BaseModel):
    codes: Optional[List[str]] = Field(None, description="固定标的池（与 universe_config 二选一）")
    strategy_type: str = Field("multifactor", description="策略类型")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")
    initial_cash: float = Field(1000000, description="初始资金")
    commission: float = Field(0.0003, description="手续费率")
    selected_factors: Optional[Dict[str, bool]] = Field(None, description="选中的因子")
    rebalance_period: str = Field("monthly", description="调仓周期")
    strategy_params: Optional[Dict[str, Any]] = Field(None, description="策略参数")
    universe_config: Optional[Dict[str, Any]] = Field(None, description="动态标的池配置")

# ── 参数统一抽取（同步/异步路由共用） ──

def _validate_request(request: BacktestRequest):
    """前置校验：codes 和 universe_config 至少有一个"""
    if not request.codes and not request.universe_config:
        raise HTTPException(status_code=400, detail="请传入 codes 或 universe_config")


def _build_backtest_kwargs(request: BacktestRequest) -> dict:
    """从 Request 构建 run_backtest 参数字典（唯一来源）"""
    return dict(
        stock_codes=request.codes,
        strategy_type=request.strategy_type,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_cash=request.initial_cash,
        commission=request.commission,
        selected_factors=request.selected_factors,
        rebalance_period=request.rebalance_period,
        strategy_params=request.strategy_params,
        universe_config=request.universe_config,
    )

# ── 标的池预览（回测前预估） ──

@router.post("/preview_universe")
async def preview_universe(request: BacktestRequest):
    """回测前预估标的数量和复杂度，帮助用户决定是否继续"""
    from services.universe_provider import create_provider
    import datetime

    start = request.start_date or (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    end = request.end_date or datetime.date.today().isoformat()

    if request.codes:
        count = len(request.codes)
    elif request.universe_config:
        try:
            provider = create_provider(request.universe_config)
            codes = provider.get_codes(end)
            count = len(codes)
        except Exception as e:
            return {"count": 0, "error": str(e)}
    else:
        raise HTTPException(status_code=400, detail="请传入 codes 或 universe_config")

    # 粗估耗时（基于经验值：~0.5s/100只/年）
    import math
    max_stocks = (request.universe_config or {}).get("max_stocks", 500)
    actual_count = min(count, max_stocks)
    years = max((datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days / 365, 0.1)
    estimated_seconds = math.ceil(actual_count / 100 * years * 0.5)

    return {
        "count": count,
        "actual_count": actual_count,
        "start_date": start,
        "end_date": end,
        "estimated_seconds": estimated_seconds,
        "warning": f"匹配 {count} 只，实际回测取前 {actual_count} 只（按市值排序）" if count > max_stocks else None,
    }



@router.post("/run")
async def run_backtest(request: BacktestRequest):
    _validate_request(request)
    import asyncio
    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(
            None, lambda: _backtest.run_backtest(**_build_backtest_kwargs(request))
        )
        return results
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 策略对比 ──

class CompareRequest(BaseModel):
    codes: List[str] = Field(..., description="股票代码列表")
    strategies: List[str] = Field(..., description="策略类型列表")
    start_date: Optional[str] = Field(None)
    end_date: Optional[str] = Field(None)
    initial_cash: float = Field(1000000)
    commission: float = Field(0.0003)
    rebalance_period: str = Field("monthly")


@router.post("/compare")
async def compare_strategies(request: CompareRequest):
    """同一股票池多策略横向对比（并行）"""
    import asyncio

    loop = asyncio.get_running_loop()

    def _run_one(st: str):
        try:
            res = _backtest.run_backtest(
                stock_codes=request.codes,
                strategy_type=st,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_cash=request.initial_cash,
                commission=request.commission,
                rebalance_period=request.rebalance_period,
            )
            return st, _sanitize({
                "total_return": res.get("total_return"),
                "annual_return": res.get("annual_return"),
                "max_drawdown": res.get("max_drawdown"),
                "sharpe_ratio": res.get("sharpe_ratio"),
                "sortino_ratio": res.get("sortino_ratio"),
                "volatility": res.get("volatility"),
                "win_rate": res.get("win_rate"),
                "excess_return": res.get("excess_return"),
                "cumReturns": res.get("cumReturns"),
                "dates": res.get("dates"),
                "benchmark": res.get("benchmark"),
            })
        except Exception as e:
            _log.warning("compare_strategy_failed", strategy=st, error=str(e))
            return st, {"error": str(e)}

    tasks = [loop.run_in_executor(None, _run_one, st) for st in request.strategies]
    pairs = await asyncio.gather(*tasks)
    results = {st: data for st, data in pairs}

    return {"strategies": results, "codes": request.codes}


# ── 参数优化（网格搜索） ──

class OptimizeRequest(BaseModel):
    codes: List[str] = Field(..., description="股票代码列表")
    strategy_type: str = Field(..., description="策略类型")
    param_ranges: Dict[str, List] = Field(..., description="参数范围 {name: [v1, v2, ...]}")
    start_date: Optional[str] = Field(None)
    end_date: Optional[str] = Field(None)
    initial_cash: float = Field(1000000)
    commission: float = Field(0.0003)
    rebalance_period: str = Field("monthly")
    top_n: int = Field(10, ge=1, le=50)


@router.post("/optimize")
async def optimize_parameters(request: OptimizeRequest):
    """网格搜索最优参数组合"""
    import itertools
    import asyncio

    param_names = list(request.param_ranges.keys())
    param_values = list(request.param_ranges.values())

    # 计算组合数，限制上限
    combos = list(itertools.product(*param_values))
    if len(combos) > 500:
        return {"error": f"参数组合过多({len(combos)})，请缩小范围（上限500）"}

    loop = asyncio.get_running_loop()

    def _run_one(combo):
        params = dict(zip(param_names, combo))
        try:
            res = _backtest.run_backtest(
                stock_codes=request.codes,
                strategy_type=request.strategy_type,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_cash=request.initial_cash,
                commission=request.commission,
                rebalance_period=request.rebalance_period,
                strategy_params=params,
            )
            sharpe = res.get("sharpe_ratio")
            if sharpe is not None and not (np.isnan(sharpe) or np.isinf(sharpe)):
                return {
                    "params": params,
                    "sharpe_ratio": round(sharpe, 4),
                    "total_return": round(res.get("total_return", 0), 2),
                    "annual_return": round(res.get("annual_return", 0), 2),
                    "max_drawdown": round(res.get("max_drawdown", 0), 2),
                    "sortino_ratio": round(res.get("sortino_ratio", 0) or 0, 4),
                    "win_rate": round(res.get("win_rate", 0) or 0, 2),
                }
        except Exception as e:
            _log.debug("optimize_combo_failed", params=params, error=str(e))
        return None

    tasks = [loop.run_in_executor(None, _run_one, combo) for combo in combos]
    raw_results = await asyncio.gather(*tasks)
    results = [r for r in raw_results if r is not None]

    # 按夏普排序
    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    return {
        "strategy_type": request.strategy_type,
        "total_combos": len(combos),
        "valid_results": len(results),
        "top": results[:request.top_n],
    }


# ── 异步回测任务包装器 ──

def _run_backtest_wrapper(task_id: str, request: BacktestRequest):
    """回测任务包装器（含结果持久化）"""
    try:
        task_store.update_task(task_id, TaskStatus.RUNNING)
        results = _backtest.run_backtest(**_build_backtest_kwargs(request))
        task_store.update_task(task_id, TaskStatus.COMPLETED, result=results)

        # 持久化到 DB
        try:
            from core.database import db_session

            with db_session() as db:
                record = all_models.BacktestResult(
                    task_id=task_id,
                    strategy_type=request.strategy_type,
                    codes=json.dumps(request.codes or []),
                    universe_config=json.dumps(request.universe_config) if request.universe_config else None,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    total_return=_sanitize(results.get("total_return")),
                    annual_return=_sanitize(results.get("annual_return")),
                    sharpe_ratio=_sanitize(results.get("sharpe_ratio")),
                    max_drawdown=_sanitize(results.get("max_drawdown")),
                    win_rate=_sanitize(results.get("win_rate")),
                    result_json=json.dumps(_sanitize(results)),
                )
                db.merge(record)
        except Exception as persist_err:
            _log.warning("backtest_persist_failed", error=str(persist_err))

    except Exception as e:
        task_store.update_task(task_id, TaskStatus.FAILED, error=str(e))


# ── 异步回测 ──

@router.post("/run_async")
async def run_backtest_async(
    request: BacktestRequest,
    background_tasks: BackgroundTasks,
):
    _validate_request(request)
    # 去重：检查是否已有 backtest 任务在运行
    existing = task_store.get_running_task("backtest")
    if existing:
        raise HTTPException(status_code=409, detail=f"已有回测任务在运行，请等待完成后再提交")
    task_id = task_store.create_task("backtest")
    background_tasks.add_task(_run_backtest_wrapper, task_id, request)
    return {"task_id": task_id, "status": "pending"}


# ── 任务状态 ──

@router.get("/status/{task_id}")
async def get_backtest_status(task_id: str):
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _sanitize(task)


# ── 历史记录 ──

@router.get("/list")
async def list_backtest_results(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(all_models.BacktestResult)
        .order_by(all_models.BacktestResult.created_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for r in rows:
        # 构建摘要标签：帮助区分同策略的不同回测
        summary_parts = []
        uc = None
        if r.universe_config:
            try:
                uc = json.loads(r.universe_config)
            except (json.JSONDecodeError, TypeError):
                pass
        if uc:
            uc_type = uc.get('type', '')
            if uc_type == 'full_market':
                summary_parts.append(f"全市场·{uc.get('max_stocks', '?')}只")
            elif uc_type == 'factor_filter':
                filters = uc.get('filters', {})
                tags = []
                if 'pe_ttm_max' in filters: tags.append(f"PE≤{filters['pe_ttm_max']}")
                if 'pb_max' in filters: tags.append(f"PB≤{filters['pb_max']}")
                if 'total_mv_min' in filters:
                    mv = filters['total_mv_min']
                    tags.append(f"市值≥{mv/10000:.0f}亿" if mv >= 10000 else f"市值≥{mv}万")
                if 'dv_ratio_min' in filters: tags.append(f"股息≥{filters['dv_ratio_min']}%")
                summary_parts.append('·'.join(tags[:3]) if tags else '因子筛选')
        else:
            # 固定池：显示标的数
            try:
                codes = json.loads(r.codes or '[]')
                summary_parts.append(f"{len(codes)}只标的")
            except (json.JSONDecodeError, TypeError):
                pass

        # 从 result_json 提取策略参数摘要（覆盖所有内置策略的关键区分参数）
        try:
            rj = json.loads(r.result_json) if r.result_json else {}
            sp = rj.get('strategy_params', {})
            # 模式（均线/MACD/因子选股等双模式策略）
            MODE_LABELS = {
                'crossover': '金叉', 'pullback': '回踩',
                'macd': 'MACD', 'rsi': 'RSI',
                'composite': '复合', 'value_only': '纯估值',
            }
            if sp.get('mode'): summary_parts.append(MODE_LABELS.get(sp['mode'], sp['mode']))
            # 事件驱动：事件类型 + 方向
            if sp.get('event_type'): summary_parts.append(sp['event_type'])
            DIR_LABELS = {'positive': '利好', 'negative': '利空', 'both': '不限'}
            if sp.get('direction'): summary_parts.append(DIR_LABELS.get(sp['direction'], sp['direction']))
            if sp.get('hold_days'): summary_parts.append(f"持{sp['hold_days']}日")
            # 持仓/调仓
            if sp.get('top_n'): summary_parts.append(f"Top{sp['top_n']}")
            REB_LABELS = {'monthly': '月', 'weekly': '周', 'daily': '日', 'quarterly': '季'}
            if sp.get('rebalance'): summary_parts.append(REB_LABELS.get(sp['rebalance'], sp['rebalance']))
            # 均线/周期参数
            if sp.get('fast_ma') and sp.get('slow_ma'): summary_parts.append(f"MA{sp['fast_ma']}/{sp['slow_ma']}")
            if sp.get('lookback_days'): summary_parts.append(f"回看{sp['lookback_days']}日")
            # 网格
            if sp.get('grid_pct'): summary_parts.append(f"网格{sp['grid_pct']}%")
            # 海龟
            if sp.get('entry') and sp.get('exit'): summary_parts.append(f"通道{sp['entry']}/{sp['exit']}")
            # 布林带
            if sp.get('window') and sp.get('num_std'): summary_parts.append(f"BB{sp['window']}·{sp['num_std']}σ")
            # 放量
            if sp.get('vol_ratio'): summary_parts.append(f"量比{sp['vol_ratio']}")
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        results.append({
            "id": r.id,
            "task_id": r.task_id,
            "strategy_type": r.strategy_type,
            "codes": r.codes,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "total_return": r.total_return,
            "annual_return": r.annual_return,
            "max_drawdown": r.max_drawdown,
            "sharpe_ratio": r.sharpe_ratio,
            "has_universe": bool(r.universe_config),
            "summary": ' · '.join(summary_parts) if summary_parts else None,
            "created_at": str(r.created_at)[:19] if r.created_at else None,
        })
    return results

# ── 详情（完整结果回放） ──

@router.get("/{result_id}/detail")
async def get_backtest_detail(result_id: int, db: Session = Depends(get_db)):
    """返回完整回测结果，供前端回放历史记录"""
    row = db.query(all_models.BacktestResult).filter(
        all_models.BacktestResult.id == result_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    # 优先用 result_json（完整），fallback 到 result_data（旧格式）
    result = None
    if row.result_json:
        try:
            result = json.loads(row.result_json)
        except (json.JSONDecodeError, TypeError):
            pass
    if result is None and row.result_data:
        result = row.result_data

    codes = []
    if row.codes:
        try:
            codes = json.loads(row.codes)
        except (json.JSONDecodeError, TypeError):
            pass

    universe_config = None
    if row.universe_config:
        try:
            universe_config = json.loads(row.universe_config)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": row.id,
        "strategy_type": row.strategy_type,
        "codes": codes,
        "universe_config": universe_config,
        "start_date": row.start_date,
        "end_date": row.end_date,
        "created_at": str(row.created_at)[:19] if row.created_at else None,
        "result": _sanitize(result) if result else None,
    }


# ── 删除记录 ──

@router.delete("/{result_id}")
async def delete_backtest_result(result_id: int, db: Session = Depends(get_db)):
    row = db.query(all_models.BacktestResult).filter(
        all_models.BacktestResult.id == result_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="回测记录不存在")
    db.delete(row)
    return {"status": "deleted", "id": result_id}


class BatchDeleteRequest(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=200, description="要删除的回测记录 ID 列表")


@router.post("/batch_delete")
async def batch_delete_backtest_results(request: BatchDeleteRequest, db: Session = Depends(get_db)):
    """批量删除回测记录"""
    deleted = db.query(all_models.BacktestResult).filter(
        all_models.BacktestResult.id.in_(request.ids)
    ).delete(synchronize_session=False)
    return {"status": "deleted", "deleted_count": deleted}
