from sqlalchemy import Column, String, Integer, Float, Date, Index, Text, DateTime, Boolean
from sqlalchemy.sql import func
from core.database import Base

class StockDailyBar(Base):
    """
    股票日线行情表 (本地化存储)
    用于彻底消除网络请求，支持极速回测
    """
    __tablename__ = "stock_daily_bars"

    # 使用联合主键或独立自增ID皆可，这里考虑到查询习惯用联合主键更严谨
    # 联合PK自动创建 sqlite_autoindex (code, trade_date)，不需要额外 index=True
    code = Column(String(20), primary_key=True, comment="股票代码 (如 000001.SZ)")
    trade_date = Column(Date, primary_key=True, comment="交易日期")
    
    open = Column(Float, comment="开盘价")
    high = Column(Float, comment="最高价")
    low = Column(Float, comment="最低价")
    close = Column(Float, comment="收盘价")
    pre_close = Column(Float, comment="昨收价")
    
    change = Column(Float, comment="涨跌额")
    pct_chg = Column(Float, comment="涨跌幅")
    
    volume = Column(Float, comment="成交量(手)")
    amount = Column(Float, comment="成交额(千元)")
    
    # 复权因子备用字段
    adj_factor = Column(Float, nullable=True, comment="复权因子")

    # 仅保留 trade_date 单列索引，用于按日期查全市场截面
    __table_args__ = (
        Index('idx_bars_trade_date', 'trade_date'),
    )

class StockDailyFactor(Base):
    """
    股票每日横截面因子/基本面数据表
    用于提速因子计算和多因子选股
    """
    __tablename__ = "stock_daily_factors"

    # 联合PK自动创建 sqlite_autoindex，不需要额外 index=True
    code = Column(String(20), primary_key=True)
    trade_date = Column(Date, primary_key=True)
    
    # 常用基本面因子 (Tushare daily_basic / BakBasic)
    turnover_rate = Column(Float, nullable=True, comment="换手率(%)")
    turnover_rate_f = Column(Float, nullable=True, comment="换手率(自由流通股)(%)")
    volume_ratio = Column(Float, nullable=True, comment="量比")
    pe = Column(Float, nullable=True, comment="市盈率")
    pe_ttm = Column(Float, nullable=True, comment="市盈率TTM")
    pb = Column(Float, nullable=True, comment="市净率")
    ps = Column(Float, nullable=True, comment="市销率")
    ps_ttm = Column(Float, nullable=True, comment="市销率TTM")
    dv_ratio = Column(Float, nullable=True, comment="股息率(%)")
    dv_ttm = Column(Float, nullable=True, comment="股息率TTM(%)")
    total_mv = Column(Float, nullable=True, comment="总市值(万元)")
    circ_mv = Column(Float, nullable=True, comment="流通市值(万元)")

    # 仅保留 trade_date 单列索引
    __table_args__ = (
        Index('idx_factors_trade_date', 'trade_date'),
    )

class FactorSnapshot(Base):
    """
    因子打分快照表
    缓存 FactorService.calculate_factors() 的结果，避免每次全量重算。
    按 (code + trade_date + strategy_type) 唯一存储。
    """
    __tablename__ = "factor_snapshot"

    code = Column(String(20), primary_key=True, comment="股票代码")
    trade_date = Column(Date, primary_key=True, comment="计算基准日期")
    strategy_type = Column(String(30), primary_key=True, default="default", comment="策略类型标识")
    composite = Column(Float, comment="综合因子分")
    rank = Column(Integer, nullable=True, comment="全市场排名")
    factors_json = Column(Text, nullable=True, comment="各因子明细 JSON")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_snapshot_date_strategy', 'trade_date', 'strategy_type'),
    )


class IndustryIndexDaily(Base):
    """
    申万一级行业指数日线（31 个行业）
    数据来源：Tushare index_daily（801010.SI ~ 801890.SI）
    """
    __tablename__ = "industry_index_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, comment="指数代码 (如 801010.SI)")
    name = Column(String(50), nullable=True, comment="行业名称 (如 农林牧渔)")
    trade_date = Column(Date, nullable=False, comment="交易日 (YYYY-MM-DD)")
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True, comment="收盘点位")
    pct_chg = Column(Float, nullable=True, comment="涨跌幅(%)")
    vol = Column(Float, nullable=True, comment="成交量(手)")
    amount = Column(Float, nullable=True, comment="成交额(千元)")

    __table_args__ = (
        Index('idx_ind_index_code_date', 'code', 'trade_date', unique=True),
        Index('idx_ind_index_date', 'trade_date'),
    )


class StockBasicInfo(Base):
    """
    股票静态信息表 (代码/名称/行业/市场)
    通过 ETL 定期从 Tushare stock_basic 同步，消除运行时 API 调用
    """
    __tablename__ = "stock_basic_info"

    code = Column(String(20), primary_key=True, comment="股票代码 (如 000001.SZ)")
    name = Column(String(50), comment="股票名称")
    industry = Column(String(50), nullable=True, comment="所属行业")
    market = Column(String(20), nullable=True, comment="市场 (主板/中小板/创业板/科创板)")
    list_date = Column(String(10), nullable=True, comment="上市日期 (如 2020-01-01)")
    delist_date = Column(String(10), nullable=True, comment="退市日期 (如 2024-06-01)，NULL=在市")
    is_active = Column(Boolean, default=True, comment="是否在市 (排除退市股)")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="最后更新时间")


class StockFinancial(Base):
    """
    财务指标表 (ROE/毛利率/营收同比等)
    通过 ETL 定期从 Tushare fina_indicator + cashflow + balancesheet 同步
    """
    __tablename__ = "stock_financials"

    code = Column(String(20), primary_key=True, comment="股票代码")
    report_date = Column(Date, primary_key=True, comment="报告期 (如 2024-12-31)")

    roe = Column(Float, nullable=True, comment="净资产收益率(%)")
    roa = Column(Float, nullable=True, comment="总资产收益率(%)")
    gross_profit_margin = Column(Float, nullable=True, comment="毛利率(%)")
    net_profit_margin = Column(Float, nullable=True, comment="净利率(%)")
    revenue_yoy = Column(Float, nullable=True, comment="营收同比增长率(%)")
    net_profit_yoy = Column(Float, nullable=True, comment="净利润同比增长率(%)")
    eps = Column(Float, nullable=True, comment="每股收益(元)")
    # P0 扩列：质量因子增强
    cashflow_oper = Column(Float, nullable=True, comment="经营活动现金流净额(元)")
    debt_to_assets = Column(Float, nullable=True, comment="资产负债率(%)")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index('idx_financial_code_date', 'code', 'report_date'),
    )


class IndexWeight(Base):
    """
    指数成分权重（沪深300/中证500/中证1000）
    月末更新，用于 universe 筛选和 benchmark 对比
    来源: Tushare index_weight（需 2000 积分）
    """
    __tablename__ = "index_weight"

    index_code = Column(String(20), primary_key=True, comment="指数代码 (如 399300.SZ)")
    con_code = Column(String(20), primary_key=True, comment="成分股代码 (如 000001.SZ)")
    trade_date = Column(Date, primary_key=True, comment="月末日期")
    weight = Column(Float, nullable=True, comment="权重(%)")

    __table_args__ = (
        Index('idx_iw_con_code', 'con_code'),
        Index('idx_iw_date', 'trade_date'),
    )


class StockMarginData(Base):
    """
    融资融券明细（个股级）
    来源: Tushare margin_detail(trade_date=xxx) 按日拉全市场
    用途: 杠杆情绪因子（margin_ratio = rzye / circ_mv，运行时计算）
    """
    __tablename__ = "stock_margin_data"

    code = Column(String(20), primary_key=True, comment="股票代码")
    trade_date = Column(Date, primary_key=True, comment="交易日期")

    rzye = Column(Float, nullable=True, comment="融资余额（元）")
    rzmre = Column(Float, nullable=True, comment="融资买入额（元）")
    rqye = Column(Float, nullable=True, comment="融券余额（元）")
    rzrqye = Column(Float, nullable=True, comment="融资融券余额合计（元）")

    __table_args__ = (
        Index('idx_margin_date', 'trade_date'),
    )


class StockMoneyFlow(Base):
    """
    资金流向日表
    用于聪明钱因子计算和智能选股器「主力净流入」筛选
    来源: Tushare moneyflow(trade_date=xxx) 全市场批量
    """
    __tablename__ = "stock_money_flow"

    code = Column(String(20), primary_key=True, comment="股票代码")
    trade_date = Column(Date, primary_key=True, comment="交易日期")

    buy_lg_amount = Column(Float, nullable=True, comment="大单买入额(万)")
    sell_lg_amount = Column(Float, nullable=True, comment="大单卖出额(万)")
    buy_elg_amount = Column(Float, nullable=True, comment="特大单买入额(万)")
    sell_elg_amount = Column(Float, nullable=True, comment="特大单卖出额(万)")
    net_mf_amount = Column(Float, nullable=True, comment="净主力流入额(万)")

    # 联合PK自动创建 sqlite_autoindex (code, trade_date)，不需要额外的 (code, trade_date) 索引
    # 仅保留 trade_date 单列索引，用于按日期查全市场截面
    __table_args__ = (
        Index('idx_mf_trade_date', 'trade_date'),
    )



class StockShareholderCount(Base):
    """
    股东户数表
    用于情绪反转因子（筹码集中度）
    来源: Tushare stk_holdernumber (600积分) / AkShare
    """
    __tablename__ = "stock_shareholder_count"

    code = Column(String(20), primary_key=True, comment="股票代码")
    end_date = Column(Date, primary_key=True, comment="截止日期")

    holder_num = Column(Integer, nullable=True, comment="股东户数")
    holder_num_change_rate = Column(Float, nullable=True, comment="增减比例(%)")

    __table_args__ = (
        Index('idx_shareholder_code_date', 'code', 'end_date'),
    )


class SyncWatermark(Base):
    """
    同步水位表
    记录每种数据类型最后一次成功同步的状态，
    供 /status API 展示和增量同步决策使用。
    """
    __tablename__ = "sync_watermark"

    # 数据类型: bars / factors / financials / sentiment / stock_basic
    data_type = Column(String(32), primary_key=True, comment="数据类型")
    # 股票池模式: all / hs300 / zz500 / pool
    mode = Column(String(16), primary_key=True, comment="同步模式")

    last_sync_date = Column(Date, nullable=True, comment="最后同步的数据日期")
    last_run_at = Column(DateTime, nullable=True, comment="最后一次执行开始时间")
    last_done_at = Column(DateTime, nullable=True, comment="最后一次执行完成时间")
    duration_seconds = Column(Float, nullable=True, comment="耗时(秒)")
    status = Column(String(16), default="unknown", comment="success / failed / running")
    error_msg = Column(Text, nullable=True, comment="失败时的错误信息")

    __table_args__ = (
        Index('idx_watermark_type_mode', 'data_type', 'mode'),
    )


class ConvertibleBondBasic(Base):
    """
    可转债基本信息表
    通过 sync_bond_basic 同步到本地，供可转债池搜索/验证使用。
    """
    __tablename__ = "convertible_bond_basic"

    code = Column(String(16), primary_key=True, comment="可转债代码，如 113050")
    name = Column(String(64), nullable=True, comment="可转债名称")
    underlying_code = Column(String(16), nullable=True, comment="正股代码")
    underlying_name = Column(String(64), nullable=True, comment="正股名称")
    rating = Column(String(8), nullable=True, comment="债券评级")
    issue_date = Column(Date, nullable=True, comment="发行日期")
    mature_date = Column(Date, nullable=True, comment="到期日期")
    face_value = Column(Float, nullable=True, comment="债券面值")
    convert_price = Column(Float, nullable=True, comment="转股价格")
    listed = Column(Boolean, default=True, comment="是否上市")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_bond_code', 'code'),
        Index('idx_bond_underlying', 'underlying_code'),
    )


class ConvertibleBondBar(Base):
    """
    可转债历史行情表（日 K 线）
    通过 sync_bond_history 同步，供可转债回测使用。
    """
    __tablename__ = "convertible_bond_bar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(16), nullable=False, index=True, comment="可转债代码，如 113050")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True, comment="成交量（手）")
    turnover = Column(Float, nullable=True, comment="成交额（万元，Tushare cb_daily.amount）")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_bond_bar_code_date', 'code', 'trade_date', unique=True),
    )


class ConvertibleBondFactor(Base):
    """
    可转债因子快照表（交易日快照）
    数据来源: Tushare cb_basic/cb_daily（主）+ AkShare bond_zh_convertible_premium（降级）
    用途: 双低策略排行 / 前端可转债池因子筛选
    """
    __tablename__ = "convertible_bond_factor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(16), nullable=False, comment="可转债代码")
    name = Column(String(64), nullable=True, comment="可转债名称")
    trade_date = Column(Date, nullable=False, comment="交易日期")

    # 行情数据
    close_price = Column(Float, nullable=True, comment="转债收盘价（元）")
    remaining_size = Column(Float, nullable=True, comment="剩余规模（亿元）")

    # 溢价率核心因子
    premium_ratio = Column(Float, nullable=True, comment="转股溢价率（%），越低越接近正股")
    pure_bond_value = Column(Float, nullable=True, comment="纯债价值（元），债底安全垫")
    pure_bond_premium = Column(Float, nullable=True, comment="纯债溢价率（%），越低安全垫越厚")
    convert_value = Column(Float, nullable=True, comment="转股价值（元）= 正股价/转股价×100")

    # 正股联动
    underlying_code = Column(String(16), nullable=True, comment="正股代码")
    underlying_close = Column(Float, nullable=True, comment="正股当日收盘价")
    underlying_pe = Column(Float, nullable=True, comment="正股PE（复用StockDailyFactor）")
    underlying_roe = Column(Float, nullable=True, comment="正股ROE（复用StockFinancial）")

    # 条款相关
    convert_price = Column(Float, nullable=True, comment="转股价格（元/股）")
    rating = Column(String(8), nullable=True, comment="债券评级")
    mature_date = Column(Date, nullable=True, comment="到期日期")

    # 综合因子（预计算，加速排序）
    double_low_score = Column(Float, nullable=True,
                              comment="双低分 = 转债价格 + 转股溢价率，越低越好，行业最常用排序指标")

    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_cbf_code_date', 'code', 'trade_date', unique=True),
        Index('idx_cbf_date', 'trade_date'),
        Index('idx_cbf_double_low', 'trade_date', 'double_low_score'),
    )


class EtfDailyBar(Base):
    """
    ETF 日线行情表（独立存储，与股票日线分离）
    通过 sync_etf_daily 从 Tushare fund_daily 同步
    """
    __tablename__ = "etf_daily_bars"

    code = Column(String(20), primary_key=True, comment="ETF代码 (如 510300.SH)")
    trade_date = Column(Date, primary_key=True, comment="交易日期")

    open = Column(Float, comment="开盘价")
    high = Column(Float, comment="最高价")
    low = Column(Float, comment="最低价")
    close = Column(Float, comment="收盘价")
    pre_close = Column(Float, comment="昨收价")

    change = Column(Float, comment="涨跌额")
    pct_chg = Column(Float, comment="涨跌幅")

    volume = Column(Float, comment="成交量(手)")
    amount = Column(Float, comment="成交额(千元)")

    adj_factor = Column(Float, nullable=True, comment="复权因子")

    __table_args__ = (
        Index('idx_etf_bar_trade_date', 'trade_date'),
    )


class EtfBasicInfo(Base):
    """
    场内 ETF 基础信息表
    通过 Tushare fund_basic(market='E') 同步
    """
    __tablename__ = "etf_basic_info"

    code = Column(String(20), primary_key=True, comment="ETF代码 (如 510300.SH)")
    name = Column(String(80), nullable=True, comment="ETF名称")
    fund_type = Column(String(30), nullable=True, comment="类型: 股票型/债券型/货币型/混合型/QDII等")
    management = Column(String(50), nullable=True, comment="管理人")
    benchmark = Column(String(100), nullable=True, comment="跟踪指数/业绩基准")
    list_date = Column(String(10), nullable=True, comment="上市日期 YYYY-MM-DD")
    is_active = Column(Boolean, default=True, comment="是否上市交易中")
    category = Column(String(20), nullable=True, comment="分类: 宽基/行业/主题/跨境/商品/REITs")
    sub_category = Column(String(30), nullable=True, comment="二级分类: 港股/美股/沪深300/红利 等")
    industry = Column(String(20), nullable=True, comment="映射行业: 医药生物/电子/银行等（仅行业ETF有值）")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_etf_category', 'category'),
        Index('idx_etf_sub_category', 'sub_category'),
        Index('idx_etf_industry', 'industry'),
    )


class EtfFundSnapshot(Base):
    """
    ETF 净值 + 份额 每日快照表
    数据来源：Tushare fund_nav（净值）+ AkShare fund_etf_scale_sse / 深交所 API（份额）
    用途：溢价率 = close / unit_nav - 1，规模 = total_share * unit_nav
    """
    __tablename__ = "etf_fund_snapshot"

    code = Column(String(20), primary_key=True, comment="ETF代码 (如 510300.SH)")
    trade_date = Column(Date, primary_key=True, comment="快照日期")
    unit_nav = Column(Float, nullable=True, comment="单位净值")
    accum_nav = Column(Float, nullable=True, comment="累计净值")
    total_share = Column(Float, nullable=True, comment="总份额（份）")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_etf_snap_date', 'trade_date'),
    )


class SwIndustry(Base):
    """
    申万一级行业成分股映射表
    数据来源：Tushare index_classify(level='L1') + index_member_all(l1_code=xxx)
    用途：ETF→个股跨资产联动的行业精确匹配
    """
    __tablename__ = "sw_industry"

    code = Column(String(20), primary_key=True, comment="股票代码 (如 000001.SZ)")
    sw_l1_code = Column(String(20), nullable=False, comment="申万一级行业代码 (如 801010.SI)")
    sw_l1_name = Column(String(30), nullable=False, index=True, comment="申万一级行业名称 (如 农林牧渔)")
    in_date = Column(String(10), nullable=True, comment="纳入日期 (YYYYMMDD)")
    out_date = Column(String(10), nullable=True, comment="剔除日期 (YYYYMMDD，NULL表示仍在)")

    __table_args__ = (
        Index('idx_sw_l1_code', 'sw_l1_code'),
        Index('idx_sw_l1_name', 'sw_l1_name'),
    )


class StockNews(Base):
    """
    新闻数据表（三源合并）
    数据源: Tushare major_news / AkShare stock_news_em / Tavily search
    用途: 前端展示 + 新闻情绪因子计算
    """
    __tablename__ = "stock_news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False, comment="新闻标题")
    summary = Column(String, nullable=True, comment="摘要（前200字）")
    source = Column(String(30), nullable=True, comment="数据源: tushare/akshare/tavily")
    url = Column(String, nullable=True, comment="原文链接")
    publish_time = Column(DateTime, nullable=True, comment="发布时间")
    market_type = Column(String(10), default="A股", comment="A股/全球")
    related_codes = Column(String, nullable=True, comment="关联股票代码 JSON: [\"600519.SH\"]")
    sentiment_score = Column(Float, default=0.0, comment="情绪评分 -1(利空)~+1(利好)")
    sentiment_label = Column(String(10), nullable=True, comment="利好影响/利空影响/中性")
    event_type = Column(String(20), nullable=True, comment="事件类型: 重组/业绩/政策/人事/诉讼/技术/资金/分红/大宗交易/解禁/龙虎榜/其他")
    nlp_reason = Column(String(100), nullable=True, comment="LLM 情绪判定理由")
    code = Column(String(20), nullable=True, comment="主关联股票代码(冗余，加速选股器查询)")
    created_at = Column(DateTime, default=func.now(), comment="入库时间")

    __table_args__ = (
        Index("ix_news_publish_time", "publish_time"),
        Index("ix_news_title", "title", unique=True),
        Index("ix_news_event_type", "event_type"),
        Index("ix_news_code", "code"),
    )
