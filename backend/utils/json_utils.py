"""
JSON 序列化工具
===============
sanitize(): 递归清除 NaN/Inf，防止 JSON 序列化崩溃。
兼容 numpy/pandas 全部类型。
"""
import math


def sanitize(obj):
    """递归清除 NaN/inf，兼容 numpy/pandas 全部类型"""
    import numpy as np
    import pandas as pd

    # numpy 标量
    if isinstance(obj, (np.floating, float)):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    # numpy array → list 递归
    if isinstance(obj, np.ndarray):
        return [sanitize(v) for v in obj.tolist()]
    # pandas Series / DataFrame → list/dict 递归
    if isinstance(obj, pd.Series):
        return sanitize(obj.to_dict())
    if isinstance(obj, pd.DataFrame):
        return sanitize(obj.to_dict(orient='records'))
    # pandas NA
    if pd.isna(obj) if not isinstance(obj, (dict, list, tuple, str, bytes)) else False:
        return None
    # 容器递归
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return obj
