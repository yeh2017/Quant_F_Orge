"""
组合优化服务
============
基于 Markowitz 现代投资组合理论实现多种组合优化方法。

支持方法:
  max_sharpe    — 最大夏普比率（scipy 求解器）
  risk_parity   — 风险平价（各资产风险贡献相等）
  min_variance  — 最小方差（二次规划）
  equal_weight  — 等权配置（基准对比）

所需数据: 各股最近 N 天历史收益率（从本地 StockDailyBar 读取）
"""

import numpy as np
import pandas as pd
import structlog
from typing import List, Dict, Optional

log = structlog.get_logger(__name__)

from settings import TRADING_DAYS, RF_ANNUAL


class PortfolioService:
    """组合优化服务"""

    def optimize(
        self,
        codes: List[str],
        method: str = "max_sharpe",
        lookback_days: int = TRADING_DAYS,
        expected_returns_override: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """主入口：计算单种方法的组合最优权重。"""
        prep = self._prepare(codes, lookback_days, expected_returns_override)
        if "error" in prep:
            return prep
        return self._build_result(prep, method)

    def optimize_all(
        self,
        codes: List[str],
        lookback_days: int = TRADING_DAYS,
        expected_returns_override: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """一次加载数据，计算全部 4 种优化方法。"""
        prep = self._prepare(codes, lookback_days, expected_returns_override)
        if "error" in prep:
            return prep
        methods = ["max_sharpe", "risk_parity", "min_variance", "equal_weight"]
        results = {}
        for m in methods:
            try:
                results[m] = self._build_result(prep, m)
            except Exception as e:
                results[m] = {"error": str(e), "method": m}
        return {"results": results}

    def _prepare(
        self,
        codes: List[str],
        lookback_days: int,
        expected_returns_override: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """公共数据加载 + 协方差计算（只做一次）。"""
        if not codes:
            return {"error": "请先添加股票到自选池"}
        returns_df = self._load_returns(codes, lookback_days)
        valid_codes = list(returns_df.columns) if not returns_df.empty else []
        n = len(valid_codes)
        if n == 0:
            return {"error": "未找到有效历史数据，请先同步行情数据"}
        actual_data_points = len(returns_df)
        mu = self._expected_returns(returns_df, expected_returns_override)
        sigma = self._cov_matrix(returns_df)
        individual_stds = np.sqrt(np.diag(sigma))
        return {"valid_codes": valid_codes, "n": n, "mu": mu, "sigma": sigma,
                "individual_stds": individual_stds, "lookback_days": lookback_days,
                "actual_data_points": actual_data_points}

    def _build_result(self, prep: Dict, method: str) -> Dict:
        """用预计算数据 + 优化方法生成结果。"""
        valid_codes, n = prep["valid_codes"], prep["n"]
        mu, sigma = prep["mu"], prep["sigma"]
        individual_stds = prep["individual_stds"]

        if n < 2:
            method = "equal_weight"
        weights = self._optimize(mu, sigma, method, n)

        port_return = float(np.dot(weights, mu))
        port_risk = float(np.sqrt(np.dot(weights, np.dot(sigma, weights))))
        rf_daily = RF_ANNUAL / TRADING_DAYS
        sharpe = (port_return - rf_daily * TRADING_DAYS) / (port_risk * np.sqrt(TRADING_DAYS) + 1e-9)

        weighted_avg_vol = float(np.dot(weights, individual_stds))
        diversification = weighted_avg_vol / (port_risk + 1e-9)

        holdings = []
        for i, code in enumerate(valid_codes):
            holdings.append({
                "code": code, "name": code,
                "weight": float(weights[i]),
                "expectedReturn": float(mu[i] * TRADING_DAYS),
                "risk": float(individual_stds[i] * np.sqrt(TRADING_DAYS)),
                "raw_metrics": {},
            })
        holdings.sort(key=lambda h: h["weight"], reverse=True)

        return {
            "method": method, "codes": valid_codes,
            "expectedReturn": float(port_return * TRADING_DAYS),
            "portfolioRisk": float(port_risk * np.sqrt(TRADING_DAYS)),
            "sharpeRatio": float(sharpe),
            "diversification": float(diversification),
            "holdings": holdings,
            "lookback_days": prep["lookback_days"],
            "actual_data_points": prep.get("actual_data_points", 0),
        }

    # ── 数据加载 ──────────────────────────────────────────────────────────

    def _load_returns(self, codes: List[str], lookback_days: int) -> pd.DataFrame:
        """从本地日线表批量读取最近 N 天收益率（自动路由 Stock/ETF/可转债）"""
        try:
            from core.database import db_session
            from utils.bar_query import get_bar_model, to_db_code
            from sqlalchemy import desc

            with db_session() as db:
                all_data = {}
                for code in codes:
                    BarModel = get_bar_model(code)
                    db_code = to_db_code(code)
                    rows = (db.query(BarModel.trade_date, BarModel.close)
                            .filter(BarModel.code == db_code)
                            .order_by(desc(BarModel.trade_date))
                            .limit(lookback_days + 1)
                            .all())
                    if len(rows) >= 10:
                        closes = np.array([r.close for r in reversed(rows)], dtype=float)
                        returns = np.diff(closes) / closes[:-1]
                        clean_code = code.split('.')[0]
                        all_data[clean_code] = returns

            if not all_data:
                return pd.DataFrame()

            # 对齐长度（取最短）
            min_len = min(len(v) for v in all_data.values())
            df = pd.DataFrame({k: v[-min_len:] for k, v in all_data.items()})
            return df.dropna(axis=1, how="any")

        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.error("portfolio_load_returns_failed", error=str(e))
            return pd.DataFrame()

    # ── 统计量 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _expected_returns(
        returns_df: pd.DataFrame,
        override: Optional[Dict[str, float]] = None,
    ) -> np.ndarray:
        """
        历史均值收益率（日频）。
        若提供 override（如因子评分），则用线性混合替换。
        """
        mu = returns_df.mean().values  # 日均收益率
        if override:
            for i, code in enumerate(returns_df.columns):
                if code in override:
                    # 将因子评分（0~1）映射到 ±3%/年 的调整量
                    adj = (override[code] - 0.5) * 0.06 / TRADING_DAYS
                    mu[i] = mu[i] * 0.7 + adj * 0.3
        return mu

    @staticmethod
    def _cov_matrix(returns_df: pd.DataFrame) -> np.ndarray:
        """
        协方差矩阵（Ledoit-Wolf 压缩，提高稳定性）。
        若 sklearn 不可用则用样本协方差降级。
        """
        try:
            from sklearn.covariance import LedoitWolf
            lw = LedoitWolf()
            lw.fit(returns_df.values)
            return lw.covariance_
        except ImportError:
            return returns_df.cov().values

    # ── 优化方法 ──────────────────────────────────────────────────────────

    def _optimize(
        self, mu: np.ndarray, sigma: np.ndarray,
        method: str, n: int
    ) -> np.ndarray:
        """分发到各优化方法"""
        if method == "max_sharpe":
            return self._max_sharpe(mu, sigma, n)
        elif method == "risk_parity":
            return self._risk_parity(sigma, n)
        elif method == "min_variance":
            return self._min_variance(sigma, n)
        else:  # equal_weight
            return np.ones(n) / n

    def _max_sharpe(self, mu: np.ndarray, sigma: np.ndarray, n: int) -> np.ndarray:
        """最大夏普比 — scipy minimize + SLSQP"""
        try:
            from scipy.optimize import minimize

            rf = RF_ANNUAL / TRADING_DAYS

            def neg_sharpe(w):
                port_r = np.dot(w, mu)
                port_v = np.sqrt(np.dot(w, np.dot(sigma, w)))
                return -(port_r - rf) / (port_v + 1e-9)

            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
            bounds = [(0.01, 0.30)] * n  # 单只 1%~30%
            w0 = np.ones(n) / n

            result = minimize(neg_sharpe, w0, method="SLSQP",
                              bounds=bounds, constraints=constraints,
                              options={"maxiter": 500, "ftol": 1e-9})
            if result.success:
                w = np.maximum(result.x, 0)
                return w / w.sum()
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("max_sharpe_failed", error=str(e))
        return np.ones(n) / n

    def _risk_parity(self, sigma: np.ndarray, n: int) -> np.ndarray:
        """风险平价 — 迭代使各资产边际风险贡献相等"""
        try:
            from scipy.optimize import minimize

            def risk_contrib_diff(w):
                port_var = np.dot(w, np.dot(sigma, w))
                mrc = np.dot(sigma, w)           # 边际风险贡献
                rc = w * mrc / (np.sqrt(port_var) + 1e-9)  # 风险贡献
                target = np.full(n, 1.0 / n)
                return np.sum((rc - target) ** 2)

            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
            bounds = [(0.005, 0.5)] * n
            w0 = np.ones(n) / n

            result = minimize(risk_contrib_diff, w0, method="SLSQP",
                              bounds=bounds, constraints=constraints,
                              options={"maxiter": 1000, "ftol": 1e-12})
            if result.success:
                w = np.maximum(result.x, 0)
                return w / w.sum()
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("risk_parity_failed", error=str(e))
        return np.ones(n) / n

    def _min_variance(self, sigma: np.ndarray, n: int) -> np.ndarray:
        """最小方差 — 二次规划"""
        try:
            from scipy.optimize import minimize

            def port_variance(w):
                return np.dot(w, np.dot(sigma, w))

            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
            bounds = [(0.01, 0.30)] * n
            w0 = np.ones(n) / n

            result = minimize(port_variance, w0, method="SLSQP",
                              bounds=bounds, constraints=constraints,
                              options={"maxiter": 500})
            if result.success:
                w = np.maximum(result.x, 0)
                return w / w.sum()
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("min_variance_failed", error=str(e))
        return np.ones(n) / n
    # ── 再平衡模拟 ────────────────────────────────────────────────────────

    def rebalance_simulation(
        self,
        codes: List[str],
        method: str = "max_sharpe",
        period: str = "monthly",
        lookback_days: int = TRADING_DAYS,
        commission_rate: float = 0.001,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict:
        """模拟定期再平衡，返回净值序列和统计指标"""
        from core.database import db_session
        from utils.bar_query import get_bar_model, to_db_code

        if not codes or len(codes) < 2:
            return {"error": "至少需要 2 只股票"}

        with db_session() as db:
            price_dict = {}
            for code in codes:
                BarModel = get_bar_model(code)
                db_code = to_db_code(code)

                q = (db.query(BarModel.trade_date, BarModel.close)
                     .filter(BarModel.code == db_code))
                if start_date:
                    from datetime import datetime, timedelta
                    pre_start = (datetime.strptime(start_date, "%Y-%m-%d")
                                 - timedelta(days=int(lookback_days * 1.5))).strftime("%Y-%m-%d")
                    q = q.filter(BarModel.trade_date >= pre_start)
                if end_date:
                    q = q.filter(BarModel.trade_date <= end_date)
                rows = q.order_by(BarModel.trade_date).all()

                if len(rows) >= 60:
                    clean = code.split('.')[0]
                    price_dict[clean] = pd.Series(
                        [r.close for r in rows],
                        index=pd.to_datetime([r.trade_date for r in rows])
                    )

        if len(price_dict) < 2:
            return {"error": "有效股票不足2只"}

        price_df = pd.DataFrame(price_dict).dropna()
        if start_date:
            price_df = price_df[price_df.index >= start_date]
        if end_date:
            price_df = price_df[price_df.index <= end_date]

        if len(price_df) < 60:
            return {"error": "日期范围内数据不足"}

        returns_df = price_df.pct_change().dropna()
        dates = returns_df.index
        n = len(returns_df.columns)

        # 确定再平衡日期
        rebalance_indices = [0]
        for i in range(1, len(dates)):
            if period == "quarterly":
                if dates[i].month != dates[i - 1].month and dates[i].month in [1, 4, 7, 10]:
                    rebalance_indices.append(i)
            else:
                if dates[i].month != dates[i - 1].month:
                    rebalance_indices.append(i)

        # 模拟
        current_weights = np.ones(n) / n
        net_value = 1.0
        benchmark_nv = 1.0
        eq_weights = np.ones(n) / n

        net_values = []
        benchmark_values = []
        turnovers = []
        rebalance_dates_out = []
        total_cost = 0.0

        for i in range(len(returns_df)):
            day_ret = returns_df.iloc[i].values

            if i in rebalance_indices:
                lookback_end = i
                lookback_start = max(0, i - lookback_days)
                hist = returns_df.iloc[lookback_start:lookback_end]

                if len(hist) >= 30:
                    try:
                        mu = hist.mean().values
                        sigma = self._cov_matrix(hist)
                        new_weights = self._optimize(mu, sigma, method, n)
                    except Exception:
                        new_weights = current_weights
                else:
                    new_weights = np.ones(n) / n

                turnover = float(np.sum(np.abs(new_weights - current_weights)) / 2)
                turnovers.append(round(turnover * 100, 2))
                rebalance_dates_out.append(str(dates[i].date()))

                cost = turnover * commission_rate * 2
                total_cost += cost
                net_value *= (1 - cost)
                current_weights = new_weights

            port_ret = np.dot(current_weights, day_ret)
            net_value *= (1 + port_ret)
            net_values.append(round(net_value, 6))

            eq_ret = np.dot(eq_weights, day_ret)
            benchmark_nv *= (1 + eq_ret)
            benchmark_values.append(round(benchmark_nv, 6))

            drifted = current_weights * (1 + day_ret)
            current_weights = drifted / drifted.sum()

        return {
            "net_values": net_values,
            "benchmark": benchmark_values,
            "dates": [str(d.date()) for d in dates],
            "rebalance_dates": rebalance_dates_out,
            "turnovers": turnovers,
            "total_cost": round(total_cost * 100, 4),
            "rebalance_count": len(rebalance_dates_out),
            "method": method,
            "period": period,
        }

