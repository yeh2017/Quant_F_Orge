"""
因子表达式 DSL 引擎
===================
解析并执行因子表达式（如 `rank(close/delay(close,20))`），
在面板数据上进行向量化计算。

安全性：使用 Python ast 模块解析，白名单验证，拒绝危险节点。

用法:
    panel = load_panel(codes, start, end)
    result = evaluate("rank(close / delay(close, 20))", panel)
    # result: DataFrame(index=date, columns=code)
"""

import ast
import operator
import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)


# ── 可用变量（面板字段名） ──

ALLOWED_VARIABLES = {
    'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg',
    'pe_ttm', 'pb', 'ps_ttm', 'turnover_rate', 'total_mv', 'dv_ttm', 'circ_mv',
}


# ── 预设因子表达式库 ──

PRESET_FACTORS = {
    "反转因子": {
        "desc": "近期跌的更可能反弹（A股最显著 alpha）",
        "params": [{"name": "days", "label": "回看天数", "default": 20, "min": 5, "max": 120}],
        "template": "-1 * (close / delay(close, {days}) - 1)",
    },
    "波动率": {
        "desc": "低波动股票长期风险调整收益更优",
        "params": [{"name": "days", "label": "窗口天数", "default": 20, "min": 5, "max": 60}],
        "template": "ts_std(close / delay(close, 1) - 1, {days})",
    },
    "量价背离": {
        "desc": "价格与成交量的相关性异常",
        "params": [{"name": "days", "label": "相关性窗口", "default": 10, "min": 5, "max": 30}],
        "template": "ts_corr(rank(close), rank(volume), {days})",
    },
    "小市值": {
        "desc": "小市值股票长期超额收益（A股特色）",
        "params": [],
        "template": "-1 * log(total_mv)",
    },
    "PE动量": {
        "desc": "估值趋势变化方向",
        "params": [{"name": "days", "label": "回看天数", "default": 20, "min": 5, "max": 60}],
        "template": "-1 * delta(pe_ttm, {days})",
    },
}


def build_expression(preset_name: str, params: dict | None = None) -> str:
    """
    从预设名称和参数构建表达式字符串。

    Args:
        preset_name: 预设名称
        params: 参数覆盖 {param_name: value}

    Returns:
        填充参数后的表达式字符串
    """
    preset = PRESET_FACTORS.get(preset_name)
    if not preset:
        raise ExpressionError(f"未知预设: {preset_name}")

    template: str = preset["template"]
    param_defs: list = preset["params"]

    # 用默认值填充，再用用户参数覆盖
    final_params = {}
    for p in param_defs:
        final_params[p["name"]] = p["default"]
    if params:
        for k, v in params.items():
            if k in final_params:
                try:
                    final_params[k] = int(v)
                except (ValueError, TypeError):
                    raise ExpressionError(f"参数 '{k}' 的值 '{v}' 不是有效整数")

    return template.format(**final_params) if final_params else template


# ── 时间序列算子（沿时间轴，每只股票独立） ──

def _delay(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日前的值"""
    return x.shift(d)


def _delta(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """x - delay(x, d)"""
    return x - x.shift(d)


def _ts_mean(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动均值"""
    return x.rolling(d, min_periods=max(1, d // 2)).mean()


def _ts_std(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动标准差"""
    return x.rolling(d, min_periods=max(2, d // 2)).std()


def _ts_sum(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动求和"""
    return x.rolling(d, min_periods=max(1, d // 2)).sum()


def _ts_min(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动最小值"""
    return x.rolling(d, min_periods=max(1, d // 2)).min()


def _ts_max(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动最大值"""
    return x.rolling(d, min_periods=max(1, d // 2)).max()


def _ts_rank(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动排名百分位"""
    return x.rolling(d, min_periods=max(2, d // 2)).apply(
        lambda s: s.rank().iloc[-1] / len(s), raw=False
    )


def _ts_argmax(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日内最大值位置（距今天数）"""
    return x.rolling(d, min_periods=max(1, d // 2)).apply(
        lambda s: np.argmax(s.values), raw=False
    )


def _ts_argmin(x: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日内最小值位置"""
    return x.rolling(d, min_periods=max(1, d // 2)).apply(
        lambda s: np.argmin(s.values), raw=False
    )


def _ts_corr(x: pd.DataFrame, y: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 日滚动相关系数"""
    result = pd.DataFrame(index=x.index, columns=x.columns, dtype=float)
    for col in x.columns:
        if col in y.columns:
            result[col] = x[col].rolling(d, min_periods=max(3, d // 2)).corr(y[col])
    return result


# ── 截面算子（跨股票，每个交易日独立） ──

def _rank(x: pd.DataFrame) -> pd.DataFrame:
    """截面百分位排名（每行独立 rank）"""
    return x.rank(axis=1, pct=True)


def _zscore(x: pd.DataFrame) -> pd.DataFrame:
    """截面 Z-Score"""
    mean = x.mean(axis=1)
    std = x.std(axis=1)
    std = std.replace(0, np.nan)
    return x.sub(mean, axis=0).div(std, axis=0)


def _demean(x: pd.DataFrame) -> pd.DataFrame:
    """截面去均值"""
    return x.sub(x.mean(axis=1), axis=0)


# ── 数学函数 ──

def _log(x):
    if isinstance(x, pd.DataFrame):
        return np.log(x.clip(lower=1e-10))
    return np.log(max(x, 1e-10))


def _abs(x):
    if isinstance(x, pd.DataFrame):
        return x.abs()
    return abs(x)


def _sign(x):
    if isinstance(x, pd.DataFrame):
        return np.sign(x)
    return np.sign(x)


def _power(x, n):
    if isinstance(x, pd.DataFrame):
        return x ** n
    return x ** n


def _where(cond, x, y):
    """条件选择: where(cond, x_if_true, y_if_false)"""
    if isinstance(cond, pd.DataFrame):
        return x.where(cond, y)
    return x if cond else y


def _max_func(x, y):
    if isinstance(x, pd.DataFrame) and isinstance(y, pd.DataFrame):
        return x.where(x >= y, y)
    elif isinstance(x, pd.DataFrame):
        return x.clip(lower=y)
    elif isinstance(y, pd.DataFrame):
        return y.clip(lower=x)
    return max(x, y)


def _min_func(x, y):
    if isinstance(x, pd.DataFrame) and isinstance(y, pd.DataFrame):
        return x.where(x <= y, y)
    elif isinstance(x, pd.DataFrame):
        return x.clip(upper=y)
    elif isinstance(y, pd.DataFrame):
        return y.clip(upper=x)
    return min(x, y)


# ── 函数注册表 ──

ALLOWED_FUNCTIONS = {
    # 时间序列（2参数: x, d）
    'delay': _delay,
    'delta': _delta,
    'ts_mean': _ts_mean,
    'ts_std': _ts_std,
    'ts_sum': _ts_sum,
    'ts_min': _ts_min,
    'ts_max': _ts_max,
    'ts_rank': _ts_rank,
    'ts_argmax': _ts_argmax,
    'ts_argmin': _ts_argmin,
    # 时间序列（3参数: x, y, d）
    'ts_corr': _ts_corr,
    # 截面（1参数: x）
    'rank': _rank,
    'zscore': _zscore,
    'demean': _demean,
    # 数学
    'log': _log,
    'abs': _abs,
    'sign': _sign,
    'power': _power,
    'where': _where,
    'max': _max_func,
    'min': _min_func,
}

# 二元运算符
BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

COMPARE_OPS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


# ── AST 安全验证 ──

class ExpressionError(Exception):
    """表达式解析或执行错误"""


def _validate_ast(node: ast.AST):
    """递归验证 AST 节点，只允许白名单操作"""
    if isinstance(node, ast.Expression):
        _validate_ast(node.body)

    elif isinstance(node, ast.BinOp):
        if type(node.op) not in BINARY_OPS:
            raise ExpressionError(f"不支持的运算符: {type(node.op).__name__}")
        _validate_ast(node.left)
        _validate_ast(node.right)

    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in UNARY_OPS:
            raise ExpressionError(f"不支持的一元运算符: {type(node.op).__name__}")
        _validate_ast(node.operand)

    elif isinstance(node, ast.Compare):
        _validate_ast(node.left)
        for op in node.ops:
            if type(op) not in COMPARE_OPS:
                raise ExpressionError(f"不支持的比较运算符: {type(op).__name__}")
        for comparator in node.comparators:
            _validate_ast(comparator)

    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("不支持方法调用（如 x.method()），只允许函数调用")
        if node.func.id not in ALLOWED_FUNCTIONS:
            raise ExpressionError(f"不支持的函数: {node.func.id}")
        for arg in node.args:
            _validate_ast(arg)

    elif isinstance(node, ast.Name):
        if node.id not in ALLOWED_VARIABLES and node.id not in ALLOWED_FUNCTIONS:
            raise ExpressionError(f"未知变量: {node.id}")

    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ExpressionError(f"只允许数字常量，不允许: {type(node.value).__name__}")

    elif isinstance(node, ast.Num):  # Python 3.7 兼容
        pass

    else:
        raise ExpressionError(
            f"不支持的语法节点: {type(node).__name__}。"
            f"只允许: 变量、函数调用、算术运算、比较运算、数字常量"
        )


# ── AST 求值 ──

def _eval_node(node: ast.AST, panel: dict[str, pd.DataFrame]) -> pd.DataFrame | float:
    """递归求值 AST 节点"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, panel)

    elif isinstance(node, ast.BinOp):
        left = _eval_node(node.left, panel)
        right = _eval_node(node.right, panel)
        op_func = BINARY_OPS[type(node.op)]
        return op_func(left, right)

    elif isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, panel)
        op_func = UNARY_OPS[type(node.op)]
        return op_func(operand)

    elif isinstance(node, ast.Compare):
        left = _eval_node(node.left, panel)
        # 只支持单个比较（a < b），不支持链式（a < b < c）
        right = _eval_node(node.comparators[0], panel)
        op_func = COMPARE_OPS[type(node.ops[0])]
        return op_func(left, right)

    elif isinstance(node, ast.Call):
        func_name = node.func.id
        func = ALLOWED_FUNCTIONS[func_name]
        args = [_eval_node(arg, panel) for arg in node.args]
        return func(*args)

    elif isinstance(node, ast.Name):
        var_name = node.id
        if var_name in panel:
            return panel[var_name]
        raise ExpressionError(
            f"变量 '{var_name}' 在面板数据中不存在。"
            f"可用字段: {list(panel.keys())}"
        )

    elif isinstance(node, ast.Constant):
        return node.value

    elif isinstance(node, ast.Num):  # Python 3.7 兼容
        return node.n

    raise ExpressionError(f"无法求值: {type(node).__name__}")


# ── 公开 API ──

def validate_expression(expr: str) -> tuple[bool, str]:
    """
    验证表达式是否合法。

    Returns:
        (is_valid, error_message)
    """
    try:
        tree = ast.parse(expr, mode='eval')
        _validate_ast(tree)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误: {e.msg} (行{e.lineno} 列{e.offset})"
    except ExpressionError as e:
        return False, str(e)


def get_required_fields(expr: str) -> set[str]:
    """
    解析表达式，提取所需的面板字段。

    用于按需加载面板数据，避免加载多余字段。
    """
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return set()

    fields = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ALLOWED_VARIABLES:
            fields.add(node.id)
    return fields


def evaluate(
    expr: str,
    panel: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    在面板数据上执行因子表达式。

    Args:
        expr: 因子表达式字符串，如 "rank(close / delay(close, 20))"
        panel: 面板数据 {field_name: DataFrame(date × code)}

    Returns:
        因子值 DataFrame(index=date, columns=code)

    Raises:
        ExpressionError: 表达式不合法或执行出错
    """
    # 1. 解析 AST
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError as e:
        raise ExpressionError(f"语法错误: {e.msg}")

    # 2. 安全验证
    _validate_ast(tree)

    # 3. 求值
    try:
        result = _eval_node(tree, panel)
    except ExpressionError:
        raise
    except Exception as e:
        raise ExpressionError(f"执行出错: {e}")

    # 4. 确保返回 DataFrame
    if isinstance(result, (int, float)):
        # 标量结果：扩展为面板
        sample = next(iter(panel.values()))
        result = pd.DataFrame(result, index=sample.index, columns=sample.columns)
    elif not isinstance(result, pd.DataFrame):
        raise ExpressionError(f"表达式结果类型错误: {type(result)}")

    log.info("expression_evaluated", expr=expr[:60],
             shape=result.shape, nan_pct=round(result.isna().mean().mean(), 3))
    return result
