"""
因子研究路由
============
串联 panel_loader → expression → stratified，提供研究 API。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["Research"])


class StratifiedRequest(BaseModel):
    """分层回测请求"""
    # 因子来源：二选一
    preset_name: str | None = Field(None, description="预设因子名称")
    expression: str | None = Field(None, description="自定义表达式")

    # 预设参数覆盖
    params: dict | None = Field(None, description="预设参数覆盖，如 {days: 10}")

    # 回测参数
    n_groups: int = Field(5, ge=2, le=10, description="分组数")
    start_date: str | None = Field(None, description="开始日期")
    end_date: str | None = Field(None, description="结束日期")


class ValidateRequest(BaseModel):
    """表达式验证请求"""
    expression: str = Field(..., description="因子表达式")


# ── 预设因子列表 ──

@router.get("/research/presets")
async def list_presets():
    """返回所有内置预设因子（含参数定义）"""
    from services.factors.expression import PRESET_FACTORS
    result = []
    for name, cfg in PRESET_FACTORS.items():
        result.append({
            "name": name,
            "desc": cfg["desc"],
            "params": cfg["params"],
            "template": cfg["template"],
        })
    return {"presets": result}


# ── 表达式验证 ──

@router.post("/research/validate")
async def validate_expression(req: ValidateRequest):
    """验证表达式是否合法，返回所需字段"""
    from services.factors.expression import validate_expression, get_required_fields
    is_valid, error = validate_expression(req.expression)
    fields = list(get_required_fields(req.expression)) if is_valid else []
    return {"valid": is_valid, "error": error, "required_fields": fields}


# ── 分层回测 ──

@router.post("/research/stratified")
async def run_stratified_backtest(req: StratifiedRequest):
    """
    执行分层回测。

    流程: 构建表达式 → 加载面板 → 计算因子值 → 分层回测
    """
    from services.factors.expression import (
        build_expression, evaluate, get_required_fields, ExpressionError,
    )
    from utils.trade_date import get_table_latest_date
    from services.factors.panel_loader import load_panel, get_trade_dates, get_rebalance_dates
    from services.factors.stratified import stratified_backtest
    from datetime import datetime, timedelta

    # 1. 确定表达式
    if req.preset_name:
        try:
            expr = build_expression(req.preset_name, req.params)
        except ExpressionError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif req.expression:
        expr = req.expression
    else:
        raise HTTPException(status_code=400, detail="需要 preset_name 或 expression")

    # 2. 确定日期范围
    end_date = req.end_date or get_table_latest_date("bars")
    if not end_date:
        raise HTTPException(status_code=400, detail="无行情数据，请先同步")
    start_date = req.start_date or (
        datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365 * 3)
    ).strftime("%Y-%m-%d")

    # 3. 获取股票列表（主板 + 中小板，按代码排序取前 500 只确保确定性）
    try:
        from core.database import db_session
        from models.quant_data import StockBasicInfo
        with db_session() as db:
            rows = db.query(StockBasicInfo.code).filter(
                StockBasicInfo.market.in_(["主板", "中小板"])
            ).order_by(StockBasicInfo.code).limit(500).all()
            codes = [r.code for r in rows]
        if len(codes) < 50:
            raise HTTPException(status_code=400, detail=f"可用股票不足: {len(codes)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取股票列表失败: {e}")

    # 4. 按需加载面板数据
    required_fields = get_required_fields(expr)
    # 确保包含 pct_chg（用于计算收益率）
    required_fields.add("pct_chg")

    try:
        panel = load_panel(codes, start_date, end_date, fields=list(required_fields))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载面板数据失败: {e}")

    if not panel:
        raise HTTPException(status_code=400, detail="面板数据为空")

    # 5. 计算因子值
    try:
        factor_panel = evaluate(expr, panel)
    except ExpressionError as e:
        raise HTTPException(status_code=400, detail=f"表达式执行错误: {e}")

    # 6. 构建收益率面板
    if "pct_chg" not in panel:
        raise HTTPException(status_code=400, detail="缺少 pct_chg 数据")
    return_panel = panel["pct_chg"] / 100  # pct_chg 是百分比

    # 7. 提取月度调仓日期，确保年化计算基于月频
    trade_dates = get_trade_dates(start_date, end_date)
    rb_dates = get_rebalance_dates(trade_dates, freq='monthly')

    # 8. 执行分层回测（月度调仓）
    result = stratified_backtest(
        factor_panel=factor_panel,
        return_panel=return_panel,
        n_groups=req.n_groups,
        rebalance_dates=rb_dates,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    result["expression"] = expr
    return result
