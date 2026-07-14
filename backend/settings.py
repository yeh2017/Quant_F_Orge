"""
settings.py
============
全局配置与常量。
业务常量 + 运行时配置（可通过 .env 覆盖）集中管理。

数据源: Tushare Pro（主） + AkShare（降级备用）
  - TUSHARE_TOKEN 在 .env 中配置
  - 积分等级: 120(免费) | 2000(基础) | 5000(进阶)
  - 120分: 日线/ETF/行业  2000分: +财务/daily_basic  5000分: +转债/资金流向/融资融券/事件
  - 接口频率限制由下方 TUSHARE_FETCH_SLEEP 和熔断器控制
"""
import os


def _env(key: str, default: str) -> str:
    """安全读取环境变量，空字符串视为未设置"""
    val = os.getenv(key, default)
    return val if val else default

# ══════════════════ 业务常量 ══════════════════

# ── 交易参数 ──
TRADING_DAYS = 252          # 年交易日数
RF_ANNUAL = 0.025           # 无风险利率（年化，小数形式，即 2.5%）
MARKET_CLOSE_HOUR = 17      # A股数据发布时间（小时），Tushare 通常在收盘后 17:30 完成日线推送
MARKET_CLOSE_MINUTE = 30    # A股数据发布时间（分钟）

# ── Tushare 积分等级 ──
# 用户在前端设置页选择自己的积分等级，系统据此自动跳过不够格的数据同步步骤
# 120=免费 | 2000=基础 | 5000=进阶（含转债/资金流向/融资融券/事件）
TUSHARE_POINTS: int = int(_env("TUSHARE_POINTS", "2000"))

def get_tushare_points() -> int:
    """运行时读取积分等级（设置页修改后立即生效，区别于模块常量 TUSHARE_POINTS 的一次性缓存）"""
    return int(os.environ.get("TUSHARE_POINTS", "2000"))

# ── 组合约束 ──
SINGLE_STOCK_MAX_WEIGHT = 0.30   # 单只股票权重上限
INDUSTRY_MAX_WEIGHT = 0.40       # 同行业权重上限

# ── 数据保留 ──
DB_RETAIN_YEARS = int(_env("DB_RETAIN_YEARS", "7"))              # 数据库历史数据保留年数
CACHE_RETAIN_DAYS = int(_env("CACHE_RETAIN_DAYS", "7"))           # 缓存保留天数
LOG_RETAIN_DAYS = int(_env("LOG_RETAIN_DAYS", "15"))              # 日志保留天数
NEWS_RETAIN_DAYS = int(_env("NEWS_RETAIN_DAYS", "90"))            # 新闻保留天数（覆盖一个季度，为事件回测积累数据）

# Tavily 搜索白名单：只从这些新闻站抓取（防止行情页/垃圾数据混入）
TAVILY_NEWS_DOMAINS = [
    "news.sina.com.cn", "finance.sina.com.cn",
    "finance.qq.com", "new.qq.com",
    "wallstreetcn.com", "cls.cn",
    "caixin.com", "yicai.com",
    "stcn.com", "nbd.com.cn",
    "chinanews.com.cn", "people.com.cn",
    "xinhuanet.com", "cctv.com",
    "thepaper.cn", "jiemian.com",
    "36kr.com", "huxiu.com",
    "reuters.com", "bloomberg.com",
    "xueqiu.com",
]
BACKTEST_RESULT_RETAIN_DAYS = int(_env("BACKTEST_RESULT_RETAIN_DAYS", "90"))  # 回测结果保留天数
SUMMARY_PUSH_HOURS = []         # telegram每日摘要推送时间（24h），如 [8, 18] 表示早8晚6各推一次

# ══════════════════ 运行时配置 ══════════════════

# ── 线程并发 ──
FINANCIAL_WORKERS: int = int(_env("FINANCIAL_WORKERS", "5"))
SINGLE_FETCH_WORKERS: int = int(_env("SINGLE_FETCH_WORKERS", "5"))

# ── 请求间隔 (秒) ──
# Tushare Pro 频率限制：积分越高，可调用频率越高
# 2000分: 200次/分  |  5000分: 500次/分  |  10000分: 无限制
FINANCIAL_SLEEP: float = float(_env("FINANCIAL_SLEEP", "0.8"))      # fina_indicator 财务指标 (2000分:2.0 | 5000分:0.8)
MONEYFLOW_SLEEP: float = float(_env("MONEYFLOW_SLEEP", "0.2"))      # moneyflow 资金流向 (2000分:0.5 | 5000分:0.2)

TUSHARE_FETCH_SLEEP: float = float(_env("TUSHARE_FETCH_SLEEP", "0.15"))  # daily 日线 (120分:0.8 | 2000分:0.3 | 5000分:0.15)
BOND_FETCH_SLEEP: float = float(_env("BOND_FETCH_SLEEP", "0.1"))    # cb_daily 可转债行情 (2000分:0.3 | 5000分:0.1)
SW_INDUSTRY_SLEEP: float = float(_env("SW_INDUSTRY_SLEEP", "0.5"))  # index_member_all 行业成分 (2000分:1.5 | 5000分:0.5)
AKSHARE_NEWS_SLEEP: float = float(_env("AKSHARE_NEWS_SLEEP", "0.5"))  # stock_news_em 个股新闻 (无官方限速, 0.5s安全值)


# ── LLM 情绪分析（多渠道：LLM_CHANNELS 优先，ERNIE_* 为向后兼容默认值） ──
ERNIE_API_KEY: str = _env("ERNIE_API_KEY", "")  # 向后兼容：无 LLM_CHANNELS 时作为默认供应商
ERNIE_MODEL_URL: str = "https://api.siliconflow.cn/v1/chat/completions"  # 向后兼容默认 URL
ERNIE_MODEL_NAME: str = _env("ERNIE_MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash")
ERNIE_BATCH_SIZE: int = int(_env("ERNIE_BATCH_SIZE", "10"))  # 每次 prompt 塞入的新闻条数
LLM_MONTHLY_BUDGET: float = float(_env("LLM_MONTHLY_BUDGET", "15"))  # AI 月预算（¥），超出降级为关键词评分

# ── 批量写入 ──
WRITE_BATCH_SIZE: int = int(_env("WRITE_BATCH_SIZE", "500"))

# ── Tushare 熔断 ──
# 连续失败 N 次后暂停调用，冷却后恢复
TUSHARE_RATE_LIMIT_PER_MIN: int = int(_env("TUSHARE_RATE_LIMIT_PER_MIN", "480"))        # 令牌桶上限（5000积分=500/min，留10%余量）
TUSHARE_BREAKER_FAIL_THRESHOLD: int = int(_env("TUSHARE_BREAKER_FAIL_THRESHOLD", "5"))   # 触发熔断的连续失败次数
TUSHARE_BREAKER_COOLDOWN: float = float(_env("TUSHARE_BREAKER_COOLDOWN", "60.0"))        # 熔断冷却时间 (秒)
