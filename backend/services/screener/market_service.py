"""
股票筛选 Service
================
从 routers/screener_market.py 提取的 screen_stocks 核心业务逻辑。
路由层只负责参数校验和调用本模块。
"""

import math
import structlog
from datetime import date as _date_cls, timedelta
from sqlalchemy import and_, or_, func, exists, select
from sqlalchemy.orm import Session, aliased

from models.quant_data import (
    StockBasicInfo, StockDailyBar, StockDailyFactor,
    StockFinancial, StockMoneyFlow, FactorSnapshot, StockShareholderCount,
    ConvertibleBondBasic, StockNews, StockMarginData,
)
from services.screener.scoring import percentile_rank

log = structlog.get_logger(__name__)


def screen_stocks(db: Session, *, pe_max=None, pb_max=None, roe_min=None,
                  revenue_yoy_min=None, net_profit_yoy_min=None,
                  turnover_rate_min=None, net_inflow_min=None,
                  pct_chg_min=None, pct_chg_max=None,
                  volume_ratio_min=None,
                  gap_up=None, holder_chg_max=None,
                  max_list_days=None,
                  has_block_trade=None, has_unlock=None, has_top_list=None,
                  margin_chg_min=None,
                  industries=None, index_filter=None,
                  sort_by="score", sort_order="desc",
                  page=1, page_size=50) -> dict:
    """
    按因子阈值筛选股票（纯 SQL 联表查询，毫秒级响应）。

    Args:
        db: SQLAlchemy Session（由路由层管理生命周期）
        其余参数对应 ScreenerRequest 的各字段

    Returns:
        {"stocks": [...], "total_matched": int, "page": int, ...}
    """
    from utils.trade_date import get_table_latest_date
    from datetime import date as _date

    latest_factor_str = get_table_latest_date("factors")
    latest_factor_date = _date.fromisoformat(latest_factor_str) if latest_factor_str else None
    if not latest_factor_date:
        return {"stocks": [], "total": 0, "message": "本地数仓无因子数据，请先同步"}

    latest_mf_str = get_table_latest_date("money_flow")
    latest_mf_date = _date.fromisoformat(latest_mf_str) if latest_mf_str else None

    latest_report_sub = db.query(
        StockFinancial.code,
        func.max(StockFinancial.report_date).label("max_report_date")
    ).group_by(StockFinancial.code).subquery()

    latest_bar_date_str = get_table_latest_date("bars")
    latest_bar_date = _date.fromisoformat(latest_bar_date_str) if latest_bar_date_str else None

    # ── 构建多表 JOIN 查询 ──
    query = db.query(
        StockBasicInfo.code,
        StockBasicInfo.name,
        StockBasicInfo.industry,
        StockBasicInfo.market,
        StockBasicInfo.list_date,
        StockDailyFactor.pe_ttm,
        StockDailyFactor.pb,
        StockDailyFactor.turnover_rate,
        StockDailyFactor.total_mv,
        StockFinancial.roe,
        StockFinancial.revenue_yoy,
        StockFinancial.net_profit_yoy,
        StockFinancial.eps,
        StockMoneyFlow.net_mf_amount,
        StockDailyBar.pct_chg,
        StockDailyBar.close.label('bar_close'),
        StockDailyBar.volume,
        StockDailyBar.amount.label('bar_amount'),
        StockDailyBar.open.label('bar_open'),
        StockDailyBar.pre_close,
    ).join(
        StockDailyFactor,
        and_(
            StockBasicInfo.code == StockDailyFactor.code,
            StockDailyFactor.trade_date == latest_factor_date
        )
    ).join(
        latest_report_sub,
        StockBasicInfo.code == latest_report_sub.c.code
    ).join(
        StockFinancial,
        and_(
            StockBasicInfo.code == StockFinancial.code,
            StockFinancial.report_date == latest_report_sub.c.max_report_date
        )
    ).outerjoin(
        StockMoneyFlow,
        and_(
            StockBasicInfo.code == StockMoneyFlow.code,
            StockMoneyFlow.trade_date == latest_mf_date
        ) if latest_mf_date else (StockBasicInfo.code == None)
    ).outerjoin(
        StockDailyBar,
        and_(
            StockBasicInfo.code == StockDailyBar.code,
            StockDailyBar.trade_date == latest_bar_date
        ) if latest_bar_date else (StockBasicInfo.code == None)
    )

    # 股东数据 JOIN
    sh_sub = db.query(
        StockShareholderCount.code,
        func.max(StockShareholderCount.end_date).label("max_sh_date")
    ).group_by(StockShareholderCount.code).subquery()

    query = query.outerjoin(
        sh_sub, StockBasicInfo.code == sh_sub.c.code
    ).outerjoin(
        StockShareholderCount,
        and_(
            StockBasicInfo.code == StockShareholderCount.code,
            StockShareholderCount.end_date == sh_sub.c.max_sh_date,
        )
    ).add_columns(
        StockShareholderCount.holder_num_change_rate,
    ).filter(
        StockBasicInfo.is_active == True,
        ~StockBasicInfo.name.contains("退市"),
        ~StockBasicInfo.code.like("4%"),
        ~StockBasicInfo.code.like("8%"),
        ~StockBasicInfo.code.like("9%"),
    )

    # ── 应用筛选条件 ──
    if pe_max is not None:
        query = query.filter(StockDailyFactor.pe_ttm <= pe_max, StockDailyFactor.pe_ttm > 0)
    if pb_max is not None:
        query = query.filter(StockDailyFactor.pb <= pb_max, StockDailyFactor.pb > 0)
    if roe_min is not None:
        query = query.filter(StockFinancial.roe >= roe_min)
    if revenue_yoy_min is not None:
        query = query.filter(StockFinancial.revenue_yoy >= revenue_yoy_min)
    if net_profit_yoy_min is not None:
        query = query.filter(StockFinancial.net_profit_yoy >= net_profit_yoy_min)
    if turnover_rate_min is not None:
        query = query.filter(StockDailyFactor.turnover_rate >= turnover_rate_min)
    if net_inflow_min is not None:
        query = query.filter(StockMoneyFlow.net_mf_amount >= net_inflow_min)
    if volume_ratio_min is not None:
        query = query.filter(StockDailyFactor.volume_ratio >= volume_ratio_min)
    if industries:
        from utils.industry import industry_filter
        query = query.filter(industry_filter(db, industries))
    if index_filter:
        _INDEX_MAP = {"hs300": "399300.SZ", "csi500": "000905.SH", "csi1000": "000852.SH"}
        idx_code = _INDEX_MAP.get(index_filter)
        if idx_code:
            from models.quant_data import IndexWeight
            latest_iw_date = db.query(func.max(IndexWeight.trade_date)).filter(
                IndexWeight.index_code == idx_code
            ).scalar()
            if latest_iw_date:
                member_codes = [r[0] for r in db.query(IndexWeight.con_code).filter(
                    IndexWeight.index_code == idx_code,
                    IndexWeight.trade_date == latest_iw_date,
                ).all()]
                if member_codes:
                    query = query.filter(StockBasicInfo.code.in_(member_codes))
    if pct_chg_min is not None and latest_bar_date:
        query = query.filter(StockDailyBar.pct_chg >= pct_chg_min)
    if pct_chg_max is not None and latest_bar_date:
        query = query.filter(StockDailyBar.pct_chg <= pct_chg_max)
    if gap_up and latest_bar_date:
        query = query.filter(StockDailyBar.open > StockDailyBar.pre_close)
    if holder_chg_max is not None:
        query = query.filter(StockShareholderCount.holder_num_change_rate <= holder_chg_max)
    if max_list_days is not None:
        cutoff = (_date_cls.today() - timedelta(days=max_list_days)).strftime("%Y-%m-%d")
        query = query.filter(StockBasicInfo.list_date >= cutoff)

    # ── 事件筛选（OR 逻辑：勾选多个事件时，命中任一即可）──
    _EVENT_WINDOW_DAYS = 8  # ≈5个交易日
    event_cutoff = _date_cls.today() - timedelta(days=_EVENT_WINDOW_DAYS)
    _event_conditions = []
    if has_block_trade:
        _event_conditions.append(exists(
            select(StockNews.id).where(
                StockNews.code == StockBasicInfo.code,
                StockNews.event_type == '大宗交易',
                StockNews.publish_time >= event_cutoff,
            )
        ))
    if has_unlock:
        _event_conditions.append(exists(
            select(StockNews.id).where(
                StockNews.code == StockBasicInfo.code,
                StockNews.event_type == '解禁',
                StockNews.publish_time >= event_cutoff,
            )
        ))
    if has_top_list:
        _event_conditions.append(exists(
            select(StockNews.id).where(
                StockNews.code == StockBasicInfo.code,
                StockNews.event_type == '龙虎榜',
                StockNews.publish_time >= event_cutoff,
            )
        ))
    if _event_conditions:
        query = query.filter(or_(*_event_conditions))

    # ── 融资余额变化率筛选（双日期自连接）──
    margin_chg_expr = None
    if margin_chg_min is not None or sort_by == 'margin_chg':
        latest_margin_date = db.query(func.max(StockMarginData.trade_date)).scalar()
        if latest_margin_date:
            old_margin_date = db.query(StockMarginData.trade_date).filter(
                StockMarginData.trade_date <= latest_margin_date - timedelta(days=_EVENT_WINDOW_DAYS)
            ).order_by(StockMarginData.trade_date.desc()).limit(1).scalar()
            if old_margin_date:
                m_new = aliased(StockMarginData, name='m_new')
                m_old = aliased(StockMarginData, name='m_old')
                query = query.outerjoin(
                    m_new, and_(m_new.code == StockBasicInfo.code, m_new.trade_date == latest_margin_date)
                ).outerjoin(
                    m_old, and_(m_old.code == StockBasicInfo.code, m_old.trade_date == old_margin_date)
                )
                margin_chg_expr = (m_new.rzye - m_old.rzye) / func.nullif(m_old.rzye, 0) * 100
                query = query.add_columns(margin_chg_expr.label('margin_chg_val'))
                if margin_chg_min is not None:
                    query = query.filter(margin_chg_expr >= margin_chg_min)

    total_matched = query.count()
    offset = (page - 1) * page_size

    # ── 排序 ──
    SORT_MAP = {
        "roe": StockFinancial.roe,
        "pe": StockDailyFactor.pe_ttm,
        "pb": StockDailyFactor.pb,
        "pct_chg": StockDailyBar.pct_chg,
        "turnover": StockDailyFactor.turnover_rate,
        "revenue_yoy": StockFinancial.revenue_yoy,
        "net_profit_yoy": StockFinancial.net_profit_yoy,
        "net_mf_amount": StockMoneyFlow.net_mf_amount,
        "total_mv": StockDailyFactor.total_mv,
        "holder_chg": StockShareholderCount.holder_num_change_rate,
        "amount": StockDailyBar.amount,
    }
    if sort_by == 'margin_chg' and margin_chg_expr is not None:
        sort_col = margin_chg_expr
    else:
        sort_col = SORT_MAP.get(sort_by)
    if sort_col is not None:
        order_fn = sort_col.asc() if sort_order == "asc" else sort_col.desc()
        rows = query.order_by(order_fn.nullslast()).offset(offset).limit(page_size).all()
    else:
        rows = query.order_by(
            StockFinancial.roe.desc().nullslast(),
            StockDailyFactor.pe_ttm.asc().nullslast(),
        ).offset(offset).limit(page_size).all()

    # ── 评分：优先用 FactorSnapshot，否则基础公式 ──
    snapshot_map = {}
    latest_snap_date = db.query(func.max(FactorSnapshot.trade_date)).filter(
        FactorSnapshot.strategy_type == "signal"
    ).scalar()
    if latest_snap_date:
        snapshots = db.query(
            FactorSnapshot.code, FactorSnapshot.composite
        ).filter(
            FactorSnapshot.strategy_type == "signal",
            FactorSnapshot.trade_date == latest_snap_date,
            FactorSnapshot.code.in_([r.code for r in rows])
        ).all()
        for s in snapshots:
            snapshot_map[s.code] = s.composite

    has_snapshot = len(snapshot_map) > 0

    if not has_snapshot:
        roe_ranks = percentile_rank([float(r.roe or 0) for r in rows])
        pe_ranks = percentile_rank([1 / max(float(r.pe_ttm or 999), 0.1) for r in rows])
        grw_ranks = percentile_rank([float(r.net_profit_yoy or 0) for r in rows])

    # ── 组装返回 ──
    stocks = []
    for i, row in enumerate(rows):
        if has_snapshot:
            score = round((snapshot_map.get(row.code, 0.5)) * 100, 1)
        else:
            score = round(roe_ranks[i] * 0.4 + pe_ranks[i] * 0.3 + grw_ranks[i] * 0.3, 1)

        stocks.append({
            "code": row.code,
            "name": row.name,
            "industry": row.industry,
            "market": row.market,
            "list_date": row.list_date,
            "pe_ttm": row.pe_ttm,
            "pb": row.pb,
            "turnover_rate": row.turnover_rate,
            "total_mv": row.total_mv,
            "roe": row.roe,
            "revenue_yoy": row.revenue_yoy,
            "net_profit_yoy": row.net_profit_yoy,
            "eps": row.eps,
            "net_mf_amount": row.net_mf_amount,
            "pct_chg": getattr(row, 'pct_chg', None),
            "close": getattr(row, 'bar_close', None),
            "volume": getattr(row, 'volume', None),
            "amount": round(float(bar_amt) / 10, 0) if (bar_amt := getattr(row, 'bar_amount', None)) is not None else None,  # 千元→万元
            "holder_chg": getattr(row, 'holder_num_change_rate', None),
            "score": score,
            "score_source": "factor" if has_snapshot else "basic",
        })

    if sort_by == "score":
        reverse = sort_order != "asc"
        stocks.sort(key=lambda x: x.get("score") or 0, reverse=reverse)

    # ── 标记正股是否有在市可转债 ──
    stock_codes = [s["code"] for s in stocks]
    if stock_codes:
        cb_rows = db.query(
            ConvertibleBondBasic.underlying_code,
            ConvertibleBondBasic.code,
        ).filter(
            ConvertibleBondBasic.underlying_code.in_(stock_codes),
            ConvertibleBondBasic.listed == True,
        ).all()
        cb_map = {r.underlying_code: r.code for r in cb_rows}
        for s in stocks:
            if s["code"] in cb_map:
                s["has_cb"] = True
                s["cb_code"] = cb_map[s["code"]]

    total_pages = math.ceil(total_matched / page_size) if page_size > 0 else 1

    return {
        "stocks": stocks,
        "total": len(stocks),
        "total_matched": total_matched,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "trade_date": str(latest_bar_date) if latest_bar_date else None,
    }


def get_market_regime(db: Session) -> dict:
    """
    大盘市场状态判定。
    三维度综合打分：市场广度(50%) × 主力资金(20%) × 行业强度(30%)
    """
    from models.quant_data import IndustryIndexDaily
    from datetime import date as _date
    from utils.trade_date import get_table_latest_date, get_verified_trade_date

    stock_codes_sq = db.query(StockBasicInfo.code).scalar_subquery()

    # ── 1. 市场广度 ──
    latest_bar_date = db.query(func.max(StockDailyBar.trade_date)).filter(
        StockDailyBar.code.in_(stock_codes_sq)
    ).scalar()
    breadth_score = 50.0
    up_count = down_count = flat_count = 0
    breadth_pct = 50.0

    if latest_bar_date:
        stats = db.query(
            func.count().label('total'),
            func.sum(func.iif(StockDailyBar.pct_chg > 0, 1, 0)).label('up'),
            func.sum(func.iif(StockDailyBar.pct_chg < 0, 1, 0)).label('down'),
            func.sum(func.iif(StockDailyBar.pct_chg == 0, 1, 0)).label('flat'),
            func.round(func.avg(StockDailyBar.pct_chg), 3).label('avg_chg'),
        ).filter(
            StockDailyBar.trade_date == latest_bar_date,
            StockDailyBar.code.in_(stock_codes_sq),
        ).first()

        total = stats.total or 1
        up_count = int(stats.up or 0)
        down_count = int(stats.down or 0)
        flat_count = int(stats.flat or 0)
        breadth_pct = round(up_count / total * 100, 1)
        breadth_score = min(100, max(0, breadth_pct))

    # ── 2. 主力资金 ──
    latest_mf_date_str = get_table_latest_date("money_flow")
    latest_mf_date = _date.fromisoformat(latest_mf_date_str) if latest_mf_date_str else None
    money_score = 50.0
    net_inflow_total = 0

    if latest_mf_date:
        mf = db.query(
            func.round(func.sum(StockMoneyFlow.net_mf_amount), 0),
        ).filter(StockMoneyFlow.trade_date == latest_mf_date).scalar()
        net_inflow_total = float(mf or 0)
        cap = 5000000
        money_score = min(100, max(0, 50 + net_inflow_total / cap * 50))

    # ── 3. 行业强度 ──
    idx_latest_str = get_table_latest_date("industry")
    idx_latest = _date.fromisoformat(idx_latest_str) if idx_latest_str else None
    industry_score = 50.0
    industry_up = industry_down = 0

    if idx_latest:
        idx_stats = db.query(
            func.count().label('total'),
            func.sum(func.iif(IndustryIndexDaily.pct_chg > 0, 1, 0)).label('up'),
            func.sum(func.iif(IndustryIndexDaily.pct_chg < 0, 1, 0)).label('down'),
        ).filter(IndustryIndexDaily.trade_date == idx_latest).first()

        idx_total = idx_stats.total or 1
        industry_up = int(idx_stats.up or 0)
        industry_down = int(idx_stats.down or 0)
        industry_score = min(100, max(0, industry_up / idx_total * 100))

    # ── 综合打分 ──
    composite = breadth_score * 0.5 + money_score * 0.2 + industry_score * 0.3

    if composite >= 60:
        regime, regime_color, regime_icon = "强势", "green", "🟢"
    elif composite >= 40:
        regime, regime_color, regime_icon = "震荡", "amber", "🟡"
    else:
        regime, regime_color, regime_icon = "弱势", "red", "🔴"

    _, data_verified = get_verified_trade_date("stock")

    return {
        "regime": regime, "regime_color": regime_color, "regime_icon": regime_icon,
        "composite_score": round(composite, 1),
        "dimensions": {
            "breadth": {
                "label": "市场广度", "score": round(breadth_score, 1),
                "detail": f"涨{up_count} / 跌{down_count} / 平{flat_count}",
                "pct": breadth_pct,
            },
            "money_flow": {
                "label": "主力资金", "score": round(money_score, 1),
                "detail": f"{'净流入' if net_inflow_total >= 0 else '净流出'} {abs(net_inflow_total/10000):.1f}亿",
                "value": round(net_inflow_total / 10000, 2),
            },
            "industry": {
                "label": "行业强度", "score": round(industry_score, 1),
                "detail": f"涨{industry_up} / 跌{industry_down}",
                "up": industry_up, "down": industry_down,
            },
        },
        "trade_date": str(latest_bar_date) if latest_bar_date else None,
        "data_verified": data_verified,
    }


def get_stock_reversal(db: Session, *, top_n: int = 5) -> dict:
    """
    个股弱转强/强转弱 Top N（相对排名法）。
    基于 5 日均涨幅 vs 今日涨幅排名交叉。
    """
    from utils.trade_date import get_verified_trade_date

    recent_dates = (
        db.query(StockDailyBar.trade_date)
        .distinct()
        .order_by(StockDailyBar.trade_date.desc())
        .limit(6).all()
    )
    if len(recent_dates) < 2:
        return {"weak_to_strong": [], "strong_to_weak": [], "error": "数据不足"}

    today = recent_dates[0][0]
    date_5d_start = recent_dates[-1][0]

    today_rows = db.query(
        StockDailyBar.code, StockDailyBar.pct_chg,
    ).filter(StockDailyBar.trade_date == today).all()
    today_map = {r[0]: float(r[1] or 0) for r in today_rows}

    avg_rows = db.query(
        StockDailyBar.code, func.round(func.avg(StockDailyBar.pct_chg), 3),
    ).filter(
        StockDailyBar.trade_date >= date_5d_start,
        StockDailyBar.trade_date < today,
    ).group_by(StockDailyBar.code).all()
    avg5d_map = {r[0]: float(r[1] or 0) for r in avg_rows}

    stock_code_set = {r[0] for r in db.query(StockBasicInfo.code).all()}
    codes = set(today_map.keys()) & set(avg5d_map.keys()) & stock_code_set
    codes = {c for c in codes if not c.endswith('.BJ')}
    if len(codes) < 50:
        return {"weak_to_strong": [], "strong_to_weak": [], "error": "数据不足"}

    by_5d = sorted(codes, key=lambda c: avg5d_map[c])
    by_today = sorted(codes, key=lambda c: today_map[c], reverse=True)

    total = len(codes)
    threshold = max(1, int(total * 0.2))

    weak_5d_set = set(by_5d[:threshold])
    strong_5d_set = set(by_5d[-threshold:])
    strong_today_set = set(by_today[:threshold])
    weak_today_set = set(by_today[-threshold:])

    w2s_codes = weak_5d_set & strong_today_set
    s2w_codes = strong_5d_set & weak_today_set

    info_map = {}
    if w2s_codes | s2w_codes:
        infos = db.query(
            StockBasicInfo.code, StockBasicInfo.name, StockBasicInfo.industry
        ).filter(StockBasicInfo.code.in_(list(w2s_codes | s2w_codes))).all()
        info_map = {r[0]: {"name": r[1], "industry": r[2]} for r in infos}

    def build_list(code_set, sort_desc=True):
        items = []
        for c in code_set:
            info = info_map.get(c, {})
            items.append({
                "code": c, "name": info.get("name", c),
                "industry": info.get("industry", ""),
                "pct_5d": round(avg5d_map[c], 2),
                "pct_today": round(today_map[c], 2),
                "delta": round(today_map[c] - avg5d_map[c], 2),
            })
        items.sort(key=lambda x: x["delta"], reverse=sort_desc)
        return items[:top_n]

    _, data_verified = get_verified_trade_date("stock")

    return {
        "weak_to_strong": build_list(w2s_codes, sort_desc=True),
        "strong_to_weak": build_list(s2w_codes, sort_desc=False),
        "trade_date": str(today),
        "total_stocks": total,
        "data_verified": data_verified,
    }


def get_industry_heat(db: Session) -> dict:
    """行业热力图（优先行业指数，降级个股均值）。"""
    from models.quant_data import IndustryIndexDaily, SwIndustry
    from utils.trade_date import get_table_latest_date
    from datetime import date as _date

    idx_latest_str = get_table_latest_date("industry")
    idx_latest = _date.fromisoformat(idx_latest_str) if idx_latest_str else None

    bar_latest_str = get_table_latest_date("bars")
    bar_latest = _date.fromisoformat(bar_latest_str) if bar_latest_str else None
    use_index = idx_latest and (not bar_latest or idx_latest >= bar_latest)

    if use_index:
        # ===== 行业指数模式 =====
        rows_1d = db.query(
            IndustryIndexDaily.name, IndustryIndexDaily.pct_chg,
        ).filter(IndustryIndexDaily.trade_date == idx_latest).all()
        heat_l1 = {r[0]: round(float(r[1]), 2) if r[1] is not None else 0.0 for r in rows_1d}

        recent_dates = (
            db.query(IndustryIndexDaily.trade_date).distinct()
            .order_by(IndustryIndexDaily.trade_date.desc()).limit(5).all()
        )
        date_5d_start = recent_dates[-1][0] if recent_dates else idx_latest

        rows_5d = db.query(
            IndustryIndexDaily.name, func.round(func.avg(IndustryIndexDaily.pct_chg), 2),
        ).filter(IndustryIndexDaily.trade_date >= date_5d_start).group_by(IndustryIndexDaily.name).all()
        heat_5d_l1 = {r[0]: float(r[1]) if r[1] is not None else 0.0 for r in rows_5d}

        # 二级行业→一级行业映射
        sub_l1_rows = db.query(
            StockBasicInfo.industry, SwIndustry.sw_l1_name, func.count().label("cnt"),
        ).join(SwIndustry, StockBasicInfo.code == SwIndustry.code).filter(
            StockBasicInfo.industry.isnot(None), SwIndustry.out_date.is_(None),
        ).group_by(StockBasicInfo.industry, SwIndustry.sw_l1_name).all()

        sub_to_l1: dict[str, str] = {}
        sub_to_l1_count: dict[str, int] = {}
        for sub_name, l1_name, cnt in sub_l1_rows:
            if sub_name not in sub_to_l1 or cnt > sub_to_l1_count[sub_name]:
                sub_to_l1[sub_name] = l1_name
                sub_to_l1_count[sub_name] = cnt

        # 反转：SW L1 → Tushare 子行业列表（供前端行业轮动点击时选中对应 checkbox）
        l1_to_subs: dict[str, list[str]] = {}
        for sub_name, l1_name in sub_to_l1.items():
            l1_to_subs.setdefault(l1_name, []).append(sub_name)

        if not sub_to_l1:
            log.warning("sw_industry_empty", hint="申万成分股表为空，热度映射降级为名称精确匹配")

        sub_industries = [r[0] for r in db.query(StockBasicInfo.industry).distinct().all() if r[0]]
        heat = {}
        heat_5d = {}
        for sub in sub_industries:
            if sub in heat_l1:
                heat[sub] = heat_l1[sub]
                heat_5d[sub] = heat_5d_l1.get(sub, 0.0)
            elif sub in sub_to_l1 and sub_to_l1[sub] in heat_l1:
                heat[sub] = heat_l1[sub_to_l1[sub]]
                heat_5d[sub] = heat_5d_l1.get(sub_to_l1[sub], 0.0)

        trade_date = str(bar_latest or idx_latest)
        source = "index"
        sorted_1d = sorted(heat_l1.items(), key=lambda x: x[1], reverse=True)
        sorted_5d = sorted(heat_5d_l1.items(), key=lambda x: x[1], reverse=True)
    else:
        # ===== Fallback: 个股均值模式 =====
        latest_date = bar_latest
        if not latest_date:
            return {"heat": {}, "heat_5d": {}, "rankings": {}, "trade_date": None}

        rows_1d = (
            db.query(StockBasicInfo.industry, func.round(func.avg(StockDailyBar.pct_chg), 2))
            .join(StockDailyBar, and_(
                StockBasicInfo.code == StockDailyBar.code,
                StockDailyBar.trade_date == latest_date,
            )).filter(
                StockBasicInfo.industry != None, StockBasicInfo.industry != "",
                StockBasicInfo.is_active == True,
                ~StockBasicInfo.name.contains("退市"),
            ).group_by(StockBasicInfo.industry).all()
        )
        heat = {r[0]: float(r[1]) if r[1] is not None else 0.0 for r in rows_1d}

        recent_dates = (
            db.query(StockDailyBar.trade_date).distinct()
            .order_by(StockDailyBar.trade_date.desc()).limit(5).all()
        )
        date_5d_start = recent_dates[-1][0] if recent_dates else latest_date

        rows_5d = (
            db.query(StockBasicInfo.industry, func.round(func.avg(StockDailyBar.pct_chg), 2))
            .join(StockDailyBar, and_(
                StockBasicInfo.code == StockDailyBar.code,
                StockDailyBar.trade_date >= date_5d_start,
            )).filter(
                StockBasicInfo.industry != None, StockBasicInfo.industry != "",
                StockBasicInfo.is_active == True,
                ~StockBasicInfo.name.contains("退市"),
            ).group_by(StockBasicInfo.industry).all()
        )
        heat_5d = {r[0]: float(r[1]) if r[1] is not None else 0.0 for r in rows_5d}

        trade_date = str(latest_date)
        source = "avg"
        sorted_1d = sorted(heat.items(), key=lambda x: x[1], reverse=True)
        sorted_5d = sorted(heat_5d.items(), key=lambda x: x[1], reverse=True)

    # top5_5d_sub
    top5_5d_sub = []
    if use_index:
        l1_best_rows = db.query(
            SwIndustry.sw_l1_name, StockBasicInfo.industry, func.count().label("cnt"),
        ).join(SwIndustry, StockBasicInfo.code == SwIndustry.code).filter(
            StockBasicInfo.industry.isnot(None), StockBasicInfo.is_active == True,
            ~StockBasicInfo.name.contains("退市"),
            SwIndustry.out_date.is_(None),
        ).group_by(SwIndustry.sw_l1_name, StockBasicInfo.industry).all()

        l1_to_best_sub: dict[str, str] = {}
        l1_best_count: dict[str, int] = {}
        for l1, sub, cnt in l1_best_rows:
            if l1 not in l1_to_best_sub or cnt > l1_best_count[l1]:
                l1_to_best_sub[l1] = sub
                l1_best_count[l1] = cnt

        seen_subs = set()
        for l1_name, pct in sorted_5d:
            best = l1_to_best_sub.get(l1_name)
            if not best or best in seen_subs:
                continue
            seen_subs.add(best)
            top5_5d_sub.append({"name": best, "pct": round(pct, 2)})
            if len(top5_5d_sub) >= 5:
                break
    else:
        for name, pct in sorted_5d[:5]:
            top5_5d_sub.append({"name": name, "pct": round(pct, 2)})

    rankings = {
        "top3_today": [{"name": n, "pct": v} for n, v in sorted_1d[:3]],
        "bottom3_today": [{"name": n, "pct": v} for n, v in sorted_1d[-3:]],
        "top3_5d": [{"name": n, "pct": v} for n, v in sorted_5d[:3]],
        "bottom3_5d": [{"name": n, "pct": v} for n, v in sorted_5d[-3:]],
        "top5_5d_sub": top5_5d_sub,
    }

    return {
        "heat": heat, "heat_5d": heat_5d, "rankings": rankings,
        "l1_to_subs": l1_to_subs if use_index else {},
        "trade_date": trade_date, "date_5d_start": str(date_5d_start),
        "source": source,
    }


def get_stock_to_etf(db: Session, *, code: str) -> dict:
    """个股→申万一级行业→同行业 ETF 反向联动。"""
    from models.quant_data import SwIndustry, EtfBasicInfo, EtfDailyBar

    ts_code = code.strip()
    if "." not in ts_code:
        from utils.asset_type import to_ts_code
        ts_code = to_ts_code(ts_code)

    sw = db.query(SwIndustry).filter(SwIndustry.code == ts_code).first()
    if not sw:
        stock = db.query(StockBasicInfo).filter(StockBasicInfo.code == ts_code).first()
        if not stock or not stock.industry:
            return {"code": code, "industry": None, "etfs": [], "message": "未找到行业分类"}
        sub_ind = stock.industry
        etf_ind = db.query(EtfBasicInfo.industry).filter(
            EtfBasicInfo.industry == sub_ind).first()
        if etf_ind:
            industry_name = sub_ind
        else:
            all_etf_inds = [r[0] for r in db.query(EtfBasicInfo.industry).filter(
                EtfBasicInfo.industry.isnot(None)).distinct().all()]
            industry_name = None
            for ei in all_etf_inds:
                if sub_ind in ei or ei in sub_ind or sub_ind[:2] in ei:
                    industry_name = ei
                    break
            if not industry_name:
                return {"code": code, "industry": sub_ind, "etfs": [],
                        "message": f"行业「{sub_ind}」暂无对应ETF，同步申万数据后可精确匹配"}
    else:
        industry_name = sw.sw_l1_name

    # 精确匹配无 ETF 时，降级模糊匹配（如"石油石化"→"基础化工"）
    exact_count = db.query(func.count(EtfBasicInfo.code)).filter(
        EtfBasicInfo.industry == industry_name,
        EtfBasicInfo.is_active == True,
    ).scalar() or 0
    if exact_count == 0:
        all_etf_inds = [r[0] for r in db.query(EtfBasicInfo.industry).filter(
            EtfBasicInfo.industry.isnot(None)).distinct().all()]
        for ei in all_etf_inds:
            if (len(industry_name) >= 3 and industry_name[:3] in ei) or ei in industry_name:
                industry_name = ei
                break

    etfs = db.query(EtfBasicInfo).filter(
        EtfBasicInfo.industry == industry_name,
        EtfBasicInfo.is_active == True,
    ).all()

    etf_list = []
    for e in etfs:
        latest = db.query(EtfDailyBar).filter(
            EtfDailyBar.code == e.code
        ).order_by(EtfDailyBar.trade_date.desc()).first()
        etf_list.append({
            "code": e.code, "name": e.name, "category": e.category,
            "close": round(float(latest.close), 2) if latest and latest.close is not None else None,
            "pct_chg": round(float(latest.pct_chg), 2) if latest and latest.pct_chg is not None else None,
            "amount": round(float(latest.amount), 0) if latest and latest.amount is not None else None,
        })

    etf_list.sort(key=lambda x: x["amount"] or 0, reverse=True)

    # 按名称核心词去重（去掉基金公司后缀如"华夏/广发/富国"），每类只保留成交额最大的
    import re
    def _etf_core_name(name: str, code: str) -> str:
        """提取 ETF 核心名称：'工程机械ETF华夏' → '工程机械ETF'"""
        if not name:
            return code  # name 为空时用 code（唯一）兜底
        m = re.match(r'(.+?ETF)', name)
        return m.group(1) if m else name[:4]

    seen_cores: set[str] = set()
    deduped = []
    for e in etf_list:
        core = _etf_core_name(e["name"] or "", e["code"])
        if core in seen_cores:
            continue
        seen_cores.add(core)
        deduped.append(e)
    etf_list = deduped[:5]

    sw_count = db.query(func.count(SwIndustry.code)).filter(
        SwIndustry.sw_l1_name == industry_name,
        SwIndustry.out_date.is_(None),
    ).scalar() or 0

    return {
        "code": code, "industry": industry_name,
        "stock_count": sw_count, "etfs": etf_list,
    }


# ══════════════════ 批量事件标签 ══════════════════

def get_event_tags(db: Session, codes: list) -> dict:
    """
    批量查询近5日事件标签 + 融资余额趋势。

    Returns:
        {code: {block: bool, unlock: bool, top: bool, margin_up: bool|None}}
    """
    if not codes:
        return {}

    _EVENT_WINDOW_DAYS = 8
    cutoff = _date_cls.today() - timedelta(days=_EVENT_WINDOW_DAYS)

    # 事件标签：查询近期结构化事件
    event_rows = db.query(
        StockNews.code,
        StockNews.event_type,
    ).filter(
        StockNews.code.in_(codes),
        StockNews.event_type.in_(['大宗交易', '解禁', '龙虎榜']),
        StockNews.publish_time >= cutoff,
    ).all()

    # 构建 code→事件集合
    code_events = {}
    for code, etype in event_rows:
        if code not in code_events:
            code_events[code] = set()
        code_events[code].add(etype)

    # 融资余额趋势：最新日 vs N日前
    latest_margin_date = db.query(func.max(StockMarginData.trade_date)).scalar()
    margin_map = {}
    if latest_margin_date:
        old_margin_date = db.query(StockMarginData.trade_date).filter(
            StockMarginData.trade_date <= latest_margin_date - timedelta(days=_EVENT_WINDOW_DAYS)
        ).order_by(StockMarginData.trade_date.desc()).limit(1).scalar()
        if old_margin_date:
            m_new = aliased(StockMarginData, name='m_new')
            m_old = aliased(StockMarginData, name='m_old')
            margin_rows = db.query(
                m_new.code,
                m_new.rzye,
                m_old.rzye,
            ).join(
                m_old, and_(m_new.code == m_old.code, m_old.trade_date == old_margin_date)
            ).filter(
                m_new.code.in_(codes),
                m_new.trade_date == latest_margin_date,
                m_old.rzye > 0,
            ).all()
            for code, rzye_new, rzye_old in margin_rows:
                if rzye_new is not None and rzye_old is not None and rzye_old > 0:
                    margin_map[code] = rzye_new > rzye_old

    # 合并结果：只返回有标签的 code
    result = {}
    all_tagged_codes = set(code_events.keys()) | set(margin_map.keys())
    for code in all_tagged_codes:
        events = code_events.get(code, set())
        result[code] = {
            "block": "大宗交易" in events,
            "unlock": "解禁" in events,
            "top": "龙虎榜" in events,
            "margin_up": margin_map.get(code),
        }

    return result
