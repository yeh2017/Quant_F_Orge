"""
技术诊断引擎
============
7 维技术面诊断：趋势 / 均线 / 量能 / MACD / RSI / KDJ / 支撑压力。
提供单只完整诊断和批量精简诊断两个入口。
"""

from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import structlog

from utils.indicators import sma, ema

log = structlog.get_logger(__name__)


# ── 状态枚举 ──

class TrendState(str, Enum):
    STRONG_BULL = "强势多头"
    BULL = "多头趋势"
    WEAK_BULL = "偏多震荡"
    NEUTRAL = "横盘整理"
    WEAK_BEAR = "偏空震荡"
    BEAR = "空头趋势"
    STRONG_BEAR = "强势空头"


class VolumeState(str, Enum):
    VOL_UP_SURGE = "放量上涨"
    VOL_UP = "温和放量"
    VOL_STABLE = "量能平稳"
    VOL_DOWN_SHRINK = "缩量回调"
    VOL_DOWN_SURGE = "放量下跌"


class MacdState(str, Enum):
    ABOVE_GOLDEN = "零轴上金叉"
    ABOVE_BULL = "零轴上多头"
    ABOVE_WEAKENING = "零轴上减弱"
    CROSS_DOWN = "即将下穿零轴"
    BELOW_DEATH = "零轴下死叉"
    BELOW_BEAR = "零轴下空头"
    BELOW_RECOVERY = "零轴下回升"


class RsiState(str, Enum):
    OVERBOUGHT = "超买"
    HIGH = "偏强"
    NEUTRAL = "中性"
    LOW = "偏弱"
    OVERSOLD = "超卖"


class KdjState(str, Enum):
    OVERBOUGHT = "超买"
    HIGH = "偏强"
    NEUTRAL = "中性"
    LOW = "偏弱"
    OVERSOLD = "超卖"


# ── 颜色映射（A 股惯例：红涨绿跌，3 级） ──

_TREND_COLOR = {
    TrendState.STRONG_BULL: "#ef4444", TrendState.BULL: "#ef4444",
    TrendState.WEAK_BULL: "#ef4444", TrendState.NEUTRAL: "#9ca3af",
    TrendState.WEAK_BEAR: "#22c55e", TrendState.BEAR: "#22c55e",
    TrendState.STRONG_BEAR: "#22c55e",
}

_TREND_LEVEL = {
    TrendState.STRONG_BULL: 6, TrendState.BULL: 5,
    TrendState.WEAK_BULL: 4, TrendState.NEUTRAL: 3,
    TrendState.WEAK_BEAR: 2, TrendState.BEAR: 1,
    TrendState.STRONG_BEAR: 0,
}


class TechnicalService:
    """技术面诊断引擎"""

    LOOKBACK = 120  # 需要最近 120 个交易日数据

    def diagnose(self, code: str, end_date: str = None) -> Optional[Dict]:
        """单只完整诊断 — 6 维 + 综合评分 + 支撑压力"""
        data = self._load_bars(code, end_date)
        if data is None:
            return None

        closes, opens, highs, lows, volumes, dates, name, stale = data

        # 均线
        ma5 = sma(closes, 5)
        ma10 = sma(closes, 10)
        ma20 = sma(closes, 20)
        ma60 = sma(closes, 60)

        c = float(closes[-1])
        m5, m10, m20, m60 = float(ma5[-1]), float(ma10[-1]), float(ma20[-1]), float(ma60[-1])

        # 7 维
        trend = self._calc_trend(c, m5, m10, m20, m60)
        ma_info = self._calc_ma_analysis(closes, ma5, ma10, ma20, ma60)
        vol_state, vol_ratio, vol_avg20 = self._calc_volume(volumes, closes, opens)
        macd_state, dif, dea, hist = self._calc_macd(closes)
        rsi6, rsi14 = self._calc_rsi(closes, 6), self._calc_rsi(closes, 14)
        rsi_state = self._rsi_state(rsi14)
        levels = self._calc_support_resistance(c, highs, lows, m5, m10, m20, m60)
        kdj_k, kdj_state = self._calc_kdj(highs, lows, closes)
        divergence = self._calc_divergence(closes, highs, lows, volumes)
        composite = self._composite_score(trend, vol_state, macd_state, rsi14, kdj_k)

        # 文字摘要
        parts = [trend.value, ma_info["arrangement"], vol_state.value,
                 f"MACD{macd_state.value}", f"RSI{rsi_state.value}", f"KDJ{kdj_state.value}"]
        if divergence:
            parts.append(divergence)
        summary = "，".join(parts)

        return {
            "code": code, "name": name, "date": str(dates[-1]),
            "close": round(c, 2), "stale": stale,
            "composite": composite,
            "trend": {"state": trend.value, "level": _TREND_LEVEL[trend],
                      "color": _TREND_COLOR[trend]},
            "ma": ma_info,
            "volume": {"state": vol_state.value, "ratio": round(vol_ratio, 2),
                       "avg20": round(vol_avg20)},
            "macd": {"state": macd_state.value,
                     "dif": round(float(dif[-1]), 3),
                     "dea": round(float(dea[-1]), 3),
                     "histogram": round(float(hist[-1]), 3)},
            "rsi": {"state": rsi_state.value,
                    "rsi6": round(float(rsi6), 1),
                    "rsi14": round(float(rsi14), 1)},
            "kdj": {"state": kdj_state.value, "k": round(float(kdj_k), 1)},
            "levels": levels,
            "summary": summary,
        }

    def diagnose_batch(self, codes: List[str]) -> Dict[str, Dict]:
        """批量精简诊断 — 仅返回评分 + 趋势状态（供选股/回测列表）"""
        result = {}
        for code in codes:
            try:
                data = self._load_bars(code)
                if data is None:
                    continue
                closes, opens, highs, lows, volumes, _, _, _ = data
                ma5 = sma(closes, 5)
                ma10 = sma(closes, 10)
                ma20 = sma(closes, 20)
                ma60 = sma(closes, 60)
                c = float(closes[-1])
                m5, m10, m20, m60 = float(ma5[-1]), float(ma10[-1]), float(ma20[-1]), float(ma60[-1])

                trend = self._calc_trend(c, m5, m10, m20, m60)
                vol_state, _, _ = self._calc_volume(volumes, closes, opens)
                macd_state, _, _, _ = self._calc_macd(closes)
                rsi14 = self._calc_rsi(closes, 14)
                kdj_k, _ = self._calc_kdj(highs, lows, closes)
                composite = self._composite_score(trend, vol_state, macd_state, rsi14, kdj_k)

                result[code] = {
                    "score": composite["score"],
                    "label": composite["label"],
                    "trend": trend.value,
                    "trend_color": _TREND_COLOR[trend],
                }
            except Exception as e:
                log.warning("diagnose_batch_skip", code=code, error=str(e))
        return result

    # ── 数据加载 ──

    def _load_bars(self, code: str, end_date: str = None):
        """从 StockDailyBar/EtfDailyBar 加载最近 LOOKBACK 日 OHLCV"""
        from core.database import db_session
        from utils.bar_query import classify_codes
        from utils.trade_date import get_table_latest_date

        stock_codes, etf_codes, bond_codes = classify_codes([code])

        with db_session() as db:
            if stock_codes:
                from models.quant_data import StockDailyBar as BarModel, StockBasicInfo
                model = BarModel
                db_code = stock_codes[0]
                info = db.query(StockBasicInfo.name).filter(StockBasicInfo.code == db_code).scalar()
            elif etf_codes:
                from models.quant_data import EtfDailyBar as BarModel, EtfBasicInfo
                model = BarModel
                db_code = etf_codes[0]
                info = db.query(EtfBasicInfo.name).filter(EtfBasicInfo.code == db_code).scalar()
            elif bond_codes:
                from models.quant_data import ConvertibleBondBar as BarModel, ConvertibleBondBasic
                model = BarModel
                db_code = bond_codes[0]
                info = db.query(ConvertibleBondBasic.name).filter(ConvertibleBondBasic.code == db_code).scalar()
            else:
                return None

            name = info or code
            query = db.query(
                model.trade_date, model.open, model.high, model.low, model.close, model.volume
            ).filter(model.code == db_code)

            if end_date:
                query = query.filter(model.trade_date <= end_date)

            query = query.order_by(model.trade_date.desc()).limit(self.LOOKBACK)
            rows = query.all()

        if len(rows) < 60:
            return None

        # 反转为时间正序
        rows = rows[::-1]
        dates = [r[0] for r in rows]
        opens = np.array([float(r[1] or 0) for r in rows])
        highs = np.array([float(r[2] or 0) for r in rows])
        lows = np.array([float(r[3] or 0) for r in rows])
        closes = np.array([float(r[4] or 0) for r in rows])
        volumes = np.array([float(r[5] or 0) for r in rows])

        # 判断数据是否过期（最新日期 vs 表最新日期差 > 2 天）
        # 用户主动查看历史（end_date 远早于表最新日）时不标记 stale
        latest_str = get_table_latest_date("bars")
        stale = False
        if latest_str:
            from datetime import date as _date
            table_latest = _date.fromisoformat(latest_str)
            data_latest = _date.fromisoformat(str(dates[-1]))
            is_historical = end_date and (table_latest - _date.fromisoformat(end_date)).days > 2
            if not is_historical:
                stale = (table_latest - data_latest).days > 2

        return closes, opens, highs, lows, volumes, dates, name, stale

    # ── 趋势判断 ──

    def _calc_trend(self, close, ma5, ma10, ma20, ma60) -> TrendState:
        bull_aligned = ma5 > ma10 > ma20 > ma60
        bear_aligned = ma5 < ma10 < ma20 < ma60
        if bull_aligned and close > ma5:
            return TrendState.STRONG_BULL
        if bull_aligned:
            return TrendState.BULL
        if bear_aligned and close < ma5:
            return TrendState.STRONG_BEAR
        if bear_aligned:
            return TrendState.BEAR
        bias_20 = (close - ma20) / ma20 if ma20 > 0 else 0
        if bias_20 > 0.02:
            return TrendState.WEAK_BULL
        if bias_20 < -0.02:
            return TrendState.WEAK_BEAR
        return TrendState.NEUTRAL

    # ── 均线分析 ──

    def _calc_ma_analysis(self, closes, ma5, ma10, ma20, ma60) -> Dict:
        c = float(closes[-1])
        m5, m10, m20, m60 = float(ma5[-1]), float(ma10[-1]), float(ma20[-1]), float(ma60[-1])

        if m5 > m10 > m20 > m60:
            arrangement = "多头排列"
        elif m5 < m10 < m20 < m60:
            arrangement = "空头排列"
        else:
            arrangement = "交叉缠绕"

        # 金叉/死叉：近 5 日 MA5 与 MA20 的交叉
        golden = False
        death = False
        for i in range(-5, -1):
            if float(ma5[i]) <= float(ma20[i]) and float(ma5[i + 1]) > float(ma20[i + 1]):
                golden = True
            if float(ma5[i]) >= float(ma20[i]) and float(ma5[i + 1]) < float(ma20[i + 1]):
                death = True

        return {
            "arrangement": arrangement,
            "bias_5": round((c - m5) / m5 * 100, 2) if m5 > 0 else 0,
            "bias_20": round((c - m20) / m20 * 100, 2) if m20 > 0 else 0,
            "bias_60": round((c - m60) / m60 * 100, 2) if m60 > 0 else 0,
            "golden_cross": golden,
            "death_cross": death,
        }

    # ── 量能分析 ──

    def _calc_volume(self, volumes, closes, opens):
        avg20 = float(np.mean(volumes[-20:]))
        cur_vol = float(volumes[-1])
        ratio = cur_vol / avg20 if avg20 > 0 else 1.0
        is_up = float(closes[-1]) >= float(opens[-1])

        if ratio > 2.0:
            state = VolumeState.VOL_UP_SURGE if is_up else VolumeState.VOL_DOWN_SURGE
        elif ratio > 1.3 and is_up:
            state = VolumeState.VOL_UP
        elif ratio < 0.7 and not is_up:
            state = VolumeState.VOL_DOWN_SHRINK
        else:
            state = VolumeState.VOL_STABLE

        return state, ratio, avg20

    # ── MACD ──

    def _calc_macd(self, closes, fast=12, slow=26, signal=9):
        # 1D 数组需要扩展为 (T,1) 给 ema，然后压平
        c = closes.reshape(-1, 1)
        dif = ema(c, fast).flatten() - ema(c, slow).flatten()
        dea = ema(dif.reshape(-1, 1), signal).flatten()
        hist = (dif - dea) * 2

        above_zero = dif[-1] > 0
        golden = dif[-2] < dea[-2] and dif[-1] > dea[-1]
        death = dif[-2] > dea[-2] and dif[-1] < dea[-1]
        hist_shrinking = abs(hist[-1]) < abs(hist[-2])

        if above_zero:
            if golden:
                state = MacdState.ABOVE_GOLDEN
            elif dif[-1] > dea[-1]:
                state = MacdState.ABOVE_WEAKENING if hist_shrinking else MacdState.ABOVE_BULL
            else:
                state = MacdState.CROSS_DOWN
        else:
            if death:
                state = MacdState.BELOW_DEATH
            elif dif[-1] < dea[-1]:
                state = MacdState.BELOW_RECOVERY if hist_shrinking else MacdState.BELOW_BEAR
            else:
                state = MacdState.BELOW_RECOVERY

        return state, dif, dea, hist

    # ── RSI ──

    def _calc_rsi(self, closes, period=14) -> float:
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - 100 / (1 + rs))

    def _rsi_state(self, rsi: float) -> RsiState:
        if rsi > 80:
            return RsiState.OVERBOUGHT
        if rsi > 60:
            return RsiState.HIGH
        if rsi >= 40:
            return RsiState.NEUTRAL
        if rsi >= 20:
            return RsiState.LOW
        return RsiState.OVERSOLD

    # ── 支撑/压力 ──

    def _calc_support_resistance(self, close, highs, lows, ma5, ma10, ma20, ma60) -> Dict:
        if close <= 0:
            return {"supports": [], "resistances": []}
        supports, resistances = [], []

        for name, val in [("MA5", ma5), ("MA10", ma10), ("MA20", ma20), ("MA60", ma60)]:
            entry = {"level": round(val, 2), "type": name,
                     "distance_pct": round(abs(close - val) / close * 100, 2)}
            if val < close:
                supports.append(entry)
            elif val > close:
                resistances.append(entry)

        high_20 = float(np.max(highs[-20:]))
        low_20 = float(np.min(lows[-20:]))
        if high_20 > close:
            resistances.append({"level": round(high_20, 2), "type": "20日高点",
                                "distance_pct": round((high_20 - close) / close * 100, 2)})
        if low_20 < close:
            supports.append({"level": round(low_20, 2), "type": "20日低点",
                             "distance_pct": round((close - low_20) / close * 100, 2)})

        supports.sort(key=lambda x: x["distance_pct"])
        resistances.sort(key=lambda x: x["distance_pct"])
        return {"supports": supports[:3], "resistances": resistances[:3]}

    # ── 量价背离检测 ──

    def _calc_divergence(self, closes, highs, lows, volumes, n=20):
        """量价背离：价格新高+缩量=顶背离，价格新低+缩量=底部信号"""
        if len(closes) < n + 1:
            return None
        high_n = float(np.max(highs[-n:]))
        low_n = float(np.min(lows[-n:]))
        vol_avg = float(np.mean(volumes[-n:]))
        cur_vol = float(volumes[-1])
        cur_close = float(closes[-1])

        if cur_close >= high_n * 0.98 and cur_vol < vol_avg * 0.8:
            return "⚠ 量价顶背离"
        if cur_close <= low_n * 1.02 and cur_vol < vol_avg * 0.8:
            return "✓ 缩量底部"
        return None

    # ── KDJ 计算 ──

    def _calc_kdj(self, highs, lows, closes, n=9, m1=3, m2=3):
        """计算 KDJ，返回 (k_value, KdjState)"""
        length = len(closes)
        if length < n:
            return 50.0, KdjState.NEUTRAL

        k_prev, d_prev = 50.0, 50.0
        for i in range(length):
            if i < n - 1:
                continue
            hn = float(np.max(highs[i - n + 1:i + 1]))
            ln = float(np.min(lows[i - n + 1:i + 1]))
            c = float(closes[i])
            rsv = 50.0 if hn == ln else (c - ln) / (hn - ln) * 100
            k_prev = (rsv + (m1 - 1) * k_prev) / m1
            d_prev = (k_prev + (m2 - 1) * d_prev) / m2

        k_val = k_prev
        if k_val > 80:
            state = KdjState.OVERBOUGHT
        elif k_val > 60:
            state = KdjState.HIGH
        elif k_val > 40:
            state = KdjState.NEUTRAL
        elif k_val > 20:
            state = KdjState.LOW
        else:
            state = KdjState.OVERSOLD
        return k_val, state

    # ── 综合评分 ──

    def _composite_score(self, trend, volume, macd_state, rsi_val, kdj_k=50.0) -> Dict:
        TREND_SCORES = {
            TrendState.STRONG_BULL: 100, TrendState.BULL: 80,
            TrendState.WEAK_BULL: 60, TrendState.NEUTRAL: 50,
            TrendState.WEAK_BEAR: 40, TrendState.BEAR: 20,
            TrendState.STRONG_BEAR: 0,
        }
        VOLUME_SCORES = {
            VolumeState.VOL_UP_SURGE: 90, VolumeState.VOL_UP: 70,
            VolumeState.VOL_STABLE: 50, VolumeState.VOL_DOWN_SHRINK: 35,
            VolumeState.VOL_DOWN_SURGE: 10,
        }
        MACD_SCORES = {
            MacdState.ABOVE_GOLDEN: 100, MacdState.ABOVE_BULL: 80,
            MacdState.ABOVE_WEAKENING: 55, MacdState.CROSS_DOWN: 40,
            MacdState.BELOW_RECOVERY: 45, MacdState.BELOW_BEAR: 20,
            MacdState.BELOW_DEATH: 0,
        }
        rsi_score = min(100.0, max(0.0, rsi_val))
        kdj_score = min(100.0, max(0.0, kdj_k))

        # 权重：趋势30% + 量能15% + MACD20% + RSI15% + KDJ10% + 趋势补10%
        score = (
            TREND_SCORES[trend] * 0.40
            + VOLUME_SCORES[volume] * 0.15
            + MACD_SCORES[macd_state] * 0.20
            + rsi_score * 0.15
            + kdj_score * 0.10
        )
        if score >= 60:
            label = "强势"
        elif score >= 40:
            label = "中性"
        else:
            label = "弱势"

        return {"score": round(score), "label": label}

