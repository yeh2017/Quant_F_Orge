"""
可转债独立路由
==============
端点一览:
  GET  /bonds/overview         → 全市场可转债概览统计
  GET  /bonds/factor_snapshot  → 最新双低排行（ConvertibleBondFactor 最新快照）
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from sqlalchemy import func

from core.database import db_session
from models.quant_data import ConvertibleBondFactor, ConvertibleBondBasic, ConvertibleBondBar

router = APIRouter(prefix="/bonds", tags=["Bonds"])


@router.get("/factor_snapshot")
def get_factor_snapshot(
    limit: int = Query(default=50, le=500, description="返回条数上限"),
    max_premium: Optional[float] = Query(default=None, description="转股溢价率上限(%)，如 30.0"),
    max_price: Optional[float] = Query(default=None, description="转债价格上限，如 130"),
    min_rating: Optional[str] = Query(default=None, description="最低评级，如 AA-"),
    trade_date: Optional[str] = Query(default=None, description="快照日期 YYYY-MM-DD，默认最新"),
    include_all: bool = Query(default=False, description="是否包含无双低分的债，用于全量查看"),
):
    """
    获取可转债双低排行榜（按 double_low_score 升序）。

    筛选参数:
      max_premium  转股溢价率上限（%），推荐 ≤30% 避免高溢价陷阱
      max_price    转债价格上限，推荐 ≤130 防强赎风险
      min_rating   评级下限，如 AA-
    """
    with db_session() as db:
      try:
        # 取最新快照日期
        if trade_date:
            from datetime import datetime
            latest_dt = datetime.strptime(trade_date, "%Y-%m-%d").date()
        else:
            from utils.trade_date import get_table_latest_date
            from datetime import date as _d
            _dt_str = get_table_latest_date("bond_factor")
            latest_dt = _d.fromisoformat(_dt_str) if _dt_str else None
        if not latest_dt:
            return {"trade_date": None, "count": 0, "data": []}

        # 排除已退市/到期的可转债
        listed_codes = db.query(ConvertibleBondBasic.code).filter(
            ConvertibleBondBasic.listed == True  # noqa: E712
        ).subquery()
        q = db.query(ConvertibleBondFactor).filter(
            ConvertibleBondFactor.trade_date == latest_dt,
            ConvertibleBondFactor.code.in_(db.query(listed_codes)),
        )
        if not include_all:
            q = q.filter(ConvertibleBondFactor.double_low_score.is_not(None))
        if max_premium is not None:
            q = q.filter(ConvertibleBondFactor.premium_ratio <= max_premium)
        if max_price is not None:
            q = q.filter(ConvertibleBondFactor.close_price <= max_price)

        rows = q.order_by(ConvertibleBondFactor.double_low_score.asc().nulls_last()).limit(limit).all()

        # 评级过滤（字符串比较，AA > AA- > A+ > A）
        RATING_ORDER = {"AAA": 7, "AA+": 6, "AA": 5, "AA-": 4, "A+": 3, "A": 2, "A-": 1, "BBB": 0}
        if min_rating and min_rating in RATING_ORDER:
            min_score = RATING_ORDER[min_rating]
            rows = [r for r in rows if RATING_ORDER.get(str(r.rating or ""), -1) >= min_score]

        # 批量查正股名称
        all_codes = [r.code for r in rows]
        name_map = {}
        issue_date_map = {}
        if all_codes:
            basics = db.query(
                ConvertibleBondBasic.code, ConvertibleBondBasic.underlying_name,
                ConvertibleBondBasic.issue_date,
            ).filter(ConvertibleBondBasic.code.in_(all_codes)).all()
            name_map = {b.code: b.underlying_name for b in basics if b.underlying_name}
            issue_date_map = {b.code: b.issue_date for b in basics if b.issue_date}

        # 批量查前一日收盘价 → 计算涨跌幅
        prev_date = db.query(func.max(ConvertibleBondFactor.trade_date)).filter(
            ConvertibleBondFactor.trade_date < latest_dt
        ).scalar()
        prev_map: dict[str, float] = {}
        if prev_date and all_codes:
            prev_rows = db.query(
                ConvertibleBondFactor.code, ConvertibleBondFactor.close_price
            ).filter(
                ConvertibleBondFactor.trade_date == prev_date,
                ConvertibleBondFactor.code.in_(all_codes),
            ).all()
            prev_map = {p.code: p.close_price for p in prev_rows if p.close_price}

        # 批量查正股当日涨跌幅
        from models.quant_data import StockDailyBar
        underlying_codes = list({r.underlying_code for r in rows if r.underlying_code})
        underlying_pct_map: dict[str, float] = {}
        if underlying_codes:
            ub_rows = db.query(
                StockDailyBar.code, StockDailyBar.pct_chg
            ).filter(
                StockDailyBar.trade_date == latest_dt,
                StockDailyBar.code.in_(underlying_codes),
            ).all()
            underlying_pct_map = {u.code: u.pct_chg for u in ub_rows if u.pct_chg is not None}

        # 批量查当日成交额 → 计算换手率
        from models.quant_data import ConvertibleBondBar
        turnover_map: dict[str, float] = {}
        if all_codes:
            bar_rows = db.query(
                ConvertibleBondBar.code, ConvertibleBondBar.turnover
            ).filter(
                ConvertibleBondBar.trade_date == latest_dt,
                ConvertibleBondBar.code.in_(all_codes),
            ).all()
            turnover_map = {b.code: b.turnover for b in bar_rows if b.turnover is not None}

        data = []
        for r in rows:
            uc = r.underlying_code or ""
            cur = float(getattr(r, 'close_price', None) or 0)
            pre = prev_map.get(str(r.code))
            pct = round((cur - pre) / pre * 100, 2) if pre and pre > 0 else None

            # 换手率 = 成交额(万元) × 10000 / 剩余规模(亿元) / 1e8 × 100(%)
            turnover_rate = None
            tv = turnover_map.get(r.code)
            rs = r.remaining_size
            if tv is not None and rs and rs > 0:
                turnover_rate = round(tv * 10000 / (rs * 1e8) * 100, 2)

            data.append({
                "code": r.code,
                "name": r.name,
                "close_price": r.close_price,
                "pct_chg": pct,
                "premium_ratio": r.premium_ratio,
                "double_low_score": r.double_low_score,
                "convert_value": r.convert_value,
                "remaining_size": r.remaining_size,
                "turnover_rate": turnover_rate,
                "amount": round(tv, 2) if tv is not None else None,  # 万元（cb_daily.amount 原始单位）
                "underlying_code": uc,
                "underlying_name": name_map.get(r.code, uc.split('.')[0] if uc else ""),
                "underlying_close": r.underlying_close,
                "underlying_pct_chg": round(underlying_pct_map.get(uc, 0), 2) if uc in underlying_pct_map else None,
                "underlying_roe": r.underlying_roe,
                "convert_price": r.convert_price,
                "rating": r.rating,
                "pure_bond_value": r.pure_bond_value,
                "mature_date": str(r.mature_date) if r.mature_date else None,
                "issue_date": str(issue_date_map[r.code]) if r.code in issue_date_map else None,
            })

        return {
            "trade_date": str(latest_dt),
            "count": len(data),
            "data": data,
        }
      except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview")
def get_bond_overview():
    """全市场可转债概览统计（不依赖筛选条件）。"""
    with db_session() as db:
      try:
        from utils.trade_date import get_verified_trade_date, get_table_latest_date
        from datetime import date as _d
        from statistics import median

        # 与股票/ETF 概览一致：使用 verified date 确保数据完整度
        _bar_dt_str, data_verified = get_verified_trade_date("bond")
        _factor_dt_str = get_table_latest_date("bond_factor")
        # 取两表日期的较小值，避免同步窗口期（Bar 已更新但 Factor 未完成）
        if _bar_dt_str and _factor_dt_str:
            latest_dt = min(_d.fromisoformat(_bar_dt_str), _d.fromisoformat(_factor_dt_str))
        elif _factor_dt_str:
            latest_dt = _d.fromisoformat(_factor_dt_str)
        elif _bar_dt_str:
            latest_dt = _d.fromisoformat(_bar_dt_str)
        else:
            latest_dt = None
        if not latest_dt:
            return {"trade_date": None, "total": 0, "data_verified": False}

        # 在市可分析品种总数（有双低分 + 在市）
        listed_codes = db.query(ConvertibleBondBasic.code).filter(
            ConvertibleBondBasic.listed == True  # noqa: E712
        ).subquery()
        market_total = db.query(func.count(ConvertibleBondFactor.code)).filter(
            ConvertibleBondFactor.trade_date == latest_dt,
            ConvertibleBondFactor.double_low_score.is_not(None),
            ConvertibleBondFactor.code.in_(db.query(listed_codes)),
        ).scalar() or 0

        # 有效可转债（有双低分的，且在市）
        rows = db.query(ConvertibleBondFactor).filter(
            ConvertibleBondFactor.trade_date == latest_dt,
            ConvertibleBondFactor.double_low_score.is_not(None),
            ConvertibleBondFactor.code.in_(db.query(listed_codes)),
        ).all()

        if not rows:
            return {"trade_date": str(latest_dt), "total": 0, "market_total": market_total}

        total = len(rows)
        prices = [float(r.close_price) for r in rows if r.close_price]
        premiums = [float(r.premium_ratio) for r in rows if r.premium_ratio is not None]
        median_price = round(median(prices), 3) if prices else 0
        median_premium = round(median(premiums), 2) if premiums else 0
        avg_double_low = round(sum(float(getattr(r, 'double_low_score', None) or 0) for r in rows) / total, 1)

        # 全市场成交额（从 Bar 表汇总，单位：万元 → 亿元）
        # Tushare cb_daily 的 amount 字段单位为万元（注意：与股票 daily 的千元不同）
        # Factor 和 Bar 的最新日期可能不同步，做 fallback
        total_amount_raw = db.query(func.sum(ConvertibleBondBar.turnover)).filter(
            ConvertibleBondBar.trade_date == latest_dt,
        ).scalar()
        amount_date = latest_dt
        if not total_amount_raw:
            bar_latest = db.query(func.max(ConvertibleBondBar.trade_date)).scalar()
            if bar_latest:
                total_amount_raw = db.query(func.sum(ConvertibleBondBar.turnover)).filter(
                    ConvertibleBondBar.trade_date == bar_latest,
                ).scalar() or 0
                amount_date = bar_latest
            else:
                total_amount_raw = 0
        total_amount = round(float(total_amount_raw) / 1e4, 2)  # 万元 → 亿元（cb_daily.amount 单位为万元，非千元）
        low_count = sum(1 for r in rows if (r.double_low_score or 999) < 130)
        safe_count = sum(1 for r in rows if (r.close_price or 999) < 110)
        redeem_risk = sum(1 for r in rows if r.convert_value and r.convert_value >= 130)
        revision_chance = sum(1 for r in rows if r.convert_value and r.convert_value <= 80)

        # 评级分布
        rating_dist: dict[str, int] = {}
        for r in rows:
            rt = str(r.rating or "未评级")
            rating_dist[rt] = rating_dist.get(rt, 0) + 1

        # 涨跌统计（基于前一日对比）
        prev_date = db.query(func.max(ConvertibleBondFactor.trade_date)).filter(
            ConvertibleBondFactor.trade_date < latest_dt
        ).scalar()
        up_count = down_count = flat_count = 0
        pct_list = []
        if prev_date:
            prev_rows = db.query(
                ConvertibleBondFactor.code, ConvertibleBondFactor.close_price
            ).filter(
                ConvertibleBondFactor.trade_date == prev_date,
                ConvertibleBondFactor.code.in_(db.query(listed_codes)),
            ).all()
            prev_map = {p.code: float(p.close_price) for p in prev_rows if p.close_price}
            for r in rows:
                cur = float(getattr(r, 'close_price', None) or 0)
                pre = prev_map.get(r.code)
                if pre and pre > 0 and cur > 0:
                    pct = (cur - pre) / pre * 100
                    pct_list.append(pct)
                    if pct > 0.01:
                        up_count += 1
                    elif pct < -0.01:
                        down_count += 1
                    else:
                        flat_count += 1
        avg_pct = round(sum(pct_list) / len(pct_list), 2) if pct_list else 0

        return {
            "trade_date": str(latest_dt),
            "data_verified": data_verified,
            "market_total": market_total,
            "total": total,
            "median_price": median_price,
            "median_premium": median_premium,
            "avg_double_low": avg_double_low,
            "low_count": low_count,
            "safe_count": safe_count,
            "redeem_risk_count": redeem_risk,
            "revision_chance_count": revision_chance,
            "rating_dist": rating_dist,
            "total_amount": total_amount,
            "amount_date": str(amount_date),
            "up": up_count,
            "down": down_count,
            "flat": flat_count,
            "avg_pct": avg_pct,
        }
      except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
