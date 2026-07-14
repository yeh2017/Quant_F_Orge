# -*- coding: utf-8 -*-
"""
数据源前后端连接测试（Tushare Pro 单源架构）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

def test_tushare_source():
    """测试 Tushare Pro 数据源连接"""
    print("=" * 60)
    print("  Tushare Pro 数据源连接测试")
    print("=" * 60)
    
    from services.stock_service import StockService
    
    test_codes = ['600519', '000858', '000001']  # 贵州茅台、五粮液、平安银行
    
    try:
        service = StockService()
        source = service.get_current_source()
        if not source:
            print("  [FAIL] 数据源未初始化")
            return
        
        print(f"  [OK] 数据源已连接")
        
        # 测试获取股票信息
        for code in test_codes:
            try:
                info = service.get_stock_info(code)
                if info:
                    print(f"\n  股票 {code}:")
                    print(f"    代码: {info.get('code', code)}")
                    print(f"    名称: {info.get('name', '未知')}")
                    print(f"    行业: {info.get('industry', '未知')}")
                    print(f"    市场: {info.get('market', '未知')}")
                else:
                    print(f"\n  股票 {code}: 未找到数据")
            except Exception as e:
                print(f"\n  股票 {code}: 获取失败 - {str(e)[:50]}")
        
        print("\n  [PASS] 数据源测试通过")
        
    except Exception as e:
        print(f"  [FAIL] Tushare: {str(e)[:80]}")


def test_api_endpoints():
    """测试 API 端点"""
    import requests
    
    print("\n" + "=" * 60)
    print("  API 端点测试")
    print("=" * 60)
    
    base_url = "http://localhost:8000"
    
    # 测试健康检查
    try:
        r = requests.get(f"{base_url}/", timeout=5)
        print(f"  [OK] 健康检查: {r.json()}")
    except Exception as e:
        print(f"  [FAIL] 健康检查失败: {e}")
        return
    
    # 测试数据中心状态
    try:
        r = requests.get(f"{base_url}/api/data_center/status", timeout=5)
        status = r.json()
        print(f"  [OK] 数据中心状态: stocks={status.get('stock_basic', {}).get('total_stocks', '?')}")
    except Exception as e:
        print(f"  [FAIL] 数据中心状态: {e}")
    
    # 测试股票信息 API
    test_codes = ['600519', '000858']
    for code in test_codes:
        try:
            r = requests.get(f"{base_url}/api/stocks/info/{code}", timeout=30)
            if r.status_code == 200:
                info = r.json()
                print(f"  [OK] 股票 {code}:")
                print(f"       代码: {info.get('code', code)}")
                print(f"       名称: {info.get('name', '未知')}")
                print(f"       行业: {info.get('industry', '未知')}")
            else:
                print(f"  [FAIL] 股票 {code}: {r.status_code} - {r.text[:50]}")
        except Exception as e:
            print(f"  [FAIL] 股票 {code}: {e}")


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("#  Tushare Pro 数据源连接测试")
    print("#" * 60)
    
    # 直接测试服务层
    test_tushare_source()
    
    # 测试 API 端点 (需要后端运行)
    try:
        test_api_endpoints()
    except Exception as e:
        print(f"\n  API 测试跳过 (后端未运行): {e}")
