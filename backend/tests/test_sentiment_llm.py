"""
LLM 情绪分析解析层单测（P0）
============================
_parse_response 是 LLM 输出 → 业务数据的唯一类型边界。
历史上出过 `string → float` 崩溃，必须覆盖所有畸形输入。

运行：  cd backend && .venv\\Scripts\\pytest tests/test_sentiment_llm.py -v
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.news.sentiment_llm import _parse_response, LLM_EVENT_TYPES, STRUCTURED_EVENT_TYPES


# ── 辅助 ──

def _make_batch(n=3):
    """构造 n 条新闻的 batch 参数"""
    return [{"id": i + 1, "title": f"新闻{i}", "codes": [f"00000{i}.SZ"]} for i in range(n)]


# ── 1. 正常 JSON ──

class TestNormalParsing:
    def test_standard_response(self):
        """标准 LLM 响应：数组格式"""
        raw = json.dumps([
            {"news_idx": 1, "stocks": [
                {"code": "000001.SZ", "score": 0.8, "event": "业绩", "reason": "利润增长"}
            ]},
            {"news_idx": 2, "stocks": [
                {"code": "600519.SH", "score": -0.5, "event": "政策", "reason": "监管收紧"}
            ]},
        ])
        result = _parse_response(raw, _make_batch(2))
        assert len(result) == 2
        assert result[0]["news_idx"] == 1
        assert result[0]["stocks"][0]["score"] == 0.8
        assert result[0]["stocks"][0]["event"] == "业绩"

    def test_dict_wrapper(self):
        """LLM 返回 {"results": [...]} 字典包裹"""
        inner = [{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.5, "event": "其他", "reason": ""}]}]
        raw = json.dumps({"results": inner})
        result = _parse_response(raw, _make_batch(1))
        assert len(result) == 1

    def test_data_key_wrapper(self):
        """LLM 返回 {"data": [...]}"""
        inner = [{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.3, "event": "资金", "reason": ""}]}]
        raw = json.dumps({"data": inner})
        result = _parse_response(raw, _make_batch(1))
        assert len(result) == 1

    def test_markdown_wrapped(self):
        """LLM 返回被 ```json ... ``` 包裹的 JSON"""
        inner = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.1, "event": "其他", "reason": ""}]}])
        raw = f"```json\n{inner}\n```"
        result = _parse_response(raw, _make_batch(1))
        assert len(result) == 1


# ── 2. 类型安全（曾导致生产崩溃） ──

class TestTypeSafety:
    def test_score_as_string(self):
        """score 为字符串 → 强转 float"""
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": "0.7", "event": "业绩", "reason": ""}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["stocks"][0]["score"] == 0.7
        assert isinstance(result[0]["stocks"][0]["score"], float)

    def test_score_empty_string(self):
        """score 为空字符串 → 降级为 0.0（曾导致 could not convert string to float 崩溃）"""
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": "", "event": "业绩", "reason": ""}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["stocks"][0]["score"] == 0.0

    def test_score_none(self):
        """score 为 null → 0.0"""
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": None, "event": "业绩", "reason": ""}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["stocks"][0]["score"] == 0.0

    def test_score_clamped(self):
        """score 超出 [-1, 1] → clamp"""
        raw = json.dumps([
            {"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 5.0, "event": "业绩", "reason": ""}]},
            {"news_idx": 2, "stocks": [{"code": "600519.SH", "score": -3.0, "event": "业绩", "reason": ""}]},
        ])
        result = _parse_response(raw, _make_batch(2))
        assert result[0]["stocks"][0]["score"] == 1.0
        assert result[1]["stocks"][0]["score"] == -1.0

    def test_news_idx_as_string(self):
        """news_idx 为字符串 → 强转 int"""
        raw = json.dumps([{"news_idx": "1", "stocks": [{"code": "000001.SZ", "score": 0.5, "event": "其他", "reason": ""}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["news_idx"] == 1

    def test_reason_truncated(self):
        """reason 超长 → 截断到 100 字"""
        long_reason = "A" * 200
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.5, "event": "其他", "reason": long_reason}]}])
        result = _parse_response(raw, _make_batch(1))
        assert len(result[0]["stocks"][0]["reason"]) == 100


# ── 3. 事件类型校验 ──

class TestEventType:
    def test_valid_event_types(self):
        """LLM 可用事件类型保持原值"""
        for ev in LLM_EVENT_TYPES:
            raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.1, "event": ev, "reason": ""}]}])
            result = _parse_response(raw, _make_batch(1))
            assert result[0]["stocks"][0]["event"] == ev

    def test_structured_event_types_rejected(self):
        """结构化事件类型（大宗交易/解禁/龙虎榜）由 sync_events 注入，LLM 返回时降级为'其他'"""
        for ev in STRUCTURED_EVENT_TYPES:
            raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.1, "event": ev, "reason": ""}]}])
            result = _parse_response(raw, _make_batch(1))
            assert result[0]["stocks"][0]["event"] == "其他", f"结构化类型 '{ev}' 应被降级为 '其他'"

    def test_invalid_event_falls_back(self):
        """非法事件类型 → '其他'"""
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.1, "event": "不存在的类型", "reason": ""}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["stocks"][0]["event"] == "其他"

    def test_event_none_falls_back(self):
        """event 为 null → '其他'"""
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ", "score": 0.1, "event": None, "reason": ""}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["stocks"][0]["event"] == "其他"


# ── 4. 畸形输入 ──

class TestMalformedInput:
    def test_invalid_json(self):
        """完全无效的 JSON → 空列表"""
        assert _parse_response("not json at all", _make_batch(1)) == []

    def test_empty_string(self):
        """空字符串"""
        assert _parse_response("", _make_batch(1)) == []

    def test_html_response(self):
        """LLM 返回 HTML（偶尔发生）"""
        assert _parse_response("<html><body>Error</body></html>", _make_batch(1)) == []

    def test_stocks_not_list(self):
        """stocks 不是数组 → 跳过该条"""
        raw = json.dumps([{"news_idx": 1, "stocks": "not_a_list"}])
        result = _parse_response(raw, _make_batch(1))
        assert len(result) == 0

    def test_entry_not_dict(self):
        """数组元素不是 dict → 跳过"""
        raw = json.dumps(["string_entry", 42])
        result = _parse_response(raw, _make_batch(1))
        assert len(result) == 0

    def test_missing_fields(self):
        """缺少字段 → 用默认值填充"""
        raw = json.dumps([{"news_idx": 1, "stocks": [{"code": "000001.SZ"}]}])
        result = _parse_response(raw, _make_batch(1))
        assert result[0]["stocks"][0]["score"] == 0.0
        assert result[0]["stocks"][0]["event"] == "其他"
        assert result[0]["stocks"][0]["reason"] == ""
