"""
共享评分工具
===========
百分位排名等评分函数，供 market / etf / bond 三个 service 复用。
消除 screener_market.py L658 和 bonds.py L83 的重复代码。
"""


def percentile_rank(values: list[float], higher_is_better: bool = True) -> list[float]:
    """
    百分位排名归一化到 [0, 100]。

    Args:
        values: 原始数值列表
        higher_is_better: True=数值越大排名越高, False=数值越小排名越高

    Returns:
        与 values 等长的排名列表，值域 [0, 100]
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]

    sorted_v = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    for rank_pos, (orig_idx, _) in enumerate(sorted_v):
        ranks[orig_idx] = rank_pos / (n - 1) * 100

    return ranks if higher_is_better else [100 - r for r in ranks]
