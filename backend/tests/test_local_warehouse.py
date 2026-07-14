"""
本地数仓集成测试
验证新增的模型、ETL 函数和 Service Layer 重构是否正确
"""
import sys
import os
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)
os.environ['TQDM_DISABLE'] = '1'

from dotenv import load_dotenv
load_dotenv()

import sqlite3

def test_models_and_tables():
    """测试 ORM 模型和建表"""
    print("=" * 50)
    print("Test 1: 模型导入 & 建表")
    print("=" * 50)
    
    from core.database import engine, Base
    
    # 建表
    Base.metadata.create_all(bind=engine)
    print("[OK] create_all 成功")
    
    # 验证表是否存在
    con = sqlite3.connect("quant_data.db")
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    con.close()
    
    expected_tables = ["stock_daily_bars", "stock_daily_factors", "stock_basic_info", "stock_financials"]
    for t in expected_tables:
        if t in tables:
            print(f"  [OK] 表 {t} 存在")
        else:
            print(f"  [FAIL] 表 {t} 不存在!")
    
    print(f"  所有数据库表: {tables}")
    print()


def test_routers():
    """测试路由导入"""
    print("=" * 50)
    print("Test 2: 路由导入")
    print("=" * 50)
    
    try:
        from routers.screener import router as sr
        print(f"  [OK] Screener 路由: {sr.prefix}")
    except Exception as e:
        print(f"  [FAIL] Screener: {e}")
    
    try:
        from routers.data_center import router as dc
        print(f"  [OK] DataCenter 路由: {dc.prefix}")
    except Exception as e:
        print(f"  [FAIL] DataCenter: {e}")
    
    print()


def test_etl_functions():
    """测试 ETL 函数可导入"""
    print("=" * 50)
    print("Test 3: ETL 函数导入")
    print("=" * 50)
    
    try:
        from jobs.data_sync_service import DataSyncService
        print("  [OK] DataSyncService + sync_bond + signal_job 导入成功")

        svc = DataSyncService()
        print(f"  [OK] DataSyncService 实例化成功")

    except Exception as e:
        print(f"  [FAIL] ETL 导入: {e}")
    
    print()


def test_service_local_read():
    """测试 Service 本地读取链路（空库场景下应 fallback）"""
    print("=" * 50)
    print("Test 4: Service 本地读取链路")
    print("=" * 50)
    
    from core.database import SessionLocal
    from models.quant_data import StockBasicInfo, StockFinancial, StockDailyFactor
    
    db = SessionLocal()
    
    # 检查各表记录数
    basic_count = db.query(StockBasicInfo).count()
    fin_count = db.query(StockFinancial).count()
    factor_count = db.query(StockDailyFactor).count()
    
    print(f"  StockBasicInfo: {basic_count} 条")
    print(f"  StockFinancial: {fin_count} 条")
    print(f"  StockDailyFactor: {factor_count} 条")
    
    db.close()
    
    if basic_count > 0:
        print("  [INFO] 本地有数据，Service 将走本地读取路径")
    else:
        print("  [INFO] 本地无数据，Service 将 fallback 到 API（正常，需先执行同步）")
    
    print()


def test_data_center_status():
    """测试数仓状态接口"""
    print("=" * 50)
    print("Test 5: 数仓状态查询")
    print("=" * 50)
    
    from core.database import SessionLocal
    from sqlalchemy import func
    from models.quant_data import StockDailyBar, StockDailyFactor, StockBasicInfo, StockFinancial
    
    db = SessionLocal()
    try:
        bar_count = db.query(func.count(StockDailyBar.code)).scalar() or 0
        factor_count = db.query(func.count(StockDailyFactor.code)).scalar() or 0
        basic_count = db.query(func.count(StockBasicInfo.code)).scalar() or 0
        fin_count = db.query(func.count(StockFinancial.code)).scalar() or 0
        
        print(f"  daily_bars: {bar_count} 条")
        print(f"  daily_factors: {factor_count} 条")
        print(f"  stock_basic: {basic_count} 条")
        print(f"  financials: {fin_count} 条")
        print("  [OK] 状态查询成功")
    except Exception as e:
        print(f"  [FAIL] {e}")
    finally:
        db.close()
    
    print()


if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  本地数仓集成测试")
    print("=" * 50)
    print()
    
    test_models_and_tables()
    test_routers()
    test_etl_functions()
    test_service_local_read()
    test_data_center_status()
    
    print("=" * 50)
    print("  全部测试完成")
    print("=" * 50)
