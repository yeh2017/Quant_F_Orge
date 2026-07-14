"""
ETF 基础信息 & 日线同步
========================
sync_etf_basic()  — 拉取场内 ETF 列表（Tushare fund_basic）
sync_etf_daily()  — 拉取 ETF 日线写入 EtfDailyBar（独立表）
"""

import structlog
import pandas as pd
from datetime import date, datetime
from typing import Optional

from core.database import db_session
from models.quant_data import EtfBasicInfo, EtfDailyBar
from data_sources.tushare_source import TushareSource

log = structlog.get_logger("sync_etf")

# ── ETF 分类规则 ──

_CATEGORY_KEYWORDS = {
    "可转债":  ["转债"],
    "REITs":  ["REITs", "REIT", "不动产", "公募基础设施"],
    "跨境":   ["纳斯达克", "纳指", "标普", "日经", "德国", "法国", "恒生",
              "港股", "H股", "巴西", "印度", "越南", "东南亚", "亚太",
              "QDII", "美国", "全球", "沙特", "韩国", "英国"],
    "商品":   ["黄金", "白银", "原油", "豆粕", "期货", "能源化工", "上海金"],
    "行业":   ["医药", "消费", "科技", "芯片", "半导体", "新能源", "光伏",
              "军工", "银行", "证券", "保险", "地产", "钢铁", "煤炭",
              "白酒", "食品", "农业", "汽车", "传媒", "通信", "电力",
              "基建", "环保", "人工智能", "数据", "云计算", "游戏",
              "券商", "医疗", "生物", "化工", "机械", "电子", "计算机",
              "5G", "碳中和", "稀土", "锂电", "有色",
              # 补充遗漏的行业关键词
              "石油", "家电", "软件", "养殖", "畜牧", "粮食", "农牧",
              "家居", "电池", "机器人", "建材", "纺织", "旅游", "酿酒",
              "水利", "交运", "物流", "航空", "船舶", "港口", "铁路",
              "影视", "教育", "体育", "零售"],
    "主题":   ["红利", "价值", "成长", "创新", "ESG", "央企", "国企",
              "民企", "龙头", "低碳", "绿色", "新质", "智能", "数字经济",
              "养老", "量化", "增强", "战略", "互联网", "一带一路",
              "国潮", "专精特新", "北交所", "现金流"],
}

# 宽基指数白名单（名称含这些关键词才是真正的宽基指数 ETF）
_BROAD_INDEX_KEYWORDS = [
    "沪深300", "中证500", "中证800", "中证1000", "中证2000",
    "上证50", "上证180", "上证380",
    "中证A50", "中证A500", "中证A100",
    "深证100", "深证成指", "创业板",
    "科创50", "科创100", "科创200", "北证50",
    "MSCI", "中证全指", "万得全A", "国证2000",
]

# 排除的分类（债券/货币型不纳入）
_EXCLUDED_TYPES = {"货币", "债券", "混合"}

# 排除的基金名称关键词（LOF/FOF/封闭式/定开的不是场内 ETF）
_EXCLUDED_NAME_KW = ["LOF", "FOF", "定开", "封闭"]


# ETF 名称关键词→股票行业名映射
_ETF_INDUSTRY_MAP = {
    '医药': '医药生物', '医疗': '医药生物', '生物': '医药生物',
    '芯片': '电子', '半导体': '电子', '电子': '电子',
    '银行': '银行', '证券': '非银金融', '券商': '非银金融', '保险': '非银金融',
    '军工': '国防军工', '新能源': '电力设备', '光伏': '电力设备',
    '钢铁': '钢铁', '煤炭': '煤炭', '白酒': '食品饮料', '酿酒': '食品饮料',
    '食品': '食品饮料', '消费': '商贸零售', '零售': '商贸零售', '汽车': '汽车',
    '传媒': '传媒', '影视': '传媒', '通信': '通信', '电力': '公用事业',
    '地产': '房地产', '化工': '基础化工', '机械': '机械设备',
    '计算机': '计算机', '人工智能': '计算机', '云计算': '计算机', '软件': '计算机',
    '农业': '农林牧渔', '养殖': '农林牧渔', '畜牧': '农林牧渔', '农牧': '农林牧渔',
    '粮食': '农林牧渔', '环保': '环保', '稀土': '有色金属', '有色': '有色金属', '锂电': '电力设备',
    '电池': '电力设备', '游戏': '传媒', '科技': '计算机', '基建': '建筑装饰',
    '家电': '家用电器', '家居': '家用电器', '建材': '建筑材料',
    '石油': '石油石化', '纺织': '纺织服饰', '旅游': '社会服务',
    '机器人': '机械设备', '船舶': '国防军工', '航空': '交通运输',
    '交运': '交通运输', '物流': '交通运输', '港口': '交通运输', '铁路': '交通运输',
    '碳中和': '环保', '大数据': '计算机', '5G': '通信', '体育': '社会服务',
}


def _map_etf_industry(name: str) -> str:
    """根据 ETF 名称关键词映射到股票行业（仅行业 ETF 有值）"""
    if not name:
        return None
    for kw, industry in _ETF_INDUSTRY_MAP.items():
        if kw in name:
            return industry
    return None


def _classify_etf(name: str, fund_type: str) -> str:
    """根据 ETF 名称和类型自动分类"""
    if not name:
        return "其他"
    # 1. 优先匹配确定性高的分类（可转债 > REITs > 跨境 > 商品 > 行业）
    for category in ("可转债", "REITs", "跨境", "商品", "行业"):
        for kw in _CATEGORY_KEYWORDS[category]:
            if kw in name:
                return category
    # 2. 宽基白名单优先于主题（避免"沪深300增强ETF"被误分到主题）
    if fund_type and "股票" in fund_type:
        for kw in _BROAD_INDEX_KEYWORDS:
            if kw in name:
                return "宽基"
    # 3. 主题关键词
    for kw in _CATEGORY_KEYWORDS["主题"]:
        if kw in name:
            return "主题"
    # 4. 兜底：股票型归主题，其余归其他
    if fund_type and "股票" in fund_type:
        return "主题"
    return "其他"


# ── 二级分类规则（每个一级分类下的子分类关键词）──
_SUB_CATEGORY_RULES = {
    "跨境": [
        ("港股", ["港股", "恒生", "H股", "香港"]),
        ("美股", ["纳斯达克", "纳指", "标普", "美国", "道琼斯"]),
        ("日韩", ["日经", "韩国", "韩交所", "TOPIX"]),
        ("欧洲", ["德国", "DAX", "法国", "英国"]),
        ("新兴市场", ["巴西", "印度", "越南", "东南亚", "亚太", "沙特", "亚洲"]),
        ("中国海外", ["海外中国", "全球中国", "中国互联网"]),
    ],
    "宽基": [
        ("沪深300", ["沪深300"]),
        ("中证500", ["中证500"]),
        ("中证1000", ["中证1000"]),
        ("中证2000", ["中证2000", "国证2000"]),
        ("上证50", ["上证50"]),
        ("中证A500", ["中证A500", "中证A50"]),
        ("中证A100", ["中证A100", "A100"]),
        ("创业板", ["创业板"]),
        ("科创板", ["科创50", "科创100", "科创200"]),
        ("中证800", ["中证800"]),
        ("上证180", ["上证180"]),
        ("深证100", ["深证100"]),
        ("上证380", ["上证380"]),
        ("MSCI", ["MSCI"]),
        ("全指", ["全指"]),
        ("自由现金流", ["自由现金流"]),
    ],
    "商品": [
        ("贵金属", ["黄金", "白银", "上海金"]),
        ("能源", ["原油", "能源化工"]),
        ("工业品", ["期货", "豆粕"]),
    ],
    # REITs/可转债不设二级分类：数量少（REITs ~87, 可转债 ~3），无需细分。
    "主题": [
        ("红利", ["红利", "高股息"]),
        ("ESG", ["ESG", "绿色", "低碳", "碳中和", "可持续", "社会责任"]),
        ("央企国企", ["央企", "国企", "国有企业", "民企"]),
        ("科创", ["科创", "创新", "专精特新", "战略新兴"]),
        ("增强", ["增强", "量化"]),
        ("价值成长", ["价值", "成长"]),
        ("新材料", ["新材料", "稀有金属", "稀土"]),
        ("智能制造", ["智能制造", "工业互联网", "机床", "装备", "工业4.0", "电网"]),
        ("数字经济", ["数字经济", "信息安全", "物联网", "车联网", "虚拟现实", "移动互联网", "互联网"]),
        ("资源能源", ["油气", "石化", "大宗商品", "能源", "自然资源"]),
        ("区域", ["一带一路", "长三角", "大湾区", "长江保护", "成渝", "湖北", "杭州湾", "浙江", "G60"]),
        ("中药", ["中药"]),
        ("沪港深", ["沪港深"]),
        ("基本面", ["基本面", "核心竞争力", "锐联", "民族品牌"]),
        ("现金流", ["自由现金流", "现金流"]),
        ("医药健康", ["制药", "健康", "养老"]),
        ("消费", ["酒", "小康"]),
        ("卫星国防", ["卫星", "国防", "军工"]),
        ("电信", ["电信"]),
        ("综合指数", ["综合", "综指", "成份", "成指", "大盘", "中盘",
                   "深证50", "上证580", "A股", "中创400", "A50",
                   "央视财经", "运输", "交通", "深证300", "主板",
                   "中小企业"]),
    ],
}


def _sub_classify_etf(name: str, category: str) -> str:
    """根据名称和一级分类推导二级分类"""
    if not name or category not in _SUB_CATEGORY_RULES:
        return None
    for sub_name, keywords in _SUB_CATEGORY_RULES[category]:
        for kw in keywords:
            if kw in name:
                return sub_name
    return None


def sync_etf_basic(task_id: Optional[str] = None) -> int:
    """同步场内 ETF 基础信息"""
    log.info("sync_etf_basic_start")
    try:
        ts = TushareSource()
        import data_sources.tushare_source as tushare_module

        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _fetch():
            return ts.pro.fund_basic(
                market="E",  # E=场内
                status="L",  # L=上市
                fields="ts_code,name,fund_type,management,benchmark,list_date",
            )

        df = _fetch()
        if df is None or df.empty:
            log.warning("etf_basic_empty")
            return 0

        # 只保留 ETF（排除 LOF、封闭式等）
        df = df[df["ts_code"].str.contains(r"^\d{6}\.(?:SH|SZ)$", regex=True, na=False)]

        # 过滤掉排除的基金类型（但保留名称含"转债"的可转债 ETF）
        _exclude_pattern = "|".join(_EXCLUDED_TYPES)
        _excluded_mask = df["fund_type"].str.contains(_exclude_pattern, na=False)
        _bond_etf_whitelist = df["name"].str.contains("转债", na=False)
        df = df[~_excluded_mask | _bond_etf_whitelist]

        # 排除 LOF/FOF/定开/封闭等非 ETF 基金
        for kw in _EXCLUDED_NAME_KW:
            df = df[~df["name"].str.contains(kw, na=False)]

        records = []
        for _, row in df.iterrows():
            name = row.get("name", "") or ""
            fund_type = row.get("fund_type", "") or ""
            raw_date = pd.to_datetime(row.get("list_date"), format="%Y%m%d", errors="coerce")
            list_date_str = raw_date.strftime("%Y-%m-%d") if pd.notna(raw_date) else None

            category = _classify_etf(name, fund_type)
            records.append({
                "code": row["ts_code"],
                "name": name,
                "fund_type": fund_type,
                "management": row.get("management", ""),
                "benchmark": row.get("benchmark", ""),
                "list_date": list_date_str,
                "category": category,
                "industry": _map_etf_industry(name) if category == "行业" else None,
                # 行业 ETF 用 industry 作为 sub_category，其他用规则表推导
                "sub_category": _map_etf_industry(name) if category == "行业" else _sub_classify_etf(name, category),
                # “其他”分类不展示；未上市（list_date 为空或未来）也标为非活跃
                "is_active": category != "其他" and bool(list_date_str) and list_date_str <= date.today().isoformat(),
            })

        from sqlalchemy import text as sa_text
        from settings import WRITE_BATCH_SIZE
        BATCH = WRITE_BATCH_SIZE
        with db_session() as db:
            db.execute(sa_text("DELETE FROM etf_basic_info"))
            db.flush()
            for i in range(0, len(records), BATCH):
                db.bulk_insert_mappings(EtfBasicInfo, records[i:i + BATCH])
            db.flush()

        count = len(records)
        log.info("sync_etf_basic_done", count=count)

        # 刷新 bar_query 的 ETF 代码缓存
        try:
            from utils.bar_query import refresh_etf_cache
            refresh_etf_cache()
        except Exception:
            pass

        if task_id:
            from utils.task_store import task_store, TaskStatus
            task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                "progress": 100,
                "message": f"ETF 列表同步完成: {count} 只",
            })

        return count

    except Exception as e:
        log.error("sync_etf_basic_failed", error=str(e))
        if task_id:
            from utils.task_store import task_store, TaskStatus
            task_store.update_task(task_id, TaskStatus.FAILED, error=str(e))
        return 0


def sync_etf_daily(task_id: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, force_refill: bool = False) -> int:
    """
    同步 ETF 日线到 EtfDailyBar（按交易日遍历，每日1次API调用）。
    架构与 sync_bond_history 一致：bdate_range + 水位增量。
    """
    import time
    log.info("sync_etf_daily_start")
    try:
        ts = TushareSource()
        import data_sources.tushare_source as tushare_module

        with db_session() as db:
            etf_codes = set(
                r[0] for r in db.query(EtfBasicInfo.code).filter(EtfBasicInfo.is_active == True).all()
            )
        if not etf_codes:
            log.warning("no_etf_to_sync")
            return 0

        if not end_date:
            from utils.trade_date import resolve_end_date
            end_date = resolve_end_date(fmt="%Y%m%d")
        if not start_date:
            from datetime import timedelta
            start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
            log.warning("etf_daily_no_start_date", fallback=start_date)

        # ── 水位增量（force_refill 时跳过）──
        actual_start = start_date
        if force_refill:
            log.info("etf_daily_force_refill", start_date=start_date)
        else:
            from jobs.sync_base import calc_next_start
            actual_start = calc_next_start("etf_daily", "all", start_date)

        if actual_start > end_date:
            log.info("etf_daily_already_up_to_date",
                     start=actual_start, end=end_date)
            if task_id:
                from utils.task_store import task_store, TaskStatus
                task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                    "progress": 100, "message": "ETF 日线已是最新",
                })
            return 0

        # ── 按真实交易日遍历（trade_cal 跳过节假日） ──
        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _fetch_trade_cal():
            return ts.pro.trade_cal(
                start_date=actual_start, end_date=end_date, is_open="1"
            )

        df_cal = _fetch_trade_cal()
        if df_cal is not None and not df_cal.empty:
            trade_dates = sorted(df_cal["cal_date"].tolist())
        else:
            # fallback: bdate_range 仅跳周末
            date_range = pd.bdate_range(start=actual_start, end=end_date, freq="B")
            trade_dates = [d.strftime("%Y%m%d") for d in date_range]
        total_days = len(trade_dates)

        if total_days == 0:
            log.info("etf_daily_no_trade_days", start=actual_start, end=end_date)
            if task_id:
                from utils.task_store import task_store, TaskStatus
                task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                    "progress": 100, "message": "无待同步交易日",
                })
            return 0

        log.info("sync_etf_daily_date_range", days=total_days,
                 start=actual_start, end=end_date)

        t0 = time.time()
        total_rows = 0
        for day_idx, trade_date_str in enumerate(trade_dates, 1):
            try:
                @tushare_module.with_tushare_retry(max_retries=2, delay=0.5)
                def _fetch_daily(td=trade_date_str):
                    return ts.pro.fund_daily(
                        trade_date=td,
                        fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
                    )

                df = _fetch_daily()
                if df is None or df.empty:
                    continue

                # 只保留我们跟踪的 ETF
                df = df[df["ts_code"].isin(etf_codes)]
                if df.empty:
                    continue

                records = []
                trade_date_val = pd.to_datetime(trade_date_str, format="%Y%m%d").date()
                for _, row in df.iterrows():
                    records.append({
                        "code": row["ts_code"],
                        "trade_date": trade_date_val,
                        "open": row.get("open"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "close": row.get("close"),
                        "pre_close": row.get("pre_close"),
                        "change": row.get("change"),
                        "pct_chg": row.get("pct_chg"),
                        "volume": row.get("vol"),
                        "amount": row.get("amount"),
                    })

                if records:
                    from sqlalchemy import text as sa_text
                    with db_session() as db:
                        # 先删当天数据再插入
                        db.execute(sa_text(
                            "DELETE FROM etf_daily_bars WHERE trade_date=:td"
                        ), {"td": trade_date_val})
                        db.bulk_insert_mappings(EtfDailyBar, records)

                total_rows += len(records)

                if task_id:
                    from utils.task_store import task_store, TaskStatus
                    task_store.update_task(task_id, TaskStatus.IN_PROGRESS, result={
                        "progress": round(day_idx / total_days * 100),
                        "message": f"ETF 日线: {day_idx}/{total_days} 天, {total_rows} 条",
                    })

                # Tushare 限频
                time.sleep(0.3)

            except Exception as e:
                log.warning("etf_daily_day_failed",
                            trade_date=trade_date_str, error=str(e))
                continue

        log.info("sync_etf_daily_done", total_rows=total_rows, days=total_days)

        # ── 写入显式水位（取 DB 实际最新日期，与 bars 对齐）──
        from jobs.sync_base import write_watermark
        try:
            from sqlalchemy import text as sa_text
            with db_session() as _db:
                _r = _db.execute(sa_text(
                    "SELECT MAX(trade_date) FROM etf_daily_bars"
                )).fetchone()
                actual_max = str(_r[0]).replace("-", "")[:8] if _r and _r[0] else end_date
        except Exception:
            actual_max = end_date
        write_watermark(
            data_type="etf_daily", mode="all",
            last_sync_date=actual_max, t_start=t0,
            status="success" if total_rows > 0 else "empty",
        )

        if task_id:
            from utils.task_store import task_store, TaskStatus
            task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                "progress": 100,
                "message": f"ETF 日线同步完成: {total_days} 天, {total_rows} 条",
            })

        return total_rows

    except Exception as e:
        log.error("sync_etf_daily_failed", error=str(e))
        from jobs.sync_base import write_watermark
        write_watermark(
            data_type="etf_daily", mode="all",
            last_sync_date=end_date or "", t_start=time.time(),
            status="failed", error_msg=str(e),
        )
        if task_id:
            from utils.task_store import task_store, TaskStatus
            task_store.update_task(task_id, TaskStatus.FAILED, error=str(e))
        return 0

