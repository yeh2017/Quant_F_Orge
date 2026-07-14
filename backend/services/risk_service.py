"""
风险分析服务
============
提供组合风险指标计算，独立于回测引擎，可接收任意收益率序列。

指标清单:
  VaR(95%, 99%)   — 历史法（分位数）
  CVaR            — 尾部期望损失
  Beta / Alpha    — 对沪深300线性回归（252日）
  Max Drawdown    — 最大回撤
  Drawdown Periods— Top3 回撤区间分解
  Tracking Error  — 超额收益标准差（年化）
  Calmar Ratio    — 年化收益 / 最大回撤
  Sortino Ratio   — 下行风险夏普
  Volatility      — 年化波动率
"""

import numpy as np
import structlog
from typing import List, Dict, Optional, Tuple

log = structlog.get_logger(__name__)

from settings import TRADING_DAYS, RF_ANNUAL


class RiskService:
    """组合风险分析服务"""

    # ── 公开入口 ──────────────────────────────────────────────────────────

    def analyze(
        self,
        portfolio_returns: List[float],
        benchmark_returns: Optional[List[float]] = None,
        net_values: Optional[List[float]] = None,
        dates: Optional[List[str]] = None,
        confidence: float = 0.95,
    ) -> Dict:
        """
        全量风险分析。

        Args:
            portfolio_returns: 每日收益率序列（小数，如 0.01 = 1%）
            benchmark_returns: 基准（沪深300）每日收益率，可选
            net_values: 组合净值序列，若为 None 则从 portfolio_returns 累乘重建
            dates: 日期序列（str），用于回撤区间标注
            confidence: VaR 置信度，默认 0.95

        Returns:
            dict 包含所有风险指标
        """
        r = np.array(portfolio_returns, dtype=float)
        r = r[~np.isnan(r)]  # 去 NaN

        if len(r) < 10:
            return {"error": "数据不足，需要至少 10 个交易日的收益率序列"}

        # 重建净值
        if net_values is None or len(net_values) != len(r):
            nv = np.cumprod(1 + r)
        else:
            nv = np.array(net_values, dtype=float)

        result = {}

        # ── 波动率 ──
        result["volatility"] = float(np.std(r) * np.sqrt(TRADING_DAYS) * 100)

        # ── VaR / CVaR ──
        result["var_95"] = float(self._var(r, 0.95) * 100)
        result["var_99"] = float(self._var(r, 0.99) * 100)
        result["cvar_95"] = float(self._cvar(r, 0.95) * 100)
        result["cvar_99"] = float(self._cvar(r, 0.99) * 100)

        # ── 最大回撤 ──
        max_dd, dd_start, dd_end = self._max_drawdown(nv, dates)
        result["max_drawdown"] = float(max_dd * 100)
        result["max_drawdown_start"] = dd_start
        result["max_drawdown_end"] = dd_end

        # ── 回撤分解（Top3 区间）──
        result["drawdown_periods"] = self._drawdown_periods(nv, dates, top_n=3)

        # ── 年化收益 ──
        total_return = float(nv[-1] / nv[0] - 1) if len(nv) > 1 else 0.0
        n_years = len(r) / TRADING_DAYS
        annual_return = float((1 + total_return) ** (1 / max(n_years, 0.01)) - 1) * 100
        result["annual_return"] = annual_return

        # ── Calmar Ratio ──
        calmar = annual_return / max(abs(result["max_drawdown"]), 1e-9)
        result["calmar_ratio"] = float(calmar)

        # ── Sortino Ratio ──
        downside = r[r < 0]
        downside_std = float(np.std(downside) * np.sqrt(TRADING_DAYS)) if len(downside) > 1 else 1e-9
        mean_r = float(np.mean(r) * TRADING_DAYS)
        result["sortino_ratio"] = float(mean_r / downside_std) if downside_std > 0 else 0.0

        # ── Beta / Alpha / Tracking Error（需要基准）──
        if benchmark_returns is not None and len(benchmark_returns) >= len(r):
            b = np.array(benchmark_returns[:len(r)], dtype=float)
            b = b[~np.isnan(b)]
            min_len = min(len(r), len(b))
            rp, rb = r[-min_len:], b[-min_len:]

            result["beta"] = float(self._beta(rp, rb))
            result["alpha"] = float(self._alpha(rp, rb, result["beta"]) * 100)
            te = float(np.std(rp - rb) * np.sqrt(TRADING_DAYS) * 100)
            result["tracking_error"] = te
            result["information_ratio"] = float(
                (np.mean(rp - rb) * TRADING_DAYS * 100) / te if te > 0 else 0.0
            )
        else:
            result["beta"] = None
            result["alpha"] = None
            result["tracking_error"] = None
            result["information_ratio"] = None

        # ── Sharpe Ratio ──
        rf = RF_ANNUAL / TRADING_DAYS  # 无风险日收益
        excess = r - rf
        sharpe_denom = np.std(excess) * np.sqrt(TRADING_DAYS)
        result["sharpe_ratio"] = float(
            np.mean(excess) * TRADING_DAYS / sharpe_denom if sharpe_denom > 0 else 0.0
        )

        log.info("risk_analysis_done", metrics=list(result.keys()))
        return result

    def get_benchmark_returns(self, start_date: str, end_date: str) -> List[float]:
        """
        获取沪深300基准日收益率序列。
        降级链：本地 EtfDailyBar(510300.SH) → Tushare index_daily → AkShare
        """
        # ── 优先：本地 ETF 日线（510300.SH = 沪深300ETF）──
        try:
            from core.database import db_session
            from models.quant_data import EtfDailyBar
            from sqlalchemy import and_

            with db_session() as db:
                rows = (db.query(EtfDailyBar.trade_date, EtfDailyBar.close)
                        .filter(and_(
                            EtfDailyBar.code == "510300.SH",
                            EtfDailyBar.trade_date >= start_date,
                            EtfDailyBar.trade_date <= end_date,
                        ))
                        .order_by(EtfDailyBar.trade_date.asc())
                        .all())
                if rows:
                    closes = np.array([r.close for r in rows], dtype=float)
                    returns = np.diff(closes) / closes[:-1]
                    log.info("benchmark_local_ok", source="EtfDailyBar:510300.SH", points=len(returns))
                    return returns.tolist()
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("benchmark_local_failed", error=str(e))


        # ── 降级1：Tushare Pro index_daily（稳定，3000积分即可）──
        try:
            from dotenv import load_dotenv
            import os, tushare as ts
            load_dotenv()
            pro = ts.pro_api(os.getenv("TUSHARE_TOKEN", ""))
            s = start_date.replace("-", "")
            e = end_date.replace("-", "")
            df = pro.index_daily(ts_code="000300.SH", start_date=s, end_date=e,
                                 fields="trade_date,close")
            if df is not None and not df.empty:
                df = df.sort_values("trade_date")
                closes = df["close"].values.astype(float)
                returns = np.diff(closes) / closes[:-1]
                log.info("benchmark_tushare_ok", points=len(returns))
                return returns.tolist()
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("benchmark_tushare_failed", error=str(e))

        # ── 降级2：AkShare（网络不稳定时可能断开）──
        try:
            import akshare as ak
            df = ak.index_zh_a_hist(symbol="000300", period="daily",
                                    start_date=start_date.replace("-", ""),
                                    end_date=end_date.replace("-", ""))
            if df is not None and not df.empty:
                closes = df["收盘"].values.astype(float)
                returns = np.diff(closes) / closes[:-1]
                return returns.tolist()
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("benchmark_akshare_failed", error=str(e))

        return []


    # ── 私有计算方法 ──────────────────────────────────────────────────────

    @staticmethod
    def _var(returns: np.ndarray, confidence: float) -> float:
        """历史法 VaR（正数，代表亏损额）"""
        return float(-np.percentile(returns, (1 - confidence) * 100))

    @staticmethod
    def _cvar(returns: np.ndarray, confidence: float) -> float:
        """历史法 CVaR（尾部期望损失，正数）"""
        threshold = np.percentile(returns, (1 - confidence) * 100)
        tail = returns[returns <= threshold]
        return float(-np.mean(tail)) if len(tail) > 0 else 0.0

    @staticmethod
    def _max_drawdown(
        net_values: np.ndarray,
        dates: Optional[List[str]] = None
    ) -> Tuple[float, Optional[str], Optional[str]]:
        """最大回撤及发生区间"""
        peak = np.maximum.accumulate(net_values)
        drawdown = (net_values - peak) / peak
        max_dd = float(-np.min(drawdown))
        if max_dd < 1e-9:
            # 无回撤（净值单调上升或全等）
            return 0.0, None, None
        idx_end = int(np.argmin(drawdown))
        idx_start = int(np.argmax(net_values[:idx_end + 1])) if idx_end > 0 else 0
        start_date = dates[idx_start] if dates and idx_start < len(dates) else None
        end_date = dates[idx_end] if dates and idx_end < len(dates) else None
        return max_dd, start_date, end_date

    @staticmethod
    def _drawdown_periods(
        net_values: np.ndarray,
        dates: Optional[List[str]] = None,
        top_n: int = 3,
    ) -> List[Dict]:
        """
        识别 Top N 回撤区间（从高点到低点）
        """
        nv = np.array(net_values, dtype=float)
        peak = np.maximum.accumulate(nv)
        dd = (nv - peak) / peak  # 负值

        in_drawdown = False
        periods = []
        start_i = 0

        for i in range(len(nv)):
            if not in_drawdown and dd[i] < 0:
                in_drawdown = True
                start_i = i
            elif in_drawdown and dd[i] >= -1e-9:
                # 回撤结束
                trough_i = start_i + int(np.argmin(dd[start_i:i + 1]))
                magnitude = float(-dd[trough_i])
                periods.append({
                    "start": dates[start_i] if dates else str(start_i),
                    "trough": dates[trough_i] if dates else str(trough_i),
                    "end": dates[i] if dates else str(i),
                    "drawdown": round(magnitude * 100, 2),  # 百分比
                    "duration_days": i - start_i,
                })
                in_drawdown = False

        # 如果还在回撤中
        if in_drawdown and start_i < len(nv):
            trough_i = start_i + int(np.argmin(dd[start_i:]))
            magnitude = float(-dd[trough_i])
            periods.append({
                "start": dates[start_i] if dates else str(start_i),
                "trough": dates[trough_i] if dates else str(trough_i),
                "end": None,
                "drawdown": round(magnitude * 100, 2),
                "duration_days": len(nv) - start_i,
            })

        # 按回撤幅度排序，取 Top N
        periods.sort(key=lambda x: x["drawdown"], reverse=True)
        return periods[:top_n]

    @staticmethod
    def _beta(portfolio_r: np.ndarray, benchmark_r: np.ndarray) -> float:
        """投资组合对基准的 Beta 系数（ddof=1 无偏估计）"""
        cov = np.cov(portfolio_r, benchmark_r)  # ddof=1
        var_b = cov[1, 1]  # 与 cov[0,1] 同源，确保 ddof 一致
        return float(cov[0, 1] / var_b) if var_b > 0 else 1.0

    @staticmethod
    def _alpha(portfolio_r: np.ndarray, benchmark_r: np.ndarray, beta: float) -> float:
        """Jensen's Alpha（日频，需年化则 × TRADING_DAYS）"""
        rf_daily = RF_ANNUAL / TRADING_DAYS
        alpha_daily = np.mean(portfolio_r) - rf_daily - beta * (np.mean(benchmark_r) - rf_daily)
        return float(alpha_daily * TRADING_DAYS)  # 年化
