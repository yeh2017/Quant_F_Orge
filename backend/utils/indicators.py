"""
共享技术指标计算工具
====================
sma / ema 被策略引擎和技术诊断引擎共同使用，抽取到此处避免跨职责耦合。
"""

import numpy as np


def sma(arr: np.ndarray, window: int) -> np.ndarray:
    """SMA：对 (T,) 或 (T, N) 矩阵的每列计算滑动均值"""
    out = np.full_like(arr, np.nan, dtype=float)
    cs = np.nancumsum(arr, axis=0)
    # 第 window-1 行（首个完整窗口）
    out[window - 1] = cs[window - 1] / window
    # 后续行用前缀和差值
    if arr.shape[0] > window:
        out[window:] = (cs[window:] - cs[:-window]) / window
    return out


def ema(arr: np.ndarray, span: int) -> np.ndarray:
    """EMA：逐行循环，列维度向量化。首行 NaN 安全处理。"""
    alpha = 2.0 / (span + 1)
    out = np.full_like(arr, np.nan, dtype=float)
    out[0] = np.where(np.isnan(arr[0]), 0.0, arr[0])
    for t in range(1, arr.shape[0]):
        prev = np.where(np.isnan(out[t - 1]), 0.0, out[t - 1])
        cur = np.where(np.isnan(arr[t]), prev, arr[t])
        out[t] = alpha * cur + (1 - alpha) * prev
    return out
