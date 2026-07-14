"""
ETF 筛选 Service
================
从 routers/screener_etf.py 提取的业务逻辑。
路由层只负责参数校验和调用本模块。
"""

import math
import re
import structlog
from collections import defaultdict
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.quant_data import StockBasicInfo, StockDailyBar

log = structlog.get_logger(__name__)

# ==================== 跟踪指数名称提取 ====================
# 从 ETF 名称提取核心指数短名（≤5字，数字可延伸到8字）
# 数据源选择：ETF 名称格式规范（[基金公司][指数名]ETF），比 benchmark
# 字段（含"经估值汇率调整后..."等复杂描述）更可靠且无格式变体。

_ETF_FUND_COMPANIES = sorted([
    "华夏基金", "易方达基金", "南方基金", "嘉实基金", "博时基金",
    "华泰柏瑞", "景顺长城", "交银施罗德", "申万菱信", "前海开源",
    "创金合信", "西部利得", "浦银安盛", "中信保诚", "国投瑞银",
    "方正富邦", "民生加银", "国寿安保", "华润元大", "弘毅远方",
    "恒生前海", "上投摩根", "南方东英", "红土创新",
    "工银瑞信", "汇添富", "鹏华", "中欧", "兴业", "银华",
    "国泰", "中银", "平安", "泰康", "长城", "大成", "万家",
    "海富通", "摩根", "永赢", "长信", "东方红", "中航",
    "中金", "中信建投", "国金", "德邦", "诺安", "太平",
    "长盛", "东财", "兴银", "东吴", "财通", "华富",
    "国联安", "华宝", "华安", "广发", "富国", "嘉实",
    "招商", "天弘", "建信", "华夏", "易方达", "南方",
    "博时", "交银", "国联", "中加", "鑫元", "中海", "顶峰",
], key=len, reverse=True)

_ETF_INDEX_PREFIXES = [
    "上证科创板", "中证全指", "中证800", "中证500",
    "中证", "上证", "深证", "国证",
    "深圳证券交易所", "上海证券交易所",
]

_ETF_INDEX_SUFFIXES = sorted([
    "生物科技", "科技业", "主题", "行业", "产业", "板块", "精选",
    "设备", "服务", "投资", "股票", "期货", "成份",
], key=len, reverse=True)


def _extract_tracking_index(etf_name: str) -> str | None:
    """从 ETF 名称提取跟踪指数短名（≤5字，数字延伸≤8字）"""
    if not etf_name:
        return None
    n = etf_name
    for s in ["ETF", "REIT", "LOF", "QDII", "联接", "发起式", "增强策略", "增强"]:
        n = n.replace(s, '')
    n = re.sub(r'[()（）\-]', '', n).strip()
    for co in _ETF_FUND_COMPANIES:
        if n.startswith(co):
            n = n[len(co):]
            break
    # 去编制机构前缀，记录被剥离的前缀以备回填
    stripped_prefix = None
    for pfx in _ETF_INDEX_PREFIXES:
        if n.startswith(pfx):
            rest = n[len(pfx):].strip()
            if rest and not rest.isdigit():
                stripped_prefix = pfx
                n = rest
            break
    # 名称归一化：长修饰语缩为短名（在截断前处理，避免暴力截断导致乱码）
    n = n.replace("可转债及可交换债券", "可转债")
    # 去末尾修饰词
    for sfx in _ETF_INDEX_SUFFIXES:
        if n.endswith(sfx) and len(n) > len(sfx) + 1:
            n = n[:-len(sfx)]
            break
    n = n.strip()
    if not n:
        return None
    # 去后缀后若只剩纯数字（如"50"），用前缀简称回填（"上证科创板"→"科创"）
    if n.isdigit() and stripped_prefix:
        short = {
            "上证科创板": "科创", "中证全指": "",
            "中证800": "中证", "中证500": "中证",
            "中证": "中证", "上证": "上证", "深证": "深证", "国证": "国证",
        }.get(stripped_prefix, stripped_prefix[:2])
        n = short + n
    if not n:
        return None
    if len(n) <= 5:
        return n
    # 可转债类指数名归一化后可达 6-7 字（如"投资级可转债"），直接保留
    if n.endswith("可转债") and len(n) <= 8:
        return n
    if n[4].isdigit():
        end = 5
        while end < len(n) and n[end].isdigit():
            end += 1
        if end <= 8:
            return n[:end]
    return n[:5]


# ==================== ETF→个股联动 ====================

def _query_industry_stocks(db: Session, sig_list, top_n, order_desc=True):
    """查同行业个股。优先申万行业映射表精确匹配，降级模糊匹配。"""
    from models.quant_data import SwIndustry
    results = []
    seen = set()
    for sig in sig_list:
        ind = sig["industry"]
        if not ind or ind in seen:
            continue
        seen.add(ind)

        stock_codes = [r[0] for r in db.query(SwIndustry.code).filter(
            SwIndustry.sw_l1_name == ind, SwIndustry.out_date.is_(None),
        ).all()]
        # 排除北交所（4/8/9开头），流动性差不适合联动推荐
        stock_codes = [c for c in stock_codes if c[0] not in ("4", "8", "9")]

        if not stock_codes:
            from sqlalchemy import or_
            stock_codes = [r[0] for r in db.query(StockBasicInfo.code).filter(
                or_(StockBasicInfo.industry.like(f"%{ind[:2]}%"), StockBasicInfo.industry == ind),
                ~StockBasicInfo.code.like("4%"),
                ~StockBasicInfo.code.like("8%"),
                ~StockBasicInfo.code.like("9%"),
            ).all()]

        if not stock_codes:
            results.append({"etf": sig, "industry": ind, "stocks": []})
            continue

        stock_latest = db.query(func.max(StockDailyBar.trade_date)).filter(
            StockDailyBar.code.in_(stock_codes)
        ).scalar()
        if not stock_latest:
            results.append({"etf": sig, "industry": ind, "stocks": []})
            continue

        order = StockDailyBar.pct_chg.desc() if order_desc else StockDailyBar.pct_chg.asc()
        top_stocks = db.query(
            StockDailyBar.code, StockDailyBar.close, StockDailyBar.pct_chg, StockDailyBar.amount,
        ).filter(
            StockDailyBar.trade_date == stock_latest,
            StockDailyBar.code.in_(stock_codes),
        ).order_by(order).limit(top_n).all()

        stock_names = {r.code: r.name for r in db.query(
            StockBasicInfo.code, StockBasicInfo.name
        ).filter(StockBasicInfo.code.in_([s.code for s in top_stocks])).all()}

        amount_ranked = sorted(top_stocks, key=lambda s: float(s.amount or 0), reverse=True)
        leader_codes = {s.code for s in amount_ranked[:3]}

        stocks = [{
            "code": s.code, "name": stock_names.get(s.code, s.code),
            "close": round(float(s.close or 0), 2),
            "pct_chg": round(float(s.pct_chg or 0), 2),
            "is_leader": s.code in leader_codes,
        } for s in top_stocks]

        results.append({"etf": sig, "industry": ind, "stocks": stocks})
    return results


def get_etf_stock_link(db: Session, *, volume_ratio: float = 1.5, top_n: int = 5) -> dict:
    """ETF 放量→个股推荐联动。返回4组信号。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar

    industry_etfs = db.query(EtfBasicInfo).filter(
        EtfBasicInfo.is_active == True, EtfBasicInfo.industry.isnot(None),
    ).all()
    if not industry_etfs:
        return {"today_links": [], "today_warnings": [],
                "week_links": [], "week_warnings": [], "trade_date": None}

    codes = [e.code for e in industry_etfs]
    etf_map = {e.code: {"name": e.name, "industry": e.industry} for e in industry_etfs}

    trade_dates = [r[0] for r in (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(5).all()
    )]
    if not trade_dates:
        return {"today_links": [], "today_warnings": [],
                "week_links": [], "week_warnings": [], "trade_date": None}

    latest_date = trade_dates[0]

    hist_dates = [r[0] for r in (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(25).all()
    )]
    hist_rows = db.query(
        EtfDailyBar.code, EtfDailyBar.trade_date, EtfDailyBar.amount
    ).filter(EtfDailyBar.code.in_(codes), EtfDailyBar.trade_date.in_(hist_dates)).all()

    code_history = defaultdict(list)
    for r in hist_rows:
        if r.amount and r.amount > 0:
            code_history[r.code].append((r.trade_date, float(r.amount)))
    for code in code_history:
        code_history[code].sort(key=lambda x: x[0], reverse=True)

    def _scan_volume_signals(target_dates):
        rows = db.query(EtfDailyBar).filter(
            EtfDailyBar.code.in_(codes), EtfDailyBar.trade_date.in_(target_dates),
        ).all()
        best_by_code = {}
        for row in rows:
            if not row.amount or row.amount <= 0:
                continue
            hist = code_history.get(row.code, [])
            prev_amounts = [amt for td, amt in hist if td < row.trade_date][:20]
            if not prev_amounts:
                continue
            avg_20 = sum(prev_amounts) / len(prev_amounts)
            if avg_20 <= 0:
                continue
            ratio = row.amount / avg_20
            if ratio < volume_ratio:
                continue
            prev = best_by_code.get(row.code)
            if not prev or ratio > prev["volume_ratio"]:
                info = etf_map.get(row.code, {})
                best_by_code[row.code] = {
                    "code": row.code, "name": info.get("name", ""),
                    "industry": info.get("industry", ""),
                    "pct_chg": round(float(row.pct_chg or 0), 2),
                    "volume_ratio": round(ratio, 2),
                    "amount": round(float(row.amount or 0), 0),
                    "trade_date": str(row.trade_date),
                }
        return sorted(best_by_code.values(), key=lambda x: x["volume_ratio"], reverse=True)

    today_signals = _scan_volume_signals([latest_date])
    week_signals = _scan_volume_signals(trade_dates)
    today_codes = {s["code"] for s in today_signals}
    week_only = [s for s in week_signals if s["code"] not in today_codes]

    def _split_and_query(signals):
        bullish = [s for s in signals if s["pct_chg"] >= 0]
        bearish = [s for s in signals if s["pct_chg"] < -1]
        links = _query_industry_stocks(db, bullish, top_n, order_desc=True)
        warnings = _query_industry_stocks(db, bearish, top_n, order_desc=False)
        return links[:10], warnings[:10]

    today_links, today_warnings = _split_and_query(today_signals)
    week_links, week_warnings = _split_and_query(week_only)

    return {
        "today_links": today_links, "today_warnings": today_warnings,
        "week_links": week_links, "week_warnings": week_warnings,
        "trade_date": str(latest_date), "volume_ratio_threshold": volume_ratio,
    }


def get_etf_list(db: Session, *, category: str = None) -> dict:
    """ETF 分类列表 + 最新行情。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar

    q = db.query(EtfBasicInfo).filter(EtfBasicInfo.is_active == True)
    if category:
        q = q.filter(EtfBasicInfo.category == category)
    etfs = q.all()
    if not etfs:
        return {"etfs": [], "categories": [], "total": 0}

    codes = [e.code for e in etfs]
    latest_date = db.query(func.max(EtfDailyBar.trade_date)).filter(
        EtfDailyBar.code.in_(codes)).scalar()

    bar_map = {}
    if latest_date:
        bars = db.query(EtfDailyBar).filter(
            EtfDailyBar.code.in_(codes), EtfDailyBar.trade_date == latest_date,
        ).all()
        bar_map = {b.code: b for b in bars}

    results = []
    for e in etfs:
        bar = bar_map.get(e.code)
        results.append({
            "code": e.code, "name": e.name, "category": e.category,
            "fund_type": e.fund_type, "management": e.management,
            "pct_chg": round(float(bar.pct_chg or 0), 2) if bar else None,
            "close": round(float(bar.close or 0), 3) if bar else None,
            "amount": round(float(bar.amount or 0), 0) if bar else None,
        })
    results.sort(key=lambda x: abs(x.get("amount") or 0), reverse=True)

    cat_counts = {}
    for r in results:
        cat = r.get("category", "其他")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    categories = [{"name": k, "count": v} for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])]

    return {
        "etfs": results, "categories": categories, "total": len(results),
        "trade_date": str(latest_date) if latest_date else None,
    }


def get_etf_reversal(db: Session, *, top_n: int = 5) -> dict:
    """ETF 弱转强/强转弱 Top N。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar
    from utils.trade_date import get_verified_trade_date

    etf_codes = [r[0] for r in db.query(EtfBasicInfo.code).filter(EtfBasicInfo.is_active == True).all()]
    if not etf_codes:
        return {"weak_to_strong": [], "strong_to_weak": [], "error": "无ETF数据"}

    recent_dates = (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(etf_codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(6).all()
    )
    if len(recent_dates) < 2:
        return {"weak_to_strong": [], "strong_to_weak": [], "error": "数据不足"}

    today = recent_dates[0][0]
    date_5d_start = recent_dates[-1][0]

    today_rows = db.query(EtfDailyBar.code, EtfDailyBar.pct_chg).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date == today).all()
    today_map = {r[0]: float(r[1] or 0) for r in today_rows}

    avg_rows = db.query(
        EtfDailyBar.code, func.round(func.avg(EtfDailyBar.pct_chg), 3)
    ).filter(
        EtfDailyBar.code.in_(etf_codes),
        EtfDailyBar.trade_date >= date_5d_start, EtfDailyBar.trade_date < today,
    ).group_by(EtfDailyBar.code).all()
    avg5d_map = {r[0]: float(r[1] or 0) for r in avg_rows}

    codes = set(today_map.keys()) & set(avg5d_map.keys())
    if len(codes) < 10:
        return {"weak_to_strong": [], "strong_to_weak": [], "error": "ETF数据不足"}

    info_map = {r.code: r for r in db.query(EtfBasicInfo).filter(EtfBasicInfo.code.in_(codes)).all()}

    by_5d = sorted(codes, key=lambda c: avg5d_map[c])
    by_today = sorted(codes, key=lambda c: today_map[c], reverse=True)

    total = len(codes)
    threshold = max(1, int(total * 0.25))

    w2s_codes = set(by_5d[:threshold]) & set(by_today[:threshold])
    s2w_codes = set(by_5d[-threshold:]) & set(by_today[-threshold:])

    def _build(code_set, sort_key, reverse=True):
        items = sorted(code_set, key=lambda c: sort_key(c), reverse=reverse)[:top_n]
        return [{
            "code": c, "name": (info_map.get(c) and info_map[c].name) or c,
            "industry": (info_map.get(c) and info_map[c].industry) or None,
            "today_chg": round(today_map.get(c, 0), 2),
            "avg5d_chg": round(avg5d_map.get(c, 0), 2),
            "swing": round(today_map.get(c, 0) - avg5d_map.get(c, 0), 2),
        } for c in items]

    _, data_verified = get_verified_trade_date("etf")

    return {
        "weak_to_strong": _build(w2s_codes, lambda c: today_map.get(c, 0) - avg5d_map.get(c, 0)),
        "strong_to_weak": _build(s2w_codes, lambda c: avg5d_map.get(c, 0) - today_map.get(c, 0)),
        "trade_date": str(today), "data_verified": data_verified,
    }


def etf_smart_screen(db: Session, *, top_n: int = 20, category: str = None, sub_category: str = None) -> dict:
    """ETF 一键智能筛选：成交活跃度 + 趋势强度 + 波动率综合评分。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar
    from utils.trade_date import get_verified_trade_date

    q = db.query(EtfBasicInfo.code).filter(EtfBasicInfo.is_active == True)
    if category:
        q = q.filter(EtfBasicInfo.category == category)
    if sub_category:
        if sub_category == "其他":
            q = q.filter(EtfBasicInfo.sub_category.is_(None))
        else:
            q = q.filter(EtfBasicInfo.sub_category == sub_category)
    etf_codes = [r[0] for r in q.all()]
    if not etf_codes:
        return {"etfs": [], "error": "无ETF数据"}

    # 取250天用于1年均涨，前20天用于短期评分
    all_dates = [r[0] for r in (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(etf_codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(250).all()
    )]
    if len(all_dates) < 5:
        return {"etfs": [], "error": "数据不足"}

    today = all_dates[0]
    recent_dates = all_dates[:20]

    stats = db.query(
        EtfDailyBar.code,
        func.avg(EtfDailyBar.pct_chg).label("avg_chg"),
        func.avg(EtfDailyBar.amount).label("avg_amount"),
        func.count(EtfDailyBar.code).label("days"),
        # 波动率用于 Sharpe 比率
        func.avg(EtfDailyBar.pct_chg * EtfDailyBar.pct_chg).label("avg_sq"),
    ).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date.in_(recent_dates),
    ).group_by(EtfDailyBar.code).all()

    # 近1年累计涨幅（今日close / 250天前close - 1）
    yearly_chg = {}
    if len(all_dates) > 20:
        earliest_date = all_dates[-1]
        earliest_bars = db.query(EtfDailyBar.code, EtfDailyBar.close).filter(
            EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date == earliest_date,
        ).all()
        earliest_map = {r[0]: float(r[1]) for r in earliest_bars if r[1]}
    else:
        earliest_map = {}

    # 20天前收盘价（用于近1月累计涨幅）
    date_20d_ago = recent_dates[-1] if len(recent_dates) >= 2 else None
    base_20d_map = {}
    if date_20d_ago:
        base_20d_bars = db.query(EtfDailyBar.code, EtfDailyBar.close).filter(
            EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date == date_20d_ago,
        ).all()
        base_20d_map = {r[0]: float(r[1]) for r in base_20d_bars if r[1]}

    today_bars = db.query(EtfDailyBar).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date == today,
    ).all()
    today_map = {b.code: b for b in today_bars}

    info_map = {r.code: r for r in db.query(EtfBasicInfo).filter(EtfBasicInfo.code.in_(etf_codes)).all()}

    scored = []
    filtered_out = 0
    for row in stats:
        code = row[0]
        avg_chg = float(row[1] or 0)
        avg_amount = float(row[2] or 0)
        days = int(row[3] or 0)
        if days < 5 or avg_amount < 1000:
            filtered_out += 1
            continue

        bar = today_map.get(code)
        info = info_map.get(code)
        if not bar or not info:
            continue

        # Sharpe 比率：avg / std（手动算 std = sqrt(E[x²] - E[x]²)）
        avg_sq = float(row[4] or 0)
        variance = max(avg_sq - avg_chg ** 2, 0)
        std_chg = math.sqrt(variance) if variance > 0 else 0.01
        sharpe = avg_chg / max(std_chg, 0.01)

        today_chg = float(bar.pct_chg or 0)
        trend_score = min(max(sharpe * 20 + 50, 0), 100)
        volume_score = min(math.log10(avg_amount + 1) * 15, 100)
        today_score = min(max(today_chg * 10 + 50, 0), 100)
        # 回测最优权重：趋势为主(70%)，成交额辅助(20%)，动量最轻(10%)
        composite = trend_score * 0.7 + volume_score * 0.2 + today_score * 0.1

        # 反转标签（仅标记，不影响评分 — 回测证明加分有害）
        reversal = None
        if avg_chg < -0.1 and today_chg > 0.5:
            reversal = "弱转强"
        elif avg_chg > 0.1 and today_chg < -0.5:
            reversal = "强转弱"

        # 累计涨幅（与行业标准一致）
        today_close = float(bar.close or 0)
        base_20d = base_20d_map.get(code)
        pct_20d = round((today_close / base_20d - 1) * 100, 2) if base_20d and base_20d > 0 else 0
        base_1y = earliest_map.get(code)
        pct_1y = round((today_close / base_1y - 1) * 100, 2) if base_1y and base_1y > 0 else 0

        # 从 ETF 名称提取跟踪指数短名
        bm_clean = _extract_tracking_index(info.name)

        scored.append({
            "code": code, "name": info.name, "category": info.category,
            "sub_category": info.sub_category,
            "list_date": info.list_date,
            "benchmark": bm_clean,
            "close": round(today_close, 3),
            "pct_chg": round(today_chg, 2),
            "amount": round(float(bar.amount or 0), 0),
            "pct_chg_20d": pct_20d,
            "avg_amount_20d": round(avg_amount, 0),
            "pct_chg_1y": pct_1y,
            "score": round(composite, 1), "reversal": reversal,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # ── 联查 EtfFundSnapshot 补充净值/份额/溢价率/规模字段 ──
    try:
        from models.quant_data import EtfFundSnapshot
        snap_date = db.query(func.max(EtfFundSnapshot.trade_date)).scalar()
        if snap_date:
            snap_rows = db.query(EtfFundSnapshot).filter(
                EtfFundSnapshot.trade_date == snap_date,
                EtfFundSnapshot.code.in_(etf_codes),
            ).all()
            snap_map = {r.code: r for r in snap_rows}

            # 净值 fallback：当天快照 nav 为空 或 完全无快照的 ETF，查最近有值的记录
            nav_missing_codes = [
                code for code in etf_codes
                if code not in snap_map or not snap_map[code].unit_nav
            ]
            nav_fallback_map = {}  # code → snapshot row with unit_nav
            if nav_missing_codes:
                fb_rows = db.query(EtfFundSnapshot).filter(
                    EtfFundSnapshot.code.in_(nav_missing_codes),
                    EtfFundSnapshot.trade_date < snap_date,
                    EtfFundSnapshot.unit_nav.isnot(None),
                ).order_by(
                    EtfFundSnapshot.code, EtfFundSnapshot.trade_date.desc()
                ).all()
                for r in fb_rows:
                    if r.code not in nav_fallback_map:
                        nav_fallback_map[r.code] = r

            # 查 N 天前快照用于规模变化（20 交易日前）
            # 用 <= 目标日期的最近可用快照（快照可能不是每天都有）
            prev_snap_map = {}
            if len(all_dates) >= 20:
                prev_date_20 = all_dates[19]  # 约 20 交易日前
                actual_prev = db.query(func.max(EtfFundSnapshot.trade_date)).filter(
                    EtfFundSnapshot.trade_date <= prev_date_20
                ).scalar()
                if actual_prev:
                    prev_rows = db.query(
                        EtfFundSnapshot.code, EtfFundSnapshot.total_share, EtfFundSnapshot.unit_nav
                    ).filter(
                        EtfFundSnapshot.trade_date == actual_prev,
                        EtfFundSnapshot.code.in_(etf_codes),
                    ).all()
                    # REITs nav 常为空，查 20 天前收盘价做 fallback
                    prev_close_map = {}
                    nav_missing_codes = [r.code for r in prev_rows if r.total_share and not r.unit_nav]
                    if nav_missing_codes:
                        from models.quant_data import EtfDailyBar
                        prev_bars = db.query(EtfDailyBar.code, EtfDailyBar.close).filter(
                            EtfDailyBar.code.in_(nav_missing_codes),
                            EtfDailyBar.trade_date == prev_date_20,
                        ).all()
                        prev_close_map = {r[0]: float(r[1]) for r in prev_bars if r[1]}
                    for r in prev_rows:
                        if r.total_share:
                            nav = float(r.unit_nav) if r.unit_nav else prev_close_map.get(r.code)
                            if nav and nav > 0:
                                prev_snap_map[r.code] = float(r.total_share) * nav

            for item in scored:
                snap = snap_map.get(item["code"])

                # 优先用当天快照净值，否则 fallback 到最近有值的历史快照
                fb = nav_fallback_map.get(item["code"])
                if snap:
                    unit_nav = float(snap.unit_nav) if snap.unit_nav else (float(fb.unit_nav) if fb else None)
                    nav_source_date = snap_date if snap.unit_nav else (fb.trade_date if fb else None)
                    total_share = float(snap.total_share) if snap.total_share else None
                elif fb:
                    # 无当天 snapshot（REITs 等），从历史记录取净值和份额
                    unit_nav = float(fb.unit_nav) if fb.unit_nav else None
                    nav_source_date = fb.trade_date
                    total_share = float(fb.total_share) if fb.total_share else None
                else:
                    item.update({"unit_nav": None, "nav_date": None, "premium": None,
                                 "total_share": None, "total_size": None, "size_chg": None})
                    continue

                # 溢价率 = close / unit_nav - 1
                premium = None
                close_val = item.get("close", 0)
                if unit_nav and unit_nav > 0 and close_val and close_val > 0:
                    premium = round((close_val / unit_nav - 1) * 100, 2)

                # 规模（亿元）= 份额 × 单位净值
                # REITs 净值按季/月公布，多数时间 nav=None → 用收盘价近似（REITs 溢价率低）
                effective_nav = unit_nav or close_val
                total_size = None
                if total_share and effective_nav and effective_nav > 0:
                    total_size = round(total_share * effective_nav / 1e8, 2)

                # 规模变化（亿元）= 今规模 - N日前规模
                size_chg = None
                if total_size and item["code"] in prev_snap_map:
                    prev_size = prev_snap_map[item["code"]]  # 原始值：份 × 元
                    if prev_size and prev_size > 0:
                        prev_size_yi = prev_size / 1e8  # 转亿元
                        size_chg = round(total_size - prev_size_yi, 2)

                item.update({
                    "unit_nav": round(unit_nav, 4) if unit_nav else None,
                    "nav_date": str(nav_source_date) if nav_source_date else None,
                    "premium": premium,
                    "total_share": round(total_share / 1e4, 2) if total_share else None,  # 万份
                    "total_size": total_size,  # 亿元
                    "size_chg": size_chg,
                })
        else:
            # 无快照数据时填 None
            for item in scored:
                item.update({"unit_nav": None, "nav_date": None, "premium": None,
                             "total_share": None, "total_size": None, "size_chg": None})
    except Exception as snap_err:
        log.warning("etf_smart_snapshot_join_failed", error=str(snap_err)[:80])
        for item in scored:
            item.update({"unit_nav": None, "nav_date": None, "premium": None,
                         "total_share": None, "total_size": None, "size_chg": None})

    _, data_verified = get_verified_trade_date("etf")

    # 分类计数（基于通过质量过滤的全量 scored，与筛选结果同口径）
    # 一级分类计数（始终基于全量，不受 category/sub_category 过滤影响）
    all_cats = db.query(
        EtfBasicInfo.category, func.count(EtfBasicInfo.code)
    ).filter(
        EtfBasicInfo.is_active == True,
    ).group_by(EtfBasicInfo.category).all()
    category_counts = [{"name": k, "count": v}
                       for k, v in sorted(all_cats, key=lambda x: -x[1])]

    # 二级分类计数（始终基于一级分类全量，不受 sub_category 过滤影响）
    sub_counts = []
    if category:
        all_subs = db.query(
            EtfBasicInfo.sub_category, func.count(EtfBasicInfo.code)
        ).filter(
            EtfBasicInfo.is_active == True,
            EtfBasicInfo.category == category,
        ).group_by(EtfBasicInfo.sub_category).all()
        sub_map = {}
        for sc, cnt in all_subs:
            sub_map[sc or "其他"] = cnt
        sub_counts = [{"name": k, "count": v}
                      for k, v in sorted(sub_map.items(), key=lambda x: -x[1])]

    return {
        # 按分类筛选返回全量（前端分页），全市场排名才限 top_n
        "etfs": scored if category else scored[:top_n], "total": len(scored),
        "filtered_out": filtered_out,
        "trade_date": str(today), "data_verified": data_verified,
        "category_counts": category_counts,
        "sub_category_counts": sub_counts,
    }


def get_etf_ranking(db: Session, *, top_n: int = 10) -> dict:
    """ETF 当日/5日涨跌排行 Top N。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar

    etf_codes = [r[0] for r in db.query(EtfBasicInfo.code).filter(EtfBasicInfo.is_active == True).all()]
    if not etf_codes:
        return {"today_top": [], "today_bottom": [],
                "fiveday_top": [], "fiveday_bottom": [], "error": "无ETF数据"}

    recent_dates = [r[0] for r in (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(etf_codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(6).all()
    )]
    if not recent_dates:
        return {"today_top": [], "today_bottom": [],
                "fiveday_top": [], "fiveday_bottom": [], "error": "数据不足"}

    today = recent_dates[0]
    info_map = {r.code: r for r in db.query(EtfBasicInfo).filter(EtfBasicInfo.code.in_(etf_codes)).all()}

    today_rows = db.query(EtfDailyBar).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date == today,
    ).all()

    today_data = []
    for b in today_rows:
        info = info_map.get(b.code)
        if not info or b.pct_chg is None:
            continue
        today_data.append({
            "code": b.code, "name": info.name, "category": info.category,
            "industry": info.industry,
            "close": round(float(b.close or 0), 3),
            "pct_chg": round(float(b.pct_chg), 2),
            "amount": round(float(b.amount or 0), 0),
        })

    today_sorted = sorted(today_data, key=lambda x: x["pct_chg"], reverse=True)
    today_top = today_sorted[:top_n]
    today_bottom = today_sorted[-top_n:][::-1]

    fiveday_top = []
    fiveday_bottom = []
    if len(recent_dates) >= 2:
        five_day_dates = recent_dates[:6]
        avg_rows = db.query(
            EtfDailyBar.code, func.sum(EtfDailyBar.pct_chg).label("sum_chg"),
            func.avg(EtfDailyBar.amount).label("avg_amt"),
        ).filter(
            EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date.in_(five_day_dates),
        ).group_by(EtfDailyBar.code).all()

        fiveday_data = []
        for row in avg_rows:
            info = info_map.get(row[0])
            if not info or row[1] is None:
                continue
            fiveday_data.append({
                "code": row[0], "name": info.name, "category": info.category,
                "industry": info.industry,
                "pct_chg_5d": round(float(row[1]), 2),
                "avg_amount": round(float(row[2] or 0), 0),
            })

        fiveday_sorted = sorted(fiveday_data, key=lambda x: x["pct_chg_5d"], reverse=True)
        fiveday_top = fiveday_sorted[:top_n]
        fiveday_bottom = fiveday_sorted[-top_n:][::-1]

    return {
        "today_top": today_top, "today_bottom": today_bottom,
        "fiveday_top": fiveday_top, "fiveday_bottom": fiveday_bottom,
        "trade_date": str(today), "total_etfs": len(today_data),
    }


def get_etf_overview(db: Session) -> dict:
    """ETF 市场总览 + 分类涨跌热力图。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar
    from utils.trade_date import get_verified_trade_date

    etf_all = db.query(EtfBasicInfo).filter(EtfBasicInfo.is_active == True).all()
    if not etf_all:
        return {"overview": None, "category_heat": [], "error": "无ETF数据"}
    etf_codes = [e.code for e in etf_all]
    info_map = {e.code: e for e in etf_all}

    recent_dates = [r[0] for r in (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(etf_codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(6).all()
    )]
    if not recent_dates:
        return {"overview": None, "category_heat": [], "error": "行情数据不足"}

    today = recent_dates[0]
    today_bars = db.query(EtfDailyBar).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date == today,
    ).all()

    up_count = down_count = flat_count = 0
    total_amount = pct_sum = 0.0
    valid_count = 0
    bar_map = {}

    for b in today_bars:
        if b.pct_chg is None:
            continue
        bar_map[b.code] = b
        pct = float(b.pct_chg)
        valid_count += 1
        pct_sum += pct
        total_amount += float(b.amount or 0)
        if pct > 0.01:
            up_count += 1
        elif pct < -0.01:
            down_count += 1
        else:
            flat_count += 1

    avg_pct = round(pct_sum / valid_count, 2) if valid_count else 0

    five_day_dates = recent_dates[:6]
    fiveday_rows = db.query(
        EtfDailyBar.code, func.sum(EtfDailyBar.pct_chg).label("sum_chg"),
    ).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date.in_(five_day_dates),
    ).group_by(EtfDailyBar.code).all()
    fiveday_map = {r[0]: round(float(r[1]), 2) for r in fiveday_rows if r[1] is not None}

    cat_stats = {}
    sub_stats = {}  # key: (category, sub_category)
    for code, b in bar_map.items():
        info = info_map.get(code)
        if not info:
            continue
        cat = info.category or "其他"
        sub = info.sub_category or ""
        if cat not in cat_stats:
            cat_stats[cat] = {"up": 0, "down": 0, "flat": 0, "pct_sum": 0, "count": 0,
                              "pct5d_sum": 0, "pct5d_count": 0, "amount_sum": 0}
        s = cat_stats[cat]
        pct = float(b.pct_chg)
        s["pct_sum"] += pct
        s["count"] += 1
        s["amount_sum"] += float(b.amount or 0)
        if pct > 0.01:
            s["up"] += 1
        elif pct < -0.01:
            s["down"] += 1
        else:
            s["flat"] += 1
        if code in fiveday_map:
            s["pct5d_sum"] += fiveday_map[code]
            s["pct5d_count"] += 1

        # 二级分类聚合（仅有 sub_category 的 ETF）
        if sub:
            sk = (cat, sub)
            if sk not in sub_stats:
                sub_stats[sk] = {"pct_sum": 0, "count": 0, "pct5d_sum": 0, "pct5d_count": 0}
            ss = sub_stats[sk]
            ss["pct_sum"] += pct
            ss["count"] += 1
            if code in fiveday_map:
                ss["pct5d_sum"] += fiveday_map[code]
                ss["pct5d_count"] += 1

    category_heat = []
    for cat, s in sorted(cat_stats.items(), key=lambda x: x[1]["pct_sum"] / max(x[1]["count"], 1), reverse=True):
        avg_today = round(s["pct_sum"] / max(s["count"], 1), 2)
        avg_5d = round(s["pct5d_sum"] / max(s["pct5d_count"], 1), 2) if s["pct5d_count"] else 0
        category_heat.append({
            "category": cat, "avg_pct": avg_today, "avg_pct_5d": avg_5d,
            "up": s["up"], "down": s["down"], "flat": s["flat"],
            "total": s["count"], "amount": round(s["amount_sum"], 0),
        })

    up_ratio = up_count / max(valid_count, 1)
    score = round(up_ratio * 50 + min(max(avg_pct + 1, 0), 2) * 25, 0)

    if score >= 60:
        regime, regime_color, regime_icon = "强势", "green", "🟢"
    elif score >= 40:
        regime, regime_color, regime_icon = "震荡", "amber", "🟠"
    else:
        regime, regime_color, regime_icon = "弱势", "red", "⚫"

    overview = {
        "trade_date": str(today), "total": valid_count,
        "up": up_count, "down": down_count, "flat": flat_count,
        "avg_pct": avg_pct, "total_amount": round(total_amount, 0),
        "score": int(score), "regime": regime,
        "regime_color": regime_color, "regime_icon": regime_icon,
    }

    # 二级分类热力图：按一级分类分组，每组内按 5 日涨跌排序
    sub_category_heat = {}
    for (cat, sub), ss in sub_stats.items():
        avg_today = round(ss["pct_sum"] / max(ss["count"], 1), 2)
        avg_5d = round(ss["pct5d_sum"] / max(ss["pct5d_count"], 1), 2) if ss["pct5d_count"] else 0
        sub_category_heat.setdefault(cat, []).append({
            "sub": sub, "avg_pct": avg_today, "avg_pct_5d": avg_5d, "count": ss["count"],
        })
    for cat in sub_category_heat:
        sub_category_heat[cat].sort(key=lambda x: x["avg_pct_5d"], reverse=True)

    _, data_verified = get_verified_trade_date("etf")
    return {
        "overview": overview, "category_heat": category_heat,
        "sub_category_heat": sub_category_heat,
        "data_verified": data_verified,
    }


def get_etf_rotation(db: Session, *, days: int = 30) -> dict:
    """ETF 板块轮动热力矩阵 + 连续领涨/领跌信号。"""
    from models.quant_data import EtfBasicInfo, EtfDailyBar

    etf_all = db.query(EtfBasicInfo).filter(EtfBasicInfo.is_active == True).all()
    if not etf_all:
        return {"dates": [], "categories": [], "matrix": [], "signals": [], "error": "无ETF数据"}
    etf_codes = [e.code for e in etf_all]
    info_map = {e.code: e for e in etf_all}

    trade_dates = [r[0] for r in (
        db.query(EtfDailyBar.trade_date).filter(EtfDailyBar.code.in_(etf_codes))
        .distinct().order_by(EtfDailyBar.trade_date.desc()).limit(days).all()
    )]
    if len(trade_dates) < 3:
        return {"dates": [], "categories": [], "matrix": [], "signals": [], "error": "数据不足"}
    trade_dates.sort()

    bars = db.query(
        EtfDailyBar.code, EtfDailyBar.trade_date, EtfDailyBar.pct_chg
    ).filter(
        EtfDailyBar.code.in_(etf_codes), EtfDailyBar.trade_date.in_(trade_dates),
    ).all()

    cat_date_pcts = defaultdict(lambda: defaultdict(list))
    sub_date_pcts = defaultdict(lambda: defaultdict(list))  # (category/sub_category) → date → [pct]
    for code, td, pct in bars:
        if pct is None:
            continue
        info = info_map.get(code)
        if not info:
            continue
        cat = info.category or "其他"
        cat_date_pcts[cat][str(td)].append(float(pct))
        sub = info.sub_category
        if sub:
            sub_date_pcts[(cat, sub)][str(td)].append(float(pct))

    categories = sorted(cat_date_pcts.keys())
    date_strs = [str(d) for d in trade_dates]

    matrix = []
    for cat in categories:
        row = []
        for ds in date_strs:
            pcts = cat_date_pcts[cat].get(ds, [])
            avg = round(sum(pcts) / len(pcts), 2) if pcts else 0
            row.append(avg)
        matrix.append(row)

    # 各分类累计涨跌（前端排名用）
    cat_totals = []
    for ci, cat in enumerate(categories):
        total = round(sum(matrix[ci]), 2)
        pct_5d = round(sum(matrix[ci][-5:]), 2) if len(matrix[ci]) >= 5 else total
        cat_totals.append({"category": cat, "total_pct": total, "pct_5d": pct_5d})
    cat_totals.sort(key=lambda x: x["total_pct"], reverse=True)

    # 二级分类轮动矩阵（按一级分类分组）
    sub_rotation = {}
    for (cat, sub), date_pcts in sub_date_pcts.items():
        if cat not in sub_rotation:
            sub_rotation[cat] = {"subs": [], "matrix": [], "totals": []}
        row = []
        for ds in date_strs:
            pcts = date_pcts.get(ds, [])
            avg = round(sum(pcts) / len(pcts), 2) if pcts else 0
            row.append(avg)
        total_pct = round(sum(row), 2)
        pct_5d = round(sum(row[-5:]), 2) if len(row) >= 5 else total_pct
        sub_rotation[cat]["subs"].append(sub)
        sub_rotation[cat]["matrix"].append(row)
        sub_rotation[cat]["totals"].append({"sub": sub, "total_pct": total_pct, "pct_5d": pct_5d})
    # 每组内按 total_pct 降序
    for v in sub_rotation.values():
        sorted_idx = sorted(range(len(v["totals"])), key=lambda i: v["totals"][i]["total_pct"], reverse=True)
        v["subs"] = [v["subs"][i] for i in sorted_idx]
        v["matrix"] = [v["matrix"][i] for i in sorted_idx]
        v["totals"] = [v["totals"][i] for i in sorted_idx]

    return {
        "dates": date_strs, "categories": categories, "matrix": matrix,
        "cat_totals": cat_totals, "total_days": len(date_strs),
        "sub_rotation": sub_rotation,
    }

