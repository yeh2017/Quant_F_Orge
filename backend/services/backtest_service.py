import structlog
log = structlog.get_logger(__name__)
"""回测服务（三层架构调度器）: 信号层 → 仓位层 → 模拟层"""
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta
from collections import OrderedDict

import pandas as pd
import numpy as np

from services.stock_service import StockService
from services.factor_service import FactorService
from services.strategies import get_strategy
from services.strategies.position_manager import PositionManager
from services.strategies.engine import BacktestEngine

from utils.asset_type import classify as classify_asset, TYPE_LABELS as ASSET_TYPE_LABELS

class BacktestService:

    """回测服务"""

    def __init__(self, stock_service: StockService = None):
        self.stock_service = stock_service or StockService()
        self.factor_service = FactorService(self.stock_service)

    # 策略 → 允许的标的类型校验
    _STRATEGY_ASSET_RULES = {
        "multifactor": {"stock"},
        "event_driven": {"stock"},
        "double_low_cb": {"bond"},
        "etf_momentum": {"etf"},
    }

    def run_backtest(

        self,
        stock_codes: List[str] = None,
        strategy_type: str = "multifactor",
        start_date: str = None,
        end_date: str = None,
        initial_cash: float = 1000000,
        commission: float = 0.0003,
        selected_factors: Dict[str, bool] = None,
        rebalance_period: str = "monthly",
        strategy_params: Dict[str, Any] = None,
        universe_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        from utils.trade_date import get_table_date_range
        # ── 日期确定：以 DB 实际数据范围为准 ──
        # 按策略资产类型选表（ETF→etf, 可转债→bond_bar, 其余→bars）
        _table = {"etf_momentum": "etf", "double_low_cb": "bond_bar"}.get(strategy_type, "bars")
        db_range = get_table_date_range(_table)
        if not db_range:
            raise ValueError("数据库无行情数据，请先同步数据")
        db_min, db_max = db_range
        if not end_date:
            end_date = db_max
        elif end_date > db_max:
            log.info("end_date_clamped", requested=end_date, actual=db_max)
            end_date = db_max
        if not start_date:
            start_date = max(db_min, (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d"))
        elif start_date < db_min:
            log.info("start_date_clamped", requested=start_date, actual=db_min)
            start_date = db_min
        if start_date > end_date:
            raise ValueError(f"起始日期 {start_date} 晚于结束日期 {end_date}，请调整日期范围")
        actual_start_date = start_date
        actual_end_date = end_date
        # 动态标的池：预算各调仓日 codes 并集
        per_date_codes = None
        if universe_config:
            from services.universe_provider import create_provider
            provider = create_provider(universe_config)
            rebal_period = (strategy_params or {}).get("rebalance", rebalance_period)
            max_stocks = universe_config.get("max_stocks", 500)
            truncate_by = universe_config.get("truncate_by", "total_mv")
            stock_codes, per_date_codes = self._resolve_universe(
                provider, start_date, end_date, rebal_period, max_stocks, truncate_by
            )
        if not stock_codes:
            raise ValueError("未指定标的：请传入 codes 或 universe_config")
        # 标的类型校验：有限制的策略自动过滤不匹配代码
        allowed = self._STRATEGY_ASSET_RULES.get(strategy_type)
        if allowed:
            good = [c for c in stock_codes if classify_asset(c) in allowed]
            bad = [c for c in stock_codes if classify_asset(c) not in allowed]
            if bad:
                allowed_cn = "/".join(ASSET_TYPE_LABELS.get(t, t) for t in allowed)
                log.info(f"[BacktestService] {strategy_type} 自动过滤 {len(bad)} 个不匹配标的，"
                         f"保留 {len(good)} 个{allowed_cn}")
            if not good:
                allowed_cn = "/".join(ASSET_TYPE_LABELS.get(t, t) for t in allowed)
                raise ValueError(f"{strategy_type} 策略仅支持{allowed_cn}标的，"
                                 f"自选池中无匹配代码")
            stock_codes = good
        result = self._run_vectorized_backtest(
            stock_codes, strategy_type, start_date, end_date,
            initial_cash, commission, selected_factors, rebalance_period,
            strategy_params or {}, per_date_codes=per_date_codes,
        )
        # 注入实际日期范围，供前端对比展示
        result["actual_start_date"] = actual_start_date
        result["actual_end_date"] = actual_end_date
        return result

    # ================================================================

    # 三层向量化回测（信号层 → 仓位层 → 模拟层）

    # ================================================================

    def _run_vectorized_backtest(

        self,
        stock_codes: List[str],
        strategy_type: str,
        start_date: str,
        end_date: str,
        initial_cash: float,
        commission: float,
        selected_factors: Dict[str, bool],
        rebalance_period: str = "monthly",
        strategy_params: Dict[str, Any] = None,
        per_date_codes: Dict[str, List[str]] = None,
    ) -> Dict[str, Any]:
        if strategy_params is None:
            strategy_params = {}
        strategy = get_strategy(strategy_type)
        if not strategy:
            raise ValueError(f"未知策略: {strategy_type}")
        # 策略可按参数动态覆盖因子选择（如 multifactor 的"纯估值"模式）
        if hasattr(strategy, 'get_factor_override'):
            override = strategy.get_factor_override(strategy_params or {})
            if override:
                selected_factors = override
        # 从策略参数中提取调仓周期和持仓数量
        rebalance_period = strategy_params.get("rebalance", rebalance_period)
        top_n_param = strategy_params.get("top_n")
        # ── Step 1: 加载价格矩阵 ──
        price_df = self._load_price_matrix(stock_codes, start_date, end_date)
        if price_df.empty or price_df.shape[1] < 1:
            raise ValueError("数据不足")
        valid_codes = list(price_df.columns)
        dates = list(price_df.index.astype(str))
        T = len(dates)
        if T < 5:
            raise ValueError(f"有效交易日不足: {T}")
        price_arr = price_df.values.astype(float)
        ret_arr = np.diff(price_arr, axis=0) / price_arr[:-1]
        ret_arr = np.nan_to_num(ret_arr, nan=0.0, posinf=0.0, neginf=0.0)
        n = len(valid_codes)
        # ── 加载可交易状态矩阵（停牌/涨跌停过滤）──
        can_buy, can_sell = self._load_tradeable_mask(
            stock_codes, start_date, end_date, valid_codes, dates
        )
        topN = top_n_param if top_n_param else max(1, min(5, n))
        max_single_weight = strategy_params.get("max_single_weight")  # None=不限
        # ── Step 2: 信号层 ── 策略生成信号矩阵
        is_signal = strategy.is_signal_based
        signal_matrix = None
        if is_signal:
            # 加载成交量（仅当策略需要时）
            vol_arr = None
            if getattr(strategy, 'needs_volume', False):
                vol_df = self._load_volume_matrix(stock_codes, start_date, end_date, valid_codes, dates)
                if vol_df is not None:
                    vol_arr = vol_df.values.astype(float)
            # 事件驱动策略：预构建事件矩阵注入 params
            if getattr(strategy, 'needs_event', False):
                from services.news.event_backtest import extract_event_signals
                events = extract_event_signals(
                    event_type=strategy_params.get("event_type"),
                    min_score=strategy_params.get("min_score", 0.3),
                    codes_filter=valid_codes,
                    start_date=start_date, end_date=end_date,
                )
                code_idx = {c: i for i, c in enumerate(valid_codes)}
                date_idx = {d: i for i, d in enumerate(dates)}
                # 非交易日事件映射到下一个交易日
                import bisect
                sorted_dates = sorted(dates)
                def _nearest_trade_date(d_str):
                    di = date_idx.get(d_str)
                    if di is not None:
                        return di
                    # 二分查找下一个交易日
                    pos = bisect.bisect_left(sorted_dates, d_str)
                    if pos < len(sorted_dates):
                        return date_idx[sorted_dates[pos]]
                    return None
                event_matrix = np.zeros((T, n))
                for ev in events:
                    di = _nearest_trade_date(ev["pub_date"].isoformat())
                    ci = code_idx.get(ev["code"])
                    if di is not None and ci is not None:
                        event_matrix[di, ci] = ev["score"]
                strategy_params["_event_matrix"] = event_matrix
            signal_matrix = strategy.generate_signals(price_arr, strategy_params, volume=vol_arr)
            strategy_params.pop("_event_matrix", None)  # 清除，防止 JSON 序列化失败
        # 因子策略：按调仓日计算因子评分（带缓存）
        _factor_cache: Dict[str, Dict[str, float]] = {}

        def _get_factor_scores_at(as_of_date: str) -> Dict[str, float]:

            if as_of_date in _factor_cache:
                return _factor_cache[as_of_date]
            try:
                scores = self.factor_service.calculate_factor_scores_fast(
                    valid_codes, start_date, as_of_date, selected_factors
                )
                result = {s["code"]: float(s.get("composite", 0.5)) for s in scores}
            except Exception as e:
                log.warning(f"[BacktestService] 因子评分失败(as_of={as_of_date}): {e}")
                result = {}
            _factor_cache[as_of_date] = result
            return result
        # ── Step 3: 仓位层 + 模拟循环 ──
        pos_mgr = PositionManager(commission=commission)
        rebal_indices = self._get_rebal_indices(dates, rebalance_period)
        rebal_set = set(rebal_indices)
        # 动态标的池：将预算的 per_date_codes 重映射到 price_df 的实际调仓日
        if per_date_codes is not None:
            pre_keys = sorted(per_date_codes.keys())  # 预算阶段的调仓日
            remapped = {}
            for idx in rebal_indices:
                actual_date = dates[idx]
                # 找预算中 <= actual_date 的最近 key
                best_key = None
                for pk in pre_keys:
                    if pk <= actual_date:
                        best_key = pk
                    else:
                        break
                if best_key:
                    remapped[actual_date] = per_date_codes[best_key]
            per_date_codes = remapped
        portfolio_rets = np.zeros(T - 1)
        current_weights = np.zeros(n)
        trade_markers: Dict[str, list] = {c: [] for c in valid_codes}
        entry_prices: Dict[str, float] = {}
        holding = np.zeros(n, dtype=bool)
        holdings_snapshots: list = []
        for i in range(T - 1):
            need_update = False
            weights = current_weights.copy()
            if is_signal and signal_matrix is not None:
                # 停牌/涨跌停过滤：不可买的清除买入信号，不可卖的清除卖出信号
                filtered_signals = signal_matrix[i].copy()
                filtered_signals[(filtered_signals > 0) & ~can_buy[i]] = 0
                filtered_signals[(filtered_signals < 0) & ~can_sell[i]] = 0
                # 动态标的池：不在当期池内的标的禁止买入
                if per_date_codes is not None:
                    active_set = set()
                    for prev_d in sorted(per_date_codes.keys(), reverse=True):
                        if prev_d <= dates[i]:
                            active_set = set(per_date_codes[prev_d])
                            break
                    for idx in range(n):
                        if valid_codes[idx] not in active_set and filtered_signals[idx] > 0:
                            filtered_signals[idx] = 0  # 清除买入信号，保留卖出信号
                w, changed = pos_mgr.signals_to_weights_daily(
                    filtered_signals, holding,
                    allow_reentry=getattr(strategy, 'allow_reentry', False),
                )
                if changed and w is not None:
                    weights = w
                    need_update = True
            elif i in rebal_set:
                if strategy.needs_factor:
                    factor_scores = _get_factor_scores_at(dates[i])
                elif hasattr(strategy, 'compute_factor_scores'):
                    factor_scores = strategy.compute_factor_scores(
                        valid_codes, price_arr[:i + 1], dates[:i + 1], strategy_params
                    )
                else:
                    factor_scores = {}
                weights = pos_mgr.factor_to_weights(
                    valid_codes, factor_scores, topN, strategy_type,
                    as_of_date=dates[i],
                    max_single_weight=max_single_weight,
                )
                # 因子策略：不可买入的标的权重清零
                weights[~can_buy[i]] = 0
                # 动态标的池：不在当期池内的标的权重清零
                if per_date_codes is not None:
                    active_set = set(per_date_codes.get(dates[i], []))
                    if not active_set:
                        # 找最近的调仓日 codes
                        for prev_d in sorted(per_date_codes.keys(), reverse=True):
                            if prev_d <= dates[i]:
                                active_set = set(per_date_codes[prev_d])
                                break
                    for idx in range(n):
                        if valid_codes[idx] not in active_set:
                            weights[idx] = 0
                if weights.sum() > 0:
                    weights = weights / weights.sum()  # 重新归一化
                need_update = True
            if need_update:
                day_ret = ret_arr[i] if i < len(ret_arr) else np.zeros(n)
                weights = pos_mgr.apply_limits(weights, current_weights, day_ret)
                # 跌停卖不掉：恢复原有权重
                for idx in range(n):
                    if weights[idx] == 0 and current_weights[idx] > 0 and not can_sell[i][idx]:
                        weights[idx] = current_weights[idx]
                # 恢复后重新归一化（防止总权重 > 1）
                if weights.sum() > 0:
                    weights = weights / weights.sum()
                portfolio_rets[i] -= pos_mgr.calc_cost(current_weights, weights)
                prev_top = set(np.where(current_weights > 0)[0])
                new_top = set(np.where(weights > 0)[0])
                reason_buy = "信号买入" if is_signal else f"因子 Top{topN}"
                reason_sell = "信号卖出" if is_signal else f"调出 Top{topN}"
                # 信号策略：生成具体决策依据
                reason_ctx = {}
                if is_signal and signal_matrix is not None:
                    reason_ctx = self._build_signal_context(
                        strategy_type, strategy_params, price_arr, i, signal_matrix
                    )
                # 完全清仓（退出组合）
                for idx in prev_top - new_top:
                    code = valid_codes[idx]
                    raw_price = price_arr[i, idx]
                    sell_price = float(raw_price) if not np.isnan(raw_price) else 0.0
                    buy_price = entry_prices.pop(code, sell_price)
                    pnl = round((sell_price / buy_price - 1) * 100, 1) if buy_price > 0 else 0.0
                    trade_markers[code].append({
                        "time": dates[i], "type": "sell",
                        "price": sell_price, "weight": 0.0,
                        "reason": reason_sell, "pnl": pnl,
                        "ctx": reason_ctx.get(idx, "") if is_signal else "",
                    })
                # 新建仓（进入组合）
                for idx in new_top - prev_top:
                    code = valid_codes[idx]
                    raw_price = price_arr[i, idx]
                    buy_price = float(raw_price) if not np.isnan(raw_price) else 0.0
                    entry_prices[code] = buy_price
                    trade_markers[code].append({
                        "time": dates[i], "type": "buy",
                        "price": buy_price,
                        "weight": round(float(weights[idx]) * 100, 1),
                        "reason": reason_buy, "pnl": None,
                        "ctx": reason_ctx.get(idx, "") if is_signal else "",
                    })
                # 权重变化（加仓/减仓，标的未退出组合）
                for idx in prev_top & new_top:
                    old_w = current_weights[idx]
                    new_w = weights[idx]
                    delta = abs(new_w - old_w)
                    if delta < 0.005:
                        continue  # 权重变化 < 0.5% 忽略
                    code = valid_codes[idx]
                    raw_price = price_arr[i, idx]
                    price = float(raw_price) if not np.isnan(raw_price) else 0.0
                    if new_w > old_w:
                        trade_markers[code].append({
                            "time": dates[i], "type": "buy",
                            "price": price,
                            "weight": round(float(new_w) * 100, 1),
                            "reason": "加仓", "pnl": None,
                            "ctx": reason_ctx.get(idx, "") if is_signal else "",
                        })
                    else:
                        bp = entry_prices.get(code, price)
                        pnl = round((price / bp - 1) * 100, 1) if bp > 0 else 0.0
                        trade_markers[code].append({
                            "time": dates[i], "type": "sell",
                            "price": price,
                            "weight": round(float(new_w) * 100, 1),
                            "reason": "减仓", "pnl": pnl,
                            "ctx": reason_ctx.get(idx, "") if is_signal else "",
                        })
                current_weights = weights
                # 记录持仓快照（仅在权重变更时记录）
                top_holdings = [
                    {"code": valid_codes[j], "weight": round(float(weights[j]) * 100, 1)}
                    for j in range(n) if weights[j] > 0.001
                ]
                if top_holdings:
                    holdings_snapshots.append({"date": dates[i], "holdings": top_holdings})
            portfolio_rets[i] += float(np.dot(current_weights, ret_arr[i]))
        # 注入股票名称到持仓快照
        if holdings_snapshots:
            name_map = self._get_stock_names(valid_codes)
            for snap in holdings_snapshots:
                for h in snap["holdings"]:
                    h["name"] = name_map.get(h["code"], h["code"].split('.')[0])
        # ── Step 4: 模拟层 ── 绩效计算
        engine = BacktestEngine()
        bench_daily = self._get_benchmark_returns(start_date, end_date, T - 1)
        result = engine.calc_performance(
            portfolio_rets, initial_cash, rebal_indices, T,
            bench_daily, trade_markers, dates,
        )
        result.dates = dates[1:]  # 与 cumReturns 对齐（去掉初始日）
        result.holdings = holdings_snapshots
        rd = result.to_dict()
        rd["strategy_params"] = strategy_params
        rd["strategy_type"] = strategy_type
        return rd

    _price_cache: OrderedDict = OrderedDict()
    _PRICE_CACHE_MAX = 50

    def _get_stock_names(self, codes: List[str]) -> Dict[str, str]:
        """批量查询资产名称映射 {code: name}，覆盖股票/ETF/可转债"""
        from utils.name_resolver import resolve_names
        return resolve_names(codes)

    def _load_price_matrix(
        self, codes: List[str], start_date: str, end_date: str
    ) -> "pd.DataFrame":
        """一次 SQL 取全部股票前复权收盘价，返回 DataFrame（LRU 缓存）"""
        cache_key = (frozenset(codes), start_date, end_date)
        if cache_key in self._price_cache:
            self._price_cache.move_to_end(cache_key)  # LRU：命中移到末尾
            return self._price_cache[cache_key]
        while len(self._price_cache) >= self._PRICE_CACHE_MAX:
            self._price_cache.popitem(last=False)  # 淘汰最旧
        from core.database import db_session
        from models.quant_data import StockDailyBar, EtfDailyBar, ConvertibleBondBar
        from utils.bar_query import classify_codes
        # 分批查询辅助（SQLite IN 子句限制 999 变量，表达式树深度限制 1000）
        BATCH_SIZE = 900

        def _query_bars_batched(db, model, columns, code_list, start, end):
            """分批 IN 查询，绕过 SQLite 限制"""
            result = []
            for i in range(0, len(code_list), BATCH_SIZE):
                batch = code_list[i: i + BATCH_SIZE]
                rows = (
                    db.query(*columns)
                    .filter(
                        model.code.in_(batch),
                        model.trade_date >= start,
                        model.trade_date <= end,
                        model.close.isnot(None),
                    )
                    .order_by(model.trade_date.asc())
                    .all()
                )
                result.extend(rows)
            return result

        with db_session() as db:
            stock_codes, etf_codes, bond_codes = classify_codes(codes)
            all_rows = []
            # 股票：有 adj_factor
            if stock_codes:
                rows = _query_bars_batched(
                    db, StockDailyBar,
                    [StockDailyBar.code, StockDailyBar.trade_date,
                     StockDailyBar.close, StockDailyBar.adj_factor],
                    stock_codes, start_date, end_date,
                )
                all_rows.extend(rows)
            # ETF：有 pre_close
            if etf_codes:
                rows = _query_bars_batched(
                    db, EtfDailyBar,
                    [EtfDailyBar.code, EtfDailyBar.trade_date,
                     EtfDailyBar.close, EtfDailyBar.pre_close],
                    etf_codes, start_date, end_date,
                )
                all_rows.extend(rows)
            # 可转债：无复权因子
            if bond_codes:
                rows = _query_bars_batched(
                    db, ConvertibleBondBar,
                    [ConvertibleBondBar.code, ConvertibleBondBar.trade_date,
                     ConvertibleBondBar.close],
                    bond_codes, start_date, end_date,
                )
                all_rows.extend([(r[0], r[1], r[2], None) for r in rows])
        if not all_rows:
            return pd.DataFrame()
        df = pd.DataFrame(all_rows, columns=["code", "trade_date", "close", "adj_or_pre"])
        df["trade_date"] = df["trade_date"].astype(str)
        # 前复权处理：按 code 分组
        etf_code_set = set(etf_codes)  # 用 classify_codes 的结果判断
        adjusted_rows = []
        for code, grp in df.groupby("code"):
            grp = grp.sort_values("trade_date").reset_index(drop=True)
            adj_col = grp["adj_or_pre"]
            has_adj = adj_col.notna().sum() > 0
            if has_adj and code not in etf_code_set:
                # 股票：adj_factor 直接可用（递增型）
                adj = adj_col.ffill().fillna(1.0)
                factor = adj / adj.iloc[-1]  # 前复权
            elif has_adj:
                # ETF：adj_or_pre 实际是 pre_close，需推算
                adj = pd.Series(1.0, index=grp.index)
                for i in range(1, len(grp)):
                    prev_c = grp.loc[grp.index[i - 1], 'close']
                    cur_pre = adj_col.iloc[i]
                    if prev_c and cur_pre and cur_pre > 0:
                        adj.iloc[i] = adj.iloc[i - 1] * (prev_c / cur_pre)
                    else:
                        adj.iloc[i] = adj.iloc[i - 1]
                factor = adj / adj.iloc[-1]  # 前复权
            else:
                factor = pd.Series(1.0, index=grp.index)
            grp["close"] = (grp["close"] * factor).round(4)
            adjusted_rows.append(grp[["code", "trade_date", "close"]])
        df = pd.concat(adjusted_rows, ignore_index=True)
        price_df = df.pivot(index="trade_date", columns="code", values="close")
        price_df = price_df.ffill(limit=5).dropna(axis=1, thresh=int(len(price_df) * 0.7))
        self._price_cache[cache_key] = price_df
        return price_df

    def _resolve_universe(
        self, provider, start_date: str, end_date: str, rebalance_period: str,
        max_stocks: int = 500, truncate_by: str = "total_mv",
    ) -> Tuple[List[str], Dict[str, List[str]]]:
        """预算各调仓日的标的池，取并集。

        Args:
            max_stocks: 最大标的数上限（由用户在前端设定）
            truncate_by: 截断排序字段 (total_mv / pe_ttm / dv_ratio)

        Returns:
            (all_codes, per_date_codes): 并集 codes + 每个调仓日的独立 codes
        """
        from core.database import db_session
        from models.quant_data import StockDailyBar
        from sqlalchemy import func

        # 获取回测区间内的交易日列表
        with db_session() as db:
            rows = (
                db.query(StockDailyBar.trade_date)
                .filter(
                    StockDailyBar.trade_date >= start_date,
                    StockDailyBar.trade_date <= end_date,
                )
                .distinct()
                .order_by(StockDailyBar.trade_date.asc())
                .all()
            )
            dates = [str(r[0]) for r in rows]

        if not dates:
            return [], {}

        rebal_indices = self._get_rebal_indices(dates, rebalance_period)
        rebal_dates = [dates[i] for i in rebal_indices]

        # 每个调仓日获取 codes
        per_date_codes = {}
        all_codes_set = set()
        for d in rebal_dates:
            codes = provider.get_codes(d)
            per_date_codes[d] = codes
            all_codes_set.update(codes)

        all_codes = sorted(all_codes_set)

        # 用户设定的上限：按市值降序截断，大市值优先保留
        if len(all_codes) > max_stocks:
            log.warning(
                "universe_truncated",
                original=len(all_codes),
                limit=max_stocks,
            )
            # 从 DB 查排序因子
            try:
                from core.database import db_session
                from models.quant_data import StockDailyFactor
                from sqlalchemy import func
                sort_col_name = truncate_by if truncate_by in ("total_mv", "pe_ttm", "dv_ratio") else "total_mv"
                sort_col = getattr(StockDailyFactor, sort_col_name, StockDailyFactor.total_mv)
                BATCH = 900  # SQLite IN 子句上限
                with db_session() as db:
                    latest_date = (
                        db.query(func.max(StockDailyFactor.trade_date))
                        .filter(StockDailyFactor.trade_date <= end_date)
                        .scalar()
                    )
                    val_map = {}
                    if latest_date:
                        for i in range(0, len(all_codes), BATCH):
                            batch = all_codes[i:i + BATCH]
                            q = (
                                db.query(StockDailyFactor.code, sort_col)
                                .filter(
                                    StockDailyFactor.trade_date == latest_date,
                                    StockDailyFactor.code.in_(batch),
                                    sort_col.isnot(None),
                                )
                            )
                            # PE 排序时过滤负值（亏损股不应排最前）
                            if sort_col_name == "pe_ttm":
                                q = q.filter(sort_col > 0)
                            val_map.update({r[0]: float(r[1]) for r in q.all()})
                # pe_ttm 越小越好（升序），其他越大越好（降序）
                is_asc = sort_col_name == "pe_ttm"
                default_val = float('inf') if is_asc else 0
                all_codes.sort(key=lambda c: val_map.get(c, default_val), reverse=not is_asc)
                log.info("universe_sort", by=sort_col_name, ascending=is_asc)
            except Exception as e:
                log.warning("sort_fallback", error=str(e))
                # 排序失败保持原序
            all_codes = all_codes[:max_stocks]
            # 同步截断每个调仓日的 codes
            allowed = set(all_codes)
            per_date_codes = {
                d: [c for c in codes if c in allowed]
                for d, codes in per_date_codes.items()
            }

        log.info(
            "universe_resolved",
            rebal_dates=len(rebal_dates),
            union_size=len(all_codes),
            sample_sizes=[len(per_date_codes[d]) for d in rebal_dates[:3]],
        )
        return all_codes, per_date_codes

    def _load_tradeable_mask(
        self, codes: List[str], start_date: str, end_date: str,
        valid_codes: List[str], dates: List[str],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """生成可交易状态矩阵，用于过滤不可执行的交易信号。

        停牌: volume == 0 或该日无数据 → 不可买也不可卖
        涨停: pct_chg >= 阈值 → 不可买入（已封板买不到）
        跌停: pct_chg <= -阈值 → 不可卖出（已封板卖不掉）

        阈值: 创业板(30)/科创板(68) = 20%, 其余 = 10%
              可转债不设涨跌停限制（规则不同且较宽松）
              ETF 不设涨跌停限制

        Returns:
            (can_buy, can_sell): 两个 (T, N) 布尔矩阵
        """
        from core.database import db_session
        from models.quant_data import StockDailyBar
        from utils.bar_query import classify_codes

        T, N = len(dates), len(valid_codes)
        # 默认可交易
        can_buy = np.ones((T, N), dtype=bool)
        can_sell = np.ones((T, N), dtype=bool)

        # 预计算每只标的的涨跌停阈值
        limit_up_thresholds = np.full(N, 0.095)    # 默认 9.5%（留余量）
        limit_down_thresholds = np.full(N, -0.095)
        code_to_idx = {c: i for i, c in enumerate(valid_codes)}

        stock_codes_db, etf_codes_db, bond_codes_db = classify_codes(codes)
        # 标记 ETF / 可转债：不做涨跌停限制
        etf_set = set(etf_codes_db)
        bond_set = set(bond_codes_db)

        for code, idx in code_to_idx.items():
            pure = code.split('.')[0]
            if code in etf_set or code in bond_set:
                # ETF/可转债不设涨跌停限制
                limit_up_thresholds[idx] = 999.0
                limit_down_thresholds[idx] = -999.0
            elif pure[:2] in ('30', '68'):
                # 创业板/科创板 20%
                limit_up_thresholds[idx] = 0.195
                limit_down_thresholds[idx] = -0.195

        # 加载真实 pct_chg 和 volume（仅股票，ETF/可转债不做停牌判断）
        date_to_tidx = {d: t for t, d in enumerate(dates)}

        BATCH_SIZE = 900
        with db_session() as db:
            if stock_codes_db:
                rows = []
                for i in range(0, len(stock_codes_db), BATCH_SIZE):
                    batch = stock_codes_db[i: i + BATCH_SIZE]
                    batch_rows = (
                        db.query(
                            StockDailyBar.code,
                            StockDailyBar.trade_date,
                            StockDailyBar.pct_chg,
                            StockDailyBar.volume,
                        )
                        .filter(
                            StockDailyBar.code.in_(batch),
                            StockDailyBar.trade_date >= start_date,
                            StockDailyBar.trade_date <= end_date,
                        )
                        .all()
                    )
                    rows.extend(batch_rows)

                # 先标记所有股票交易日为"无数据"（停牌），再逐行恢复
                for code in stock_codes_db:
                    idx = code_to_idx.get(code)
                    if idx is not None:
                        can_buy[:, idx] = False
                        can_sell[:, idx] = False

                for code, trade_date, pct_chg, volume in rows:
                    idx = code_to_idx.get(code)
                    td = str(trade_date)
                    tidx = date_to_tidx.get(td)
                    if idx is None or tidx is None:
                        continue

                    vol = float(volume or 0)
                    pct = float(pct_chg or 0) / 100.0  # DB 存的是百分比

                    if vol <= 0:
                        # 停牌（有记录但无成交）
                        continue  # 保持 False

                    # 有成交量 → 可交易，但需检查涨跌停
                    can_buy[tidx, idx] = pct < limit_up_thresholds[idx]
                    can_sell[tidx, idx] = pct > limit_down_thresholds[idx]

        log.info(
            "tradeable_mask_loaded",
            total_cells=T * N,
            suspended=int((~can_buy & ~can_sell).sum()),
            limit_up_blocked=int((~can_buy & can_sell).sum()),
            limit_down_blocked=int((can_buy & ~can_sell).sum()),
        )
        return can_buy, can_sell


    def _load_volume_matrix(
        self, codes: List[str], start_date: str, end_date: str,
        valid_codes: List[str], dates: List[str],
    ) -> "pd.DataFrame | None":
        """加载成交量矩阵，与价格矩阵对齐（仅在策略需要量数据时调用）"""
        from core.database import db_session
        from models.quant_data import StockDailyBar, EtfDailyBar, ConvertibleBondBar
        from utils.bar_query import classify_codes
        BATCH_SIZE = 900
        with db_session() as db:
            stock_codes, etf_codes, bond_codes = classify_codes(codes)
            all_rows = []
            for model, sub_codes in [(StockDailyBar, stock_codes), (EtfDailyBar, etf_codes), (ConvertibleBondBar, bond_codes)]:
                if not sub_codes:
                    continue
                for i in range(0, len(sub_codes), BATCH_SIZE):
                    batch = sub_codes[i: i + BATCH_SIZE]
                    rows = (
                        db.query(model.code, model.trade_date, model.volume)
                        .filter(
                            model.code.in_(batch),
                            model.trade_date >= start_date,
                            model.trade_date <= end_date,
                            model.volume.isnot(None),
                        )
                        .order_by(model.trade_date.asc())
                        .all()
                    )
                    all_rows.extend(rows)
        if not all_rows:
            return None
        df = pd.DataFrame(all_rows, columns=["code", "trade_date", "volume"])
        df["trade_date"] = df["trade_date"].astype(str)
        vol_df = df.pivot(index="trade_date", columns="code", values="volume")
        # 对齐到价格矩阵维度
        vol_df = vol_df.reindex(index=dates, columns=valid_codes).fillna(0)
        return vol_df

    @staticmethod

    def _get_rebal_indices(dates: List[str], period: str) -> List[int]:

        if not dates:
            return []
        indices = [0]   # 第一天必调仓
        prev_month = dates[0][:7]
        prev_quarter = dates[0][:4] + "-" + str((int(dates[0][5:7]) - 1) // 3)
        from datetime import date as _date
        prev_week = _date.fromisoformat(dates[0]).isocalendar()[1]
        for i, d in enumerate(dates[1:], start=1):
            cur_month = d[:7]
            cur_quarter = d[:4] + "-" + str((int(d[5:7]) - 1) // 3)
            if period == "monthly" and cur_month != prev_month:
                indices.append(i)
                prev_month = cur_month
            elif period == "weekly":
                cur_week = _date.fromisoformat(d).isocalendar()[1]
                if cur_week != prev_week:
                    indices.append(i)
                    prev_week = cur_week
            elif period == "quarterly" and cur_quarter != prev_quarter:
                indices.append(i)
                prev_quarter = cur_quarter
        return indices

    @staticmethod
    def _get_benchmark_returns(start_date: str, end_date: str, target_len: int) -> List[float]:
        """复用 RiskService 的基准获取（统一降级链），并对齐到目标长度。"""
        from services.risk_service import RiskService
        rets = RiskService().get_benchmark_returns(start_date, end_date)
        if not rets:
            return [0.0] * target_len
        if len(rets) >= target_len:
            return rets[:target_len]
        return rets + [0.0] * (target_len - len(rets))



    @staticmethod
    def _build_signal_context(
        strategy_type: str, params: dict,
        price_arr: np.ndarray, t: int, signal_matrix: np.ndarray,
    ) -> Dict[int, str]:
        """
        根据策略类型和当时的价格/信号状态，为每个触发信号的标的生成决策描述。
        返回 {stock_idx: "描述字符串"}
        """
        from services.strategies.base import sma, ema

        ctx: Dict[int, str] = {}
        T, N = price_arr.shape
        if t < 1:
            return ctx

        triggered = np.where(signal_matrix[t] != 0)[0]
        if len(triggered) == 0:
            return ctx

        try:
            if strategy_type == "macd":
                fast_p = params.get("fast", 12)
                slow_p = params.get("slow", 26)
                sig_p = params.get("signal", 9)
                mode = params.get("mode", "macd")
                if mode == "rsi":
                    period = params.get("rsi_period", 14)
                    for idx in triggered:
                        prices = price_arr[:t+1, idx]
                        delta = np.diff(prices)
                        if len(delta) < period:
                            continue
                        alpha = 1.0 / period
                        avg_g, avg_l = np.mean(np.maximum(delta[:period], 0)), np.mean(np.maximum(-delta[:period], 0))
                        for k in range(period, len(delta)):
                            avg_g = alpha * max(delta[k], 0) + (1 - alpha) * avg_g
                            avg_l = alpha * max(-delta[k], 0) + (1 - alpha) * avg_l
                        rsi = 100 - 100 / (1 + avg_g / (avg_l + 1e-9))
                        ctx[idx] = f"RSI({period})={rsi:.1f}"
                else:
                    ema_f = ema(price_arr[:t+1], fast_p)
                    ema_s = ema(price_arr[:t+1], slow_p)
                    dif = ema_f - ema_s
                    dea = ema(dif, sig_p)
                    for idx in triggered:
                        d, e = float(dif[t, idx]), float(dea[t, idx])
                        cross = "金叉" if d > e else "死叉"
                        ctx[idx] = f"MACD {cross} DIF={d:.3f} DEA={e:.3f}"

            elif strategy_type == "timing":
                fast_p = params.get("fast_ma", 20)
                slow_p = params.get("slow_ma", 60)
                ma_f = sma(price_arr[:t+1], fast_p)
                ma_s = sma(price_arr[:t+1], slow_p)
                for idx in triggered:
                    f_val = float(ma_f[t, idx]) if not np.isnan(ma_f[t, idx]) else 0
                    s_val = float(ma_s[t, idx]) if not np.isnan(ma_s[t, idx]) else 0
                    if signal_matrix[t, idx] > 0:
                        ctx[idx] = f"MA{fast_p}={f_val:.2f}↑MA{slow_p}={s_val:.2f}"
                    else:
                        ctx[idx] = f"MA{fast_p}={f_val:.2f}↓MA{slow_p}={s_val:.2f}"

            elif strategy_type == "bband":
                window = params.get("window", 20)
                num_std = params.get("num_std", 2.0)
                mid = sma(price_arr[:t+1], window)
                std = np.nanstd(price_arr[max(0, t-window+1):t+1], axis=0)
                for idx in triggered:
                    m = float(mid[t, idx]) if not np.isnan(mid[t, idx]) else 0
                    upper = m + num_std * float(std[idx])
                    lower = m - num_std * float(std[idx])
                    p = float(price_arr[t, idx])
                    if signal_matrix[t, idx] > 0:
                        ctx[idx] = f"触及下轨 价格={p:.2f} 下轨={lower:.2f}"
                    else:
                        ctx[idx] = f"触及上轨 价格={p:.2f} 上轨={upper:.2f}"

            elif strategy_type == "turtle":
                entry = params.get("entry", 20)
                exit_n = params.get("exit", 10)
                for idx in triggered:
                    p = float(price_arr[t, idx])
                    if signal_matrix[t, idx] > 0:
                        high_n = float(np.nanmax(price_arr[max(0, t-entry):t, idx]))
                        ctx[idx] = f"突破{entry}日高点 价格={p:.2f}>{high_n:.2f}"
                    else:
                        low_m = float(np.nanmin(price_arr[max(0, t-exit_n):t, idx]))
                        ctx[idx] = f"跌破{exit_n}日低点 价格={p:.2f}<{low_m:.2f}"

            elif strategy_type == "volume_breakout":
                price_days = params.get("price_days", 20)
                for idx in triggered:
                    p = float(price_arr[t, idx])
                    if signal_matrix[t, idx] > 0:
                        high_n = float(np.nanmax(price_arr[max(0, t-price_days):t, idx]))
                        ctx[idx] = f"放量突破{price_days}日高点 {p:.2f}>{high_n:.2f}"
                    else:
                        low_n = float(np.nanmin(price_arr[max(0, t-price_days):t, idx]))
                        ctx[idx] = f"跌破{price_days}日低点 {p:.2f}<{low_n:.2f}"

            elif strategy_type == "grid":
                ma_w = params.get("ma_window", 20)
                grid_pct = params.get("grid_pct", 3.0) / 100
                mid = sma(price_arr[:t+1], ma_w)
                for idx in triggered:
                    m = float(mid[t, idx]) if not np.isnan(mid[t, idx]) else 0
                    p = float(price_arr[t, idx])
                    if m > 0:
                        dist = (p - m) / m
                        grid_n = int(abs(dist) / grid_pct) if grid_pct > 0 else 0
                        if signal_matrix[t, idx] > 0:
                            ctx[idx] = f"跌入第{grid_n}层网格 中轴={m:.2f}"
                        else:
                            ctx[idx] = f"涨入第{grid_n}层网格 中轴={m:.2f}"
        except Exception:
            pass  # 决策理由生成失败不影响回测
        return ctx

