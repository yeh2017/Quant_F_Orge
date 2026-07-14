"""
数据源 Schema + 列名映射 自动化测试
====================================
验证 schema 验证规则和列名映射配置正确性。
运行: python -m pytest tests/test_schema.py -v
"""
import pytest
from data_sources.schema import validate_records, SCHEMA, COLUMN_MAP, get_column_map


# ══════════════════════════════════════════════════
#  Schema 验证测试
# ══════════════════════════════════════════════════

class TestSchemaValidation:
    """验证 validate_records 的校验逻辑"""

    def test_empty_records_is_ok(self):
        result = validate_records([], SCHEMA["cb_basic"], source="test")
        assert result["ok"] is True
        assert result["total"] == 0

    def test_good_data_passes(self):
        records = [
            {"code": "113050", "name": "南银转债",
             "convert_price": 12.5, "rating": "AA", "underlying_code": "601009"},
            {"code": "127039", "name": "润建转债",
             "convert_price": 20.0, "rating": "AA-", "underlying_code": "002929"},
        ]
        result = validate_records(records, SCHEMA["cb_basic"], source="test")
        assert result["ok"] is True
        assert result["total"] == 2

    def test_missing_required_field_fails(self):
        records = [{"name": "南银转债"}]  # 缺 code
        result = validate_records(records, SCHEMA["cb_basic"], source="test")
        assert result["ok"] is False
        assert any("code" in w for w in result["warnings"])

    def test_missing_required_raises_when_asked(self):
        records = [{"name": "南银转债"}]
        with pytest.raises(ValueError):
            validate_records(records, SCHEMA["cb_basic"],
                             source="test", raise_on_fail=True)

    def test_all_null_important_fails(self):
        """模拟之前的 bug：API 返回了行但关键字段全是 NULL"""
        records = [
            {"code": f"11{i:04d}", "name": "X",
             "convert_price": None, "rating": None, "underlying_code": None}
            for i in range(10)
        ]
        result = validate_records(records, SCHEMA["cb_basic"], source="test")
        assert result["ok"] is False
        assert len(result["warnings"]) >= 2  # convert_price + rating 至少两个

    def test_partial_null_within_threshold(self):
        """50% 以内的 NULL 不报警（亏损股无 PE 是正常的）"""
        records = [
            {"code": f"6001{i:02d}.SH", "trade_date": "20260319",
             "pe_ttm": 15.0 if i % 2 == 0 else None,
             "pb": 1.5, "turnover_rate": 2.0}
            for i in range(10)
        ]
        result = validate_records(records, SCHEMA["stock_factor"], source="test")
        # pe_ttm 50% NULL,  min_ratio=0.3 → 50% > 30% → OK
        assert result["ok"] is True


# ══════════════════════════════════════════════════
#  列名映射测试
# ══════════════════════════════════════════════════

class TestColumnMap:
    """验证 COLUMN_MAP 配置的完整性和正确性"""

    def test_akshare_cb_premium_has_required_keys(self):
        """AkShare 溢价率映射必须包含 schema 中定义的 required + important 字段"""
        mapping = COLUMN_MAP["akshare_cb_premium"]
        target_fields = set(mapping.values())
        schema = SCHEMA["ak_cb_premium"]

        for field in schema["required"]:
            assert field in target_fields, f"required 字段 '{field}' 不在映射目标中"
        for field in schema["important"]:
            assert field in target_fields, f"important 字段 '{field}' 不在映射目标中"

    def test_tushare_cb_basic_has_conv_price(self):
        """确保 conv_price（不是 convert_price）在映射中"""
        mapping = COLUMN_MAP["tushare_cb_basic"]
        assert "conv_price" in mapping, "Tushare 实际字段名是 conv_price，不是 convert_price"
        assert mapping["conv_price"] == "convert_price"

    def test_all_column_maps_have_entries(self):
        """所有声明的映射都不能为空"""
        for source, mapping in COLUMN_MAP.items():
            assert len(mapping) > 0, f"{source} 列名映射为空"

    def test_get_column_map_returns_correct(self):
        result = get_column_map("akshare_cb_premium")
        assert "债券代码" in result
        assert result["债券代码"] == "code"

    def test_get_column_map_unknown_returns_empty(self):
        result = get_column_map("nonexistent_source")
        assert result == {}


# ══════════════════════════════════════════════════
#  Schema 定义完整性测试
# ══════════════════════════════════════════════════

class TestSchemaDefinitions:
    """确保 SCHEMA 定义本身是合理的"""

    def test_all_schemas_have_required_keys(self):
        for name, schema in SCHEMA.items():
            assert "required" in schema, f"{name} 缺少 required"
            assert "important" in schema, f"{name} 缺少 important"
            assert "min_ratio" in schema, f"{name} 缺少 min_ratio"

    def test_min_ratio_in_valid_range(self):
        for name, schema in SCHEMA.items():
            ratio = schema["min_ratio"]
            assert 0.0 <= ratio <= 1.0, f"{name} min_ratio={ratio} 不在 [0,1] 范围"

    def test_required_and_important_no_overlap(self):
        """required 和 important 不应重叠"""
        for name, schema in SCHEMA.items():
            overlap = set(schema["required"]) & set(schema["important"])
            assert len(overlap) == 0, f"{name} 字段重叠: {overlap}"
