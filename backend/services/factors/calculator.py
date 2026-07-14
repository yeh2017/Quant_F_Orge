"""
单只股票因子计算函数（声明式注册）
====================================
每个因子通过 @register_factor 装饰器声明：
  - name:      因子标识符
  - weight:    默认权重（总和 = 1.0）
  - label:     中文标签
  - fast_cols:  快速路径列映射 [(col, lower_better), ...]

添加新因子只需在本文件添加带装饰器的函数，其他文件自动生效。
"""
from typing import Optional, Dict, List, Any
import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)

from services.factors.utils import normalize_pct
from settings import TRADING_DAYS


# ── 因子注册表 ──
FACTOR_REGISTRY: Dict[str, Any] = {}


def register_factor(name: str, *, weight: float = 0.0, label: str = "",
                    fast_cols: Optional[list] = None, desc: str = "", items: Optional[list] = None,
                    category: str = ""):
    """装饰器：注册因子计算函数及其元数据

    Args:
        name:      因子唯一标识
        weight:    默认权重（weight=0 表示已弃用）
        label:     中文标签
        fast_cols:  快速路径列映射
        desc:      因子描述（前端卡片用）
        items:     因子包含的子指标列表（前端展示用）
        category:  因子分类（return/fundamental/risk）
    """
    def decorator(func):
        FACTOR_REGISTRY[name] = {
            "fn": func,
            "weight": weight,
            "label": label,
            "fast_cols": fast_cols or [],
            "desc": desc,
            "items": items or [],
            "category": category,
        }
        func._factor_name = name
        return func
    return decorator


# ── 工具函数：其他模块从这里读取因子配置 ──

def get_active_factors() -> dict:
    """返回活跃因子（weight > 0）的注册信息"""
    return {k: v for k, v in FACTOR_REGISTRY.items() if v["weight"] > 0}


def get_factor_weights() -> dict:
    """返回 {name: weight} 字典，仅活跃因子"""
    return {k: v["weight"] for k, v in FACTOR_REGISTRY.items() if v["weight"] > 0}


def get_factor_col_map() -> dict:
    """返回 {name: [(col, lower_better), ...]} 字典，仅活跃且有 fast_cols 的因子"""
    return {k: v["fast_cols"] for k, v in FACTOR_REGISTRY.items()
            if v["weight"] > 0 and v["fast_cols"]}


def get_factor_labels() -> dict:
    """返回 {name: label} 字典，仅活跃因子"""
    return {k: v["label"] for k, v in FACTOR_REGISTRY.items() if v["weight"] > 0}


def get_factor_cards() -> list:
    """返回前端因子卡片定义列表（按权重降序）"""
    cards = []
    for k, v in FACTOR_REGISTRY.items():
        if v["weight"] <= 0:
            continue
        cards.append({
            "key": k,
            "name": v["label"] + "因子" if v["label"] else k,
            "items": v["items"],
            "desc": v["desc"],
            "weight": v["weight"],
            "category": v.get("category", ""),
        })
    cards.sort(key=lambda x: x["weight"], reverse=True)
    return cards


# ─────────────── 因子定义（按权重降序） ───────────────

@register_factor("reversal", weight=0.23, label="反转",
                  fast_cols=[("reversal_20", False)],
                  desc="A股短期反转效应显著，近期跌的更可能反弹",
                  items=["1月收益反转", "超跌反弹"],
                  category="return")
def calc_reversal_factor(history: Optional[List[Dict]] = None, **_) -> float:
    """反转因子：最近 1 月收益率取反（A 股短期反转效应显著）"""
    if not history or len(history) < 22:
        return -np.inf
    try:
        df = pd.DataFrame(history)
        closes = df['close'].astype(float)
        ret_1m = closes.iloc[-1] / closes.iloc[-22] - 1
        return -ret_1m
    except (AttributeError, TypeError):
        raise
    except Exception:
        return -np.inf


@register_factor("value", weight=0.17, label="价值",
                  fast_cols=[("pe_ttm", True), ("pb", True)],
                  desc="PE/PB越低越有价值",
                  items=["PE", "PB", "PS"],
                  category="fundamental")
def calc_value_factor(ts_daily: Optional[Dict], financial: Optional[Dict], **_) -> float:
    """价值因子：PE_TTM 和 PB 的倒数加权"""
    exposure = 0.0
    weight_sum = 0.0

    if ts_daily:
        pe_ttm = float(ts_daily.get("pe_ttm", 0) or 0)
        pb = float(ts_daily.get("pb", 0) or 0)

        if pe_ttm > 0:
            ep = 1.0 / pe_ttm
            exposure += ep * 0.6
            weight_sum += 0.6

        if pb > 0:
            bp = 1.0 / pb
            exposure += bp * 0.4
            weight_sum += 0.4

    if weight_sum == 0 and financial:
        raw_pe = financial.get("pe") or financial.get("pe_ttm")
        try:
            if raw_pe and float(raw_pe) > 0:
                ep = 1.0 / float(raw_pe)
                exposure += ep
                weight_sum += 1.0
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("value_factor_pe_fallback_failed", error=str(e))

    if weight_sum > 0:
        return exposure / weight_sum
    return -np.inf


@register_factor("quality", weight=0.19, label="质量",
                  fast_cols=[("roe", False)],
                  desc="衡量盈利质量+杠杆风险，数值越高经营质量越好",
                  items=["ROE", "毛利率", "现金流质量", "低杠杆"],
                  category="fundamental")
def calc_quality_factor(financial: Optional[Dict], **_) -> float:
    """质量因子：ROE + 毛利率 + 现金流质量 + 低杠杆"""
    if not financial:
        return -np.inf
    roe = normalize_pct(financial.get("roe", 0)) / 100.0
    gpm = normalize_pct(financial.get("gross_profit_margin", 0)) / 100.0

    # 现金流质量：经营现金流净额 / (EPS × 1e8) 近似现金流/净利润比
    cf_quality = 0.0
    cashflow = financial.get("cashflow_oper")
    eps = financial.get("eps")
    if cashflow is not None and eps is not None:
        try:
            cf_val = float(cashflow)
            eps_val = float(eps)
            if eps_val > 0:
                cf_quality = min(cf_val / (eps_val * 1e8), 2.0)  # 上限截断
        except (ValueError, TypeError):
            pass

    # 低杠杆：资产负债率越低越好
    low_leverage = 0.0
    dta = financial.get("debt_to_assets")
    if dta is not None:
        try:
            dta_val = float(dta)
            if 0 <= dta_val <= 100:
                low_leverage = 1.0 - dta_val / 100.0
        except (ValueError, TypeError):
            pass

    # 权重分配：ROE 核心(0.35) + 毛利率(0.25) + 现金流(0.25) + 低杠杆(0.15)
    return roe * 0.35 + gpm * 0.25 + cf_quality * 0.25 + low_leverage * 0.15


@register_factor("size", weight=0.12, label="规模",
                  fast_cols=[("total_mv", True)],
                  desc="小市值股票长期超额收益显著（A股特色）",
                  items=["市值对数", "小市值溢价"],
                  category="risk")
def calc_size_factor(ts_daily: Optional[Dict] = None, **_) -> float:
    """规模因子：总市值对数取反（小市值溢价）"""
    if not ts_daily:
        return -np.inf
    total_mv = ts_daily.get("total_mv")
    if total_mv is None:
        return -np.inf
    try:
        mv = float(total_mv)
        if mv <= 0:
            return -np.inf
        return -np.log(mv)
    except (AttributeError, TypeError):
        raise
    except Exception:
        return -np.inf


@register_factor("momentum", weight=0.10, label="动量",
                  fast_cols=[("momentum_20", False)],
                  desc="12月前至1月前的经典学术动量，跳过近期反转噪声",
                  items=["12-1月收益", "中期趋势"],
                  category="return")
def calc_momentum_factor(history: Optional[List[Dict]] = None, **_) -> float:
    """动量因子：12-1 月经典学术动量"""
    if not history or len(history) < 60:
        return -np.inf
    try:
        df = pd.DataFrame(history)
        closes = df['close'].astype(float)
        if len(closes) >= TRADING_DAYS:
            ret_12_1 = closes.iloc[-22] / closes.iloc[-TRADING_DAYS] - 1
        else:
            ret_12_1 = closes.iloc[-22] / closes.iloc[0] - 1
        return ret_12_1
    except (AttributeError, TypeError):
        raise
    except Exception:
        return -np.inf


@register_factor("lowvol", weight=0.08, label="低波",
                  fast_cols=[("volatility_20", True)],
                  desc="低波动股票长期风险调整收益更优",
                  items=["波动率", "Beta"],
                  category="risk")
def calc_lowvol_factor(history: Optional[List[Dict]] = None, **_) -> float:
    """低波因子：下行波动率的相反数"""
    if not history or len(history) < 20:
        return -np.inf
    try:
        df = pd.DataFrame(history)
        closes = df['close'].astype(float)
        returns = closes.pct_change().dropna()
        downside = returns[returns < 0]
        if len(downside) < 5:
            downside_vol = returns.std() * np.sqrt(TRADING_DAYS)
        else:
            downside_vol = downside.std() * np.sqrt(TRADING_DAYS)
        return -downside_vol
    except (AttributeError, TypeError):
        raise
    except Exception:
        return -np.inf


@register_factor("growth", weight=0.05, label="成长",
                  fast_cols=[("revenue_growth", False), ("net_profit_growth", False)],
                  desc="评估公司成长性，结合营收利润增速",
                  items=["营收增长", "利润增长"],
                  category="fundamental")
def calc_growth_factor(financial: Optional[Dict], **_) -> float:
    """成长因子：营收同比和净利润同比"""
    if not financial:
        return -np.inf
    rev_yoy = normalize_pct(financial.get("revenue_growth") or financial.get("revenue_yoy", 0)) / 100.0
    np_yoy = normalize_pct(financial.get("net_profit_growth") or financial.get("net_profit_yoy", 0)) / 100.0
    if rev_yoy == 0 and np_yoy == 0:
        return -np.inf
    return rev_yoy * 0.4 + np_yoy * 0.6


@register_factor("dividend", weight=0.05, label="红利",
                  fast_cols=[("dv_ttm", False)],
                  desc="高股息股票长期跑赢大盘，A股红利策略独立alpha",
                  items=["股息率TTM", "分红稳定性"],
                  category="fundamental")
def calc_dividend_factor(ts_daily: Optional[Dict] = None, **_) -> float:
    """红利因子：股息率TTM（越高越好）"""
    if not ts_daily:
        return -np.inf
    dv = ts_daily.get("dv_ttm") or ts_daily.get("dv_ratio")
    if dv is None:
        return -np.inf
    try:
        val = float(dv)
        return val if val > 0 else -np.inf
    except (AttributeError, TypeError):
        raise
    except Exception:
        return -np.inf


@register_factor("concentration", weight=0.01, label="筹码集中",
                  fast_cols=[("holder_change_rate", True)],
                  desc="股东户数减少代表筹码集中，主力吸筹信号",
                  items=["股东户数变化率"],
                  category="fundamental")
def calc_concentration_factor(financial: Optional[Dict] = None, **_) -> float:
    """筹码集中因子：股东户数变化率取反（户数减少 → 筹码集中 → 值越大越好）"""
    if not financial:
        return -np.inf
    hcr = financial.get("holder_change_rate")
    if hcr is None:
        return -np.inf
    try:
        val = float(hcr)
        return -val  # 户数减少（负值）→ 取反 → 正值 → 越大越集中
    except (ValueError, TypeError):
        return -np.inf


@register_factor("leverage", weight=0.08, label="杠杆情绪",
                  fast_cols=[("margin_ratio", False)],
                  desc="融资余额/流通市值，衡量杠杆资金看多程度",
                  items=["融资余额比"], category="fundamental")
def calc_leverage_factor(financial: Optional[Dict] = None, **_) -> float:
    """杠杆情绪因子（慢路径 fallback，快路径用 margin_ratio 列排名）"""
    if not financial:
        return -np.inf
    mr = financial.get("margin_ratio")
    if mr is None:
        return -np.inf
    try:
        return float(mr)
    except (ValueError, TypeError):
        return -np.inf

