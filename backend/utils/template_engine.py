"""
Jinja2 模板渲染引擎
==================
加载 templates/ 目录下的 .j2 模板，注册自定义过滤器后渲染。
供推送通知（push_top.j2）和每日摘要（daily_summary.j2）使用。
"""

import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


# ── 自定义过滤器 ──

def clean_title(text: str) -> str:
    """清理标题中的多余空白和特殊字符"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_reason(text: str) -> str:
    """清理 nlp_reason：去除 [规则] 前缀和多余空白"""
    if not text:
        return ""
    text = re.sub(r"^\[规则\]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_env.filters["clean_title"] = clean_title
_env.filters["clean_reason"] = clean_reason


def render(template_name: str, **kwargs) -> str:
    """渲染指定模板，返回字符串"""
    tmpl = _env.get_template(template_name)
    return tmpl.render(**kwargs)
