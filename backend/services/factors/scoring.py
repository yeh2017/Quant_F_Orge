"""
截面评分 + 向量化打分 + IC 分析
"""
import structlog
import numpy as np
import pandas as pd
from typing import Dict, List

from services.factors.utils import make_serializable, robust_zscore
from services.factors.calculator import get_factor_col_map, get_factor_labels

log = structlog.get_logger(__name__)


def cross_sectional_normalize(
    results: List[Dict],
    factor_weights: Dict[str, float],
    selected_factors: Dict[str, bool],
) -> List[Dict]:
    """双重中性化截面标准化：市值正交化 + 行业内去极值Z-Score"""
    if len(results) < 10:
        # 样本不足 10 无法稳定执行 OLS 中性化，直接跳过
        return results

    factor_names = [k for k in factor_weights if selected_factors.get(k, False)]

    # 1. 准备市值对数
    mkt_caps = np.array([r.get("market_cap", 1.0) for r in results], dtype=float)
    mkt_caps[mkt_caps <= 0] = 1.0
    log_mkt_cap = np.log(mkt_caps)

    # 2. 建立行业分组字典
    industry_groups = {}
    for i, r in enumerate(results):
        ind = r.get("industry", "未知")
        if not ind:
            ind = "未知"
        if ind not in industry_groups:
            industry_groups[ind] = []
        industry_groups[ind].append(i)

    for factor in factor_names:
        raw_vals = [r.get(factor) for r in results]  # 可能是 None / NaN / Inf / 正常float

        valid_vals = [v for v in raw_vals if v is not None and np.isfinite(v)]
        if not valid_vals:
            for r in results:
                r[factor] = 50.0
            continue

        min_val = min(valid_vals)
        clean_vals = [v if (v is not None and np.isfinite(v)) else min_val for v in raw_vals]
        clean_vals_arr = np.array(clean_vals, dtype=float)

        # Step A: 市值中性化
        try:
            if np.std(log_mkt_cap) > 1e-6 and np.std(clean_vals_arr) > 1e-6:
                X = np.vstack([log_mkt_cap, np.ones(len(log_mkt_cap))]).T
                w = np.linalg.lstsq(X, clean_vals_arr, rcond=None)[0]
                neutral_vals = clean_vals_arr - np.dot(X, w)
            else:
                neutral_vals = clean_vals_arr
        except (AttributeError, TypeError):
            raise
        except Exception:
            neutral_vals = clean_vals_arr

        # Step B: 截面 Z-Score 标准化
        mapped_scores_all = np.zeros(len(results))

        if len(neutral_vals) < 30:
            z_scores = robust_zscore(neutral_vals) if len(neutral_vals) >= 2 else np.zeros_like(neutral_vals)
            mapped_scores = 50 + z_scores * 15
            mapped_scores_all = np.clip(mapped_scores, 0, 100)
        else:
            for ind, indices in industry_groups.items():
                ind_vals = neutral_vals[indices]

                if len(ind_vals) < 2:
                    global_z = robust_zscore(neutral_vals)[indices]
                    z_scores = global_z
                else:
                    z_scores = robust_zscore(ind_vals)

                mapped_scores = 50 + z_scores * 15
                mapped_scores_all[indices] = np.clip(mapped_scores, 0, 100)

        for i, r in enumerate(results):
            r[factor] = round(float(mapped_scores_all[i]), 2)

    # 用标准化后的分数重算综合得分
    for r in results:
        factor_scores = {k: r.get(k, 50.0) for k in factor_names}
        r["composite"] = calc_composite_score(factor_scores, selected_factors, factor_weights)

    return results


def calc_composite_score(
    factor_scores: Dict[str, float],
    selected_factors: Dict[str, bool],
    factor_weights: Dict[str, float],
) -> float:
    """计算综合得分（加权平均）"""
    total_weight = 0
    weighted_sum = 0

    for factor, score in factor_scores.items():
        if score is None:
            continue
        if selected_factors.get(factor, False):
            weight = factor_weights.get(factor, 0)
            weighted_sum += score * weight
            total_weight += weight

    if total_weight > 0:
        return round(weighted_sum / total_weight, 2)
    return 0


def score_factors_vectorized(
    df: pd.DataFrame,
    selected_factors: dict,
    factor_weights: dict,
) -> list:
    """
    向量化因子打分。
    各原始因子用 rank(pct=True) → 加权求和 → MAD去极值 → Sigmoid 归一化。
    """
    if df.empty:
        return []

    scored = df[["code"]].copy()

    factor_col_map = get_factor_col_map()

    composite = np.zeros(len(df))
    total_weight = 0.0
    # 保存每个因子的归一化分数（百分位），用于输出
    factor_rank_scores = {}

    for factor_name, col_rules in factor_col_map.items():
        if not selected_factors.get(factor_name, True):
            continue
        w = factor_weights.get(factor_name, 0.1)

        sub_scores = []
        for col, lower_better in col_rules:
            if col not in df.columns:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            valid_mask = s.notna() & np.isfinite(s)
            if valid_mask.sum() < 3:
                continue
            # lower_better 因子（PE/PB/市值/波动率）：≤0 无经济含义，排除后再排名
            # 例：PE<0 表示亏损，不是"更便宜"；PB<0 表示资不抵债
            if lower_better:
                s = s.where(s > 0)
                if s.notna().sum() < 3:
                    continue
            ranked = s.rank(pct=True, na_option="bottom")
            if lower_better:
                ranked = 1 - ranked
            sub_scores.append(ranked.values)

        if sub_scores:
            factor_score = np.nanmean(np.stack(sub_scores, axis=0), axis=0)
            factor_rank_scores[factor_name] = factor_score
            composite += factor_score * w
            total_weight += w

    if total_weight == 0:
        return []

    composite = composite / total_weight

    z = robust_zscore(composite)
    z_clipped = np.clip(z, -3, 3)
    final = 1 / (1 + np.exp(-z_clipped))

    results = []
    for pos, (_, row) in enumerate(df.iterrows()):
        code = row["code"]
        entry = {
            "code": code,
            "name": row.get("name", code),
            "industry": row.get("industry", "未知") or "未知",
            "composite": float(make_serializable(final[pos])),
        }
        # 输出每个因子的归一化百分位分数（0~1），用位置索引确保与 numpy 数组对齐
        for fname in factor_col_map:
            if fname in factor_rank_scores:
                entry[fname] = round(float(factor_rank_scores[fname][pos]), 2)
            else:
                entry[fname] = 0.0
        results.append(entry)

    results.sort(key=lambda x: x["composite"], reverse=True)
    return results


def analyze_factor_ic(
    df: pd.DataFrame,
    factor_weights: dict,
    snapshots: list = None,
) -> dict:
    """
    因子绩效归因：滚动多截面 Rank IC + ICIR。

    - 有 snapshots（多截面）→ 逐期算 IC → IC_mean / IC_std / ICIR
    - 无 snapshots（fallback）→ 单截面同期 IC（兼容旧逻辑）
    """
    from scipy import stats as sp_stats

    FACTOR_LABELS = get_factor_labels()
    FACTOR_COL = get_factor_col_map()

    # ── 多截面滚动 IC ──
    if snapshots and len(snapshots) >= 3:
        # 逐期逐因子计算 IC
        ic_series = {fname: [] for fname in FACTOR_COL}

        for snap in snapshots:
            sdf = snap["df"]
            if "fwd_ret" not in sdf.columns or len(sdf) < 10:
                continue

            fwd = pd.to_numeric(sdf["fwd_ret"], errors="coerce")

            for factor_name, col_rules in FACTOR_COL.items():
                sub_vals = []
                for col, lower_better in col_rules:
                    if col not in sdf.columns:
                        continue
                    s = pd.to_numeric(sdf[col], errors="coerce")
                    ranked = s.rank(pct=True, na_option="bottom")
                    if lower_better:
                        ranked = 1 - ranked
                    sub_vals.append(ranked)

                if not sub_vals:
                    continue

                factor_score = np.nanmean(np.stack([v.values for v in sub_vals], axis=0), axis=0)
                valid = np.isfinite(factor_score) & np.isfinite(fwd.values)
                if valid.sum() < 5:
                    continue

                ic, _ = sp_stats.spearmanr(factor_score[valid], fwd.values[valid])
                if np.isfinite(ic):
                    ic_series[factor_name].append(float(ic))

        # 汇总
        results = []
        ic_ir_map = {}

        for factor_name in FACTOR_COL:
            ics = ic_series.get(factor_name, [])
            if len(ics) < 2:
                results.append({
                    "name": factor_name,
                    "label": FACTOR_LABELS.get(factor_name, factor_name),
                    "ic_mean": None, "ic_std": None, "ic_ir": None,
                    "current_weight": factor_weights.get(factor_name, 0),
                    "suggested_weight": 0, "verdict": "数据不足",
                })
                continue

            ic_mean = float(np.mean(ics))
            ic_std = float(np.std(ics))
            icir = ic_mean / ic_std if ic_std > 1e-6 else 0.0
            abs_icir = abs(icir)
            abs_ic = abs(ic_mean)

            ic_ir_map[factor_name] = max(abs_icir, 0.001)

            if abs_icir >= 0.5:
                verdict = "✅ 强有效" if ic_mean > 0 else "⚠️ 强反向"
            elif abs_icir >= 0.3:
                verdict = "✅ 有效" if ic_mean > 0 else "⚠️ 反向有效"
            elif abs_ic >= 0.02:
                verdict = "➖ 弱相关"
            else:
                verdict = "❌ 无效"

            results.append({
                "name": factor_name,
                "label": FACTOR_LABELS.get(factor_name, factor_name),
                "ic_mean": round(ic_mean, 4),
                "ic_std": round(ic_std, 4),
                "ic_ir": round(icir, 4),
                "ic_count": len(ics),
                "current_weight": round(factor_weights.get(factor_name, 0), 4),
                "suggested_weight": 0,
                "verdict": verdict,
            })

        # 推荐权重
        total_ir = sum(ic_ir_map.values())
        suggested = {k: round(v / total_ir, 4) for k, v in ic_ir_map.items()} if total_ir > 0 else {}
        for r in results:
            r["suggested_weight"] = round(suggested.get(r["name"], 0), 4)

        results.sort(key=lambda x: abs(x.get("ic_ir") or 0), reverse=True)

        return {
            "factors": results,
            "suggested_weights": suggested,
            "stock_count": len(snapshots[0]["df"]) if snapshots else 0,
            "periods": len(snapshots),
            "method": "rolling_forward_ic",
        }

    # ── Fallback：单截面同期 IC（兼容旧逻辑）──
    if df.empty or len(df) < 10:
        return {"error": "数据不足，至少需要 10 只股票"}

    if "momentum_20" not in df.columns:
        return {"error": "缺少动量数据，无法计算收益"}

    forward_ret = pd.to_numeric(df["momentum_20"], errors="coerce")

    results = []
    ic_ir_map = {}

    for factor_name, col_rules in FACTOR_COL.items():
        sub_vals = []
        for col, lower_better in col_rules:
            if col not in df.columns:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            ranked = s.rank(pct=True, na_option="bottom")
            if lower_better:
                ranked = 1 - ranked
            sub_vals.append(ranked)

        if not sub_vals:
            results.append({
                "name": factor_name, "label": FACTOR_LABELS.get(factor_name, factor_name),
                "ic_mean": None, "ic_std": None, "ic_ir": None,
                "current_weight": factor_weights.get(factor_name, 0),
                "suggested_weight": 0, "verdict": "数据不足",
            })
            continue

        factor_score = np.nanmean(np.stack([v.values for v in sub_vals], axis=0), axis=0)
        valid = np.isfinite(factor_score) & np.isfinite(forward_ret.values)

        if valid.sum() < 5:
            results.append({
                "name": factor_name, "label": FACTOR_LABELS.get(factor_name, factor_name),
                "ic_mean": None, "ic_std": None, "ic_ir": None,
                "current_weight": factor_weights.get(factor_name, 0),
                "suggested_weight": 0, "verdict": "数据不足",
            })
            continue

        ic, _ = sp_stats.spearmanr(factor_score[valid], forward_ret.values[valid])
        ic = float(ic) if np.isfinite(ic) else 0.0

        abs_ic = abs(ic)
        ic_ir_map[factor_name] = max(abs_ic, 0.001)

        if abs_ic >= 0.05:
            verdict = "✅ 有效" if ic > 0 else "⚠️ 反向有效"
        elif abs_ic >= 0.02:
            verdict = "➖ 弱相关"
        else:
            verdict = "❌ 无效"

        results.append({
            "name": factor_name,
            "label": FACTOR_LABELS.get(factor_name, factor_name),
            "ic_mean": round(ic, 4),
            "ic_std": None,
            "ic_ir": round(abs_ic, 4),
            "current_weight": round(factor_weights.get(factor_name, 0), 4),
            "suggested_weight": 0,
            "verdict": verdict,
        })

    total_ic = sum(ic_ir_map.values())
    suggested = {k: round(v / total_ic, 4) for k, v in ic_ir_map.items()} if total_ic > 0 else {}
    for r in results:
        r["suggested_weight"] = round(suggested.get(r["name"], 0), 4)

    results.sort(key=lambda x: abs(x.get("ic_mean") or 0), reverse=True)

    return {
        "factors": results,
        "suggested_weights": suggested,
        "stock_count": len(df),
        "method": "single_snapshot_ic",
    }


def compute_ic_decay() -> dict:
    """
    计算各因子在不同前瞻期（1/5/10/20/60日）的 Rank IC 衰减曲线。
    从路由层剥离的纯业务逻辑。
    """
    from scipy import stats as sp_stats
    from core.database import db_session
    from models.quant_data import StockDailyBar

    HORIZONS = [1, 5, 10, 20, 60]
    FACTOR_COL = get_factor_col_map()
    FACTOR_LABELS = get_factor_labels()

    with db_session() as db:
        dates = [r[0] for r in db.query(StockDailyBar.trade_date).distinct()
                 .order_by(StockDailyBar.trade_date.desc()).limit(120).all()]
        if len(dates) < 70:
            return {"error": "数据不足，至少需要 70 个交易日"}
        dates.sort()

        from models.quant_data import StockDailyFactor

        rows = db.query(
            StockDailyBar.code, StockDailyBar.trade_date, StockDailyBar.close,
            StockDailyBar.pct_chg, StockDailyBar.volume,
            StockDailyFactor.pe_ttm, StockDailyFactor.pb, StockDailyFactor.ps_ttm,
            StockDailyFactor.total_mv, StockDailyFactor.turnover_rate,
        ).join(
            StockDailyFactor,
            (StockDailyBar.code == StockDailyFactor.code) &
            (StockDailyBar.trade_date == StockDailyFactor.trade_date),
            isouter=True,
        ).filter(StockDailyBar.trade_date.in_(dates)).all()

        df = pd.DataFrame(rows, columns=[
            "code", "trade_date", "close",
            "pct_chg", "vol",
            "pe_ttm", "pb", "ps_ttm",
            "total_mv", "turnover_rate",
        ])
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.sort_values(["code", "trade_date"], inplace=True)

        for h in HORIZONS:
            df[f"fwd_{h}d"] = df.groupby("code")["close"].transform(
                lambda s: s.shift(-h) / s - 1
            )

        mid_date = dates[-61] if len(dates) > 61 else dates[len(dates) // 2]
        snap = df[df["trade_date"] == pd.Timestamp(mid_date)].copy()
        if len(snap) < 30:
            return {"error": "截面数据不足"}

        factor_scores = {}
        for factor_name, col_rules in FACTOR_COL.items():
            sub_vals = []
            for col, lower_better in col_rules:
                if col not in snap.columns:
                    continue
                s = pd.to_numeric(snap[col], errors="coerce")
                ranked = s.rank(pct=True, na_option="bottom")
                if lower_better:
                    ranked = 1 - ranked
                sub_vals.append(ranked.values)
            if sub_vals:
                factor_scores[factor_name] = np.nanmean(np.stack(sub_vals), axis=0)

        result = {}
        for factor_name, scores in factor_scores.items():
            ics = []
            for h in HORIZONS:
                fwd = snap[f"fwd_{h}d"].values
                valid = np.isfinite(scores) & np.isfinite(fwd)
                if valid.sum() < 10:
                    ics.append(None)
                    continue
                ic, _ = sp_stats.spearmanr(scores[valid], fwd[valid])
                ics.append(round(float(ic), 4) if np.isfinite(ic) else None)
            result[factor_name] = {
                "label": FACTOR_LABELS.get(factor_name, factor_name),
                "ics": ics,
            }

        return {
            "horizons": HORIZONS,
            "factors": result,
            "snapshot_date": mid_date,
            "stock_count": len(snap),
        }

