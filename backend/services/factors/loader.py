"""
批量数据加载
============
一次 SQL 批量拉取所有股票的截面因子原始数据。
比逐只循环快 10-20 倍。
"""
import structlog
import numpy as np
import pandas as pd
from typing import List
from collections import defaultdict

log = structlog.get_logger(__name__)

from settings import TRADING_DAYS


def load_factor_df(codes: List[str], start_date: str, end_date: str) -> pd.DataFrame:
    """
    批量拉取因子数据，返回宽表 DataFrame。

    列: code, pe_ttm, pb, turnover_rate, momentum_20, volatility_20,
        roe, revenue_growth, net_profit_growth, holder_change_rate, industry
    """
    # 信任边界：外部传入的 codes 可能无后缀，统一规范化为 DB 格式
    from utils.asset_type import to_ts_code
    codes = [to_ts_code(c) for c in codes]
    try:
        from core.database import db_session
        from models.quant_data import StockDailyFactor, StockDailyBar, StockFinancial
        from sqlalchemy import and_, func

        records = {}
        with db_session() as db:
            # ── 1. 估值因子（StockDailyFactor 最新截面）──
            subq = (
                db.query(
                    StockDailyFactor.code,
                    func.max(StockDailyFactor.trade_date).label("max_date"),
                )
                .filter(
                    StockDailyFactor.code.in_(codes),
                    StockDailyFactor.trade_date >= start_date,
                    StockDailyFactor.trade_date <= end_date,
                )
                .group_by(StockDailyFactor.code)
                .subquery()
            )
            factor_rows = (
                db.query(StockDailyFactor)
                .join(subq, and_(
                    StockDailyFactor.code == subq.c.code,
                    StockDailyFactor.trade_date == subq.c.max_date,
                ))
                .all()
            )
            for r in factor_rows:
                records.setdefault(r.code, {})
                records[r.code].update({
                    "pe_ttm": r.pe_ttm,
                    "pb": r.pb,
                    "turnover_rate": r.turnover_rate,
                    "total_mv": r.total_mv,
                    "circ_mv": r.circ_mv,
                    "dv_ttm": r.dv_ttm,
                })

            # ── 2. 动量 + 波动（StockDailyBar 批量，取最近 20 日）──
            bar_subq = (
                db.query(
                    StockDailyBar.code,
                    StockDailyBar.trade_date,
                    StockDailyBar.close,
                )
                .filter(
                    StockDailyBar.code.in_(codes),
                    StockDailyBar.trade_date >= start_date,
                    StockDailyBar.trade_date <= end_date,
                )
                .order_by(StockDailyBar.code, StockDailyBar.trade_date.desc())
                .all()
            )
            bar_map = defaultdict(list)
            for row in bar_subq:
                if row.close is not None:
                    bar_map[row.code].append(float(row.close))

            for code, closes in bar_map.items():
                if len(closes) >= 2:
                    closes_arr = np.array(closes[:20])
                    if len(closes_arr) >= 2:
                        rev = closes_arr[::-1]
                        returns_20 = np.diff(rev) / np.where(rev[:-1] != 0, rev[:-1], np.nan)
                        returns_20 = returns_20[~np.isnan(returns_20)]
                        records.setdefault(code, {})
                        records[code]["momentum_20"] = float(closes_arr[0] / closes_arr[-1] - 1) \
                            if closes_arr[-1] != 0 else 0.0
                        # reversal = 近期收益取反（A 股短期反转效应）
                        records[code]["reversal_20"] = -records[code]["momentum_20"]
                        vol_std = float(np.std(returns_20)) if len(returns_20) > 1 else 0.0
                        records[code]["volatility_20"] = vol_std * np.sqrt(TRADING_DAYS)

            # ── 3. 财务因子（StockFinancial 最新季报）──
            fin_subq = (
                db.query(
                    StockFinancial.code,
                    func.max(StockFinancial.report_date).label("max_date"),
                )
                .filter(StockFinancial.code.in_(codes))
                .group_by(StockFinancial.code)
                .subquery()
            )
            fin_rows = (
                db.query(StockFinancial)
                .join(fin_subq, and_(
                    StockFinancial.code == fin_subq.c.code,
                    StockFinancial.report_date == fin_subq.c.max_date,
                ))
                .all()
            )
            for r in fin_rows:
                records.setdefault(r.code, {})
                records[r.code].update({
                    "roe": r.roe,
                    "gross_profit_margin": r.gross_profit_margin,
                    "cashflow_oper": r.cashflow_oper if hasattr(r, "cashflow_oper") else None,
                    "debt_to_assets": r.debt_to_assets if hasattr(r, "debt_to_assets") else None,
                    "eps": r.eps if hasattr(r, "eps") else None,
                    "revenue_growth": r.revenue_yoy if hasattr(r, "revenue_yoy") else None,
                    "net_profit_growth": r.net_profit_yoy if hasattr(r, "net_profit_yoy") else None,
                })

            # ── 4. 筹码集中度（StockShareholderCount 最近两期变化率）──
            from models.quant_data import StockShareholderCount
            sh_rows = (
                db.query(
                    StockShareholderCount.code,
                    StockShareholderCount.end_date,
                    StockShareholderCount.holder_num,
                    StockShareholderCount.holder_num_change_rate,
                )
                .filter(StockShareholderCount.code.in_(codes))
                .order_by(StockShareholderCount.code, StockShareholderCount.end_date.desc())
                .all()
            )
            seen_codes = set()
            for r in sh_rows:
                if r.code in seen_codes:
                    continue
                seen_codes.add(r.code)
                records.setdefault(r.code, {})
                records[r.code]["holder_change_rate"] = (
                    float(r.holder_num_change_rate) if r.holder_num_change_rate is not None else None
                )

            # ── 5. 融资融券 → margin_ratio ──
            from models.quant_data import StockMarginData
            margin_subq = (
                db.query(
                    StockMarginData.code,
                    func.max(StockMarginData.trade_date).label("max_date"),
                )
                .filter(StockMarginData.code.in_(codes))
                .group_by(StockMarginData.code)
                .subquery()
            )
            margin_rows = (
                db.query(StockMarginData)
                .join(margin_subq, and_(
                    StockMarginData.code == margin_subq.c.code,
                    StockMarginData.trade_date == margin_subq.c.max_date,
                ))
                .all()
            )
            for r in margin_rows:
                records.setdefault(r.code, {})
                # circ_mv（流通市值）优先，fallback 到 total_mv（总市值）
                circ_mv = records[r.code].get("circ_mv") or records[r.code].get("total_mv")
                if r.rzye and circ_mv and circ_mv > 0:
                    records[r.code]["margin_ratio"] = r.rzye / (circ_mv * 10000)
                else:
                    records[r.code]["margin_ratio"] = None

            # ── 6. 行业归属 + 名称（StockBasicInfo）──
            from models.quant_data import StockBasicInfo as SBI
            ind_rows = (
                db.query(SBI.code, SBI.industry, SBI.name)
                .filter(SBI.code.in_(codes))
                .all()
            )
            for r in ind_rows:
                records.setdefault(r.code, {})
                if r.industry:
                    records[r.code]["industry"] = r.industry
                if r.name:
                    records[r.code]["name"] = r.name

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame.from_dict(records, orient="index")
        df.index.name = "code"
        df = df.reset_index()
        return df

    except Exception as e:
        log.warning(f"[FactorLoader] load_factor_df error: {e}")
        return pd.DataFrame()


def load_monthly_snapshots(
    codes: list[str],
    start_date: str,
    end_date: str,
    periods: int = 12,
) -> list[dict]:
    """
    按月末截面批量拉取因子数据 + forward return，用于滚动 IC 分析。

    返回 [{period_date, df(code, factor_cols..., fwd_ret)}] × N期
    """
    # 信任边界：外部传入的 codes 可能无后缀，统一规范化为 DB 格式
    from utils.asset_type import to_ts_code
    codes = [to_ts_code(c) for c in codes]
    try:
        from core.database import db_session
        from models.quant_data import StockDailyBar, StockDailyFactor, StockFinancial
        from sqlalchemy import and_, func

        with db_session() as db:
            # ── 1. 获取月末日期列表（全局交易日，不依赖单只股票）──
            all_dates = [
                r[0] for r in db.query(StockDailyBar.trade_date)
                .filter(
                    StockDailyBar.trade_date >= start_date,
                    StockDailyBar.trade_date <= end_date,
                )
                .order_by(StockDailyBar.trade_date)
                .distinct()
                .all()
            ]
            if len(all_dates) < 40:
                return []

            # 取每月最后一个交易日
            from collections import defaultdict
            month_map = defaultdict(str)
            for d in all_dates:
                ym = str(d)[:7]  # "2025-03"
                month_map[ym] = str(d)  # 不断更新，最终保留月末

            month_ends = sorted(month_map.values())[-periods - 1:]  # 多取1个用于 fwd_ret
            if len(month_ends) < 3:
                return []

            # ── 2. 批量拉取所有月末截面的收盘价 ──
            price_rows = (
                db.query(StockDailyBar.code, StockDailyBar.trade_date, StockDailyBar.close)
                .filter(
                    StockDailyBar.code.in_(codes),
                    StockDailyBar.trade_date.in_(month_ends),
                    StockDailyBar.close.isnot(None),
                )
                .all()
            )
            # {(code, date): close}
            price_map = {(r.code, str(r.trade_date)): float(r.close) for r in price_rows}

            # ── 3. 批量拉取估值因子（最近截面） ──
            factor_subq = (
                db.query(
                    StockDailyFactor.code,
                    func.max(StockDailyFactor.trade_date).label("max_date"),
                )
                .filter(
                    StockDailyFactor.code.in_(codes),
                    StockDailyFactor.trade_date >= start_date,
                    StockDailyFactor.trade_date <= end_date,
                )
                .group_by(StockDailyFactor.code)
                .subquery()
            )
            factor_rows = (
                db.query(StockDailyFactor)
                .join(factor_subq, and_(
                    StockDailyFactor.code == factor_subq.c.code,
                    StockDailyFactor.trade_date == factor_subq.c.max_date,
                ))
                .all()
            )
            factor_map = {}
            for r in factor_rows:
                factor_map[r.code] = {
                    "pe_ttm": r.pe_ttm, "pb": r.pb,
                    "turnover_rate": r.turnover_rate, "total_mv": r.total_mv,
                    "circ_mv": r.circ_mv, "dv_ttm": r.dv_ttm,
                }

            # ── 4. 批量拉取财务因子 ──
            fin_subq = (
                db.query(
                    StockFinancial.code,
                    func.max(StockFinancial.report_date).label("max_date"),
                )
                .filter(StockFinancial.code.in_(codes))
                .group_by(StockFinancial.code)
                .subquery()
            )
            fin_rows = (
                db.query(StockFinancial)
                .join(fin_subq, and_(
                    StockFinancial.code == fin_subq.c.code,
                    StockFinancial.report_date == fin_subq.c.max_date,
                ))
                .all()
            )
            fin_map = {}
            for r in fin_rows:
                fin_map[r.code] = {
                    "roe": r.roe,
                    "gross_profit_margin": r.gross_profit_margin,
                    "cashflow_oper": r.cashflow_oper if hasattr(r, "cashflow_oper") else None,
                    "debt_to_assets": r.debt_to_assets if hasattr(r, "debt_to_assets") else None,
                    "eps": r.eps if hasattr(r, "eps") else None,
                    "revenue_growth": r.revenue_yoy if hasattr(r, "revenue_yoy") else None,
                    "net_profit_growth": r.net_profit_yoy if hasattr(r, "net_profit_yoy") else None,
                }

            # ── 4b. 融资融券 → margin_ratio ──
            from models.quant_data import StockMarginData
            margin_subq = (
                db.query(
                    StockMarginData.code,
                    func.max(StockMarginData.trade_date).label("max_date"),
                )
                .filter(StockMarginData.code.in_(codes))
                .group_by(StockMarginData.code)
                .subquery()
            )
            margin_rows = (
                db.query(StockMarginData)
                .join(margin_subq, and_(
                    StockMarginData.code == margin_subq.c.code,
                    StockMarginData.trade_date == margin_subq.c.max_date,
                ))
                .all()
            )
            for r in margin_rows:
                # circ_mv（流通市值）优先，fallback 到 total_mv
                circ_mv = factor_map.get(r.code, {}).get("circ_mv") or factor_map.get(r.code, {}).get("total_mv")
                if r.rzye and circ_mv and circ_mv > 0:
                    fin_map.setdefault(r.code, {})["margin_ratio"] = r.rzye / (circ_mv * 10000)

            # ── 5. 批量拉取 20日动量/波动率 ──
            bar_rows = (
                db.query(StockDailyBar.code, StockDailyBar.trade_date, StockDailyBar.close)
                .filter(
                    StockDailyBar.code.in_(codes),
                    StockDailyBar.trade_date >= start_date,
                    StockDailyBar.trade_date <= end_date,
                )
                .order_by(StockDailyBar.code, StockDailyBar.trade_date.desc())
                .all()
            )
            bar_map = defaultdict(list)
            for row in bar_rows:
                if row.close is not None:
                    bar_map[row.code].append(float(row.close))

            momentum_map = {}
            volatility_map = {}
            for code, closes in bar_map.items():
                if len(closes) >= 2:
                    closes_arr = np.array(closes[:20])
                    if len(closes_arr) >= 2:
                        momentum_map[code] = float(closes_arr[0] / closes_arr[-1] - 1) if closes_arr[-1] != 0 else 0.0
                        rev = closes_arr[::-1]
                        returns_20 = np.diff(rev) / np.where(rev[:-1] != 0, rev[:-1], np.nan)
                        returns_20 = returns_20[~np.isnan(returns_20)]
                        volatility_map[code] = float(np.std(returns_20) * np.sqrt(TRADING_DAYS)) if len(returns_20) > 1 else 0.0

        # ── 6. 组装每期截面 ──
        snapshots = []
        for i in range(len(month_ends) - 1):
            t_date = month_ends[i]
            t1_date = month_ends[i + 1]

            records = []
            for code in codes:
                p0 = price_map.get((code, t_date))
                p1 = price_map.get((code, t1_date))
                if p0 is None or p1 is None or p0 <= 0:
                    continue

                fwd_ret = (p1 - p0) / p0

                entry = {"code": code, "fwd_ret": fwd_ret}
                # 合并因子数据
                entry.update(factor_map.get(code, {}))
                entry.update(fin_map.get(code, {}))
                entry["momentum_20"] = momentum_map.get(code, 0.0)
                entry["reversal_20"] = -momentum_map.get(code, 0.0)
                entry["volatility_20"] = volatility_map.get(code, 0.0)
                records.append(entry)

            if len(records) >= 10:
                snapshots.append({
                    "period_date": t_date,
                    "df": pd.DataFrame(records),
                })

        log.info("monthly_snapshots_loaded", periods=len(snapshots),
                 codes=len(codes), date_range=f"{month_ends[0]}~{month_ends[-1]}")
        return snapshots

    except Exception as e:
        log.warning(f"[FactorLoader] load_monthly_snapshots error: {e}")
        return []

