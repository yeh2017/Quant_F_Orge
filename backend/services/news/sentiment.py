"""
情绪评分模块

从 sync_news.py 提取，统一所有数据源的评分逻辑。
"""
import re

# 情绪阈值常量（全模块统一引用）
STRONG_THRESHOLD = 0.3   # |score| > 此值 → 利好/利空
# PUSH_THRESHOLD 已迁移至 notifier.py _DEFAULT_CONFIG["push_threshold"]，用户可在设置面板调整

# 情绪关键词（扩充版）
_POSITIVE_KW = [
    "签约", "利好", "增持", "回购", "创新高", "突破", "中标", "获批",
    "涨停", "盈利", "超预期", "大涨", "新高", "龙头", "加仓",
    "翻倍", "暴涨", "飙升", "扭亏", "分红", "派息", "战略合作",
    "订单", "放量", "净买入", "融资", "上调", "评级", "推荐",
    "重组", "并购", "注入", "激励", "解禁利好", "大幅增长",
    "业绩预增", "营收增长", "净利润增", "毛利率提升",
]
_NEGATIVE_KW = [
    "立案", "违规", "减持", "亏损", "下调", "利空", "处罚", "退市",
    "跌停", "预亏", "暴雷", "爆仓", "警示", "ST", "暴跌",
    "破发", "腰斩", "闪崩", "清仓", "套牢", "踩雷", "质押",
    "商誉减值", "计提", "诉讼", "担保", "欠薪", "停牌",
    "业绩预减", "净利润降", "营收下滑", "大幅下降",
    "关注函", "问询函", "监管", "调查", "造假", "内幕",
]


def score_sentiment(text: str) -> float:
    """关键词情绪评分: -1 ~ +1"""
    pos = sum(1 for kw in _POSITIVE_KW if kw in text)
    neg = sum(1 for kw in _NEGATIVE_KW if kw in text)
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 2)


def score_to_label(score: float) -> str:
    if score > STRONG_THRESHOLD:
        return "利好影响"
    if score < -STRONG_THRESHOLD:
        return "利空影响"
    return "中性"


def strip_html(text: str) -> str:
    """去除 HTML/JS/CSS/广告，保留纯文本"""
    clean = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'<[^>]+>', '', clean)
    clean = re.sub(r'\(function\(\)\{.*', '', clean, flags=re.DOTALL)
    clean = re.sub(r'（[a-zA-Z][a-zA-Z,\s]{10,}[a-zA-Z]）', '', clean)
    clean = re.sub(r'\([a-zA-Z][a-zA-Z,\s]{10,}[a-zA-Z]\)', '', clean)
    clean = re.sub(r'关注同花顺财经.*', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean
