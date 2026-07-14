"""
因子计算工具函数
"""
import numpy as np


def make_serializable(val):
    """确保值可 JSON 序列化"""
    if val is None:
        return None
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return 0.0
        return v
    except (TypeError, ValueError):
        return val


def normalize_pct(val):
    """百分比归一化：如果绝对值 < 1 则认为是小数形式，乘以 100"""
    if val is None:
        return 0.0
    try:
        val = float(val)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(val) or np.isinf(val):
        return 0.0
    if 0 < abs(val) < 1:
        return val * 100
    return val


def robust_zscore(values: np.ndarray) -> np.ndarray:
    """MAD 去极值 + Z-Score 标准化"""
    if len(values) < 2:
        return np.zeros_like(values)

    # MAD (Median Absolute Deviation) 去极值
    median = np.nanmedian(values)
    mad = np.nanmedian(np.abs(values - median))

    # 将极值截断在 中位数 ± 3.148 * MAD (对应高斯分布的 3 sigma)
    if mad > 0:
        upper_bound = median + 3.148 * mad
        lower_bound = median - 3.148 * mad
        values = np.clip(values, lower_bound, upper_bound)

    # Z-Score
    mean = np.nanmean(values)
    std = np.nanstd(values)
    if std > 0:
        return (values - mean) / std
    return np.zeros_like(values)
