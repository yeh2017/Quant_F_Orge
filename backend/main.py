"""
QFO量化回测平台 — 主入口
========================
职责：应用创建 + CORS + 路由注册 + 全局异常处理 + 定时任务调度。
所有业务路由已拆分至 routers/ 目录。
"""

import os
import sys

# 添加当前目录(backend)和上级目录(项目根目录) to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

# Apply SSL fix before any other imports
try:
    from utils.ssl_fix import apply_ssl_fix, patch_akshare
    apply_ssl_fix()
    patch_akshare()
except ImportError:
    pass

from dotenv import load_dotenv
load_dotenv()

import asyncio as _asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import datetime as _dt, timedelta as _td

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Logging Init（必须在所有模块导入之前）
from core.logging_config import setup_logging
setup_logging()

# Database Init
from core.database import engine, Base
from models import all_models  # 确保业务表被注册到 Base.metadata
from models import quant_data  # noqa: F401 — 副作用导入，注册 19 个数仓表到 Base.metadata
Base.metadata.create_all(bind=engine)


# ── 全局 JSON 安全工具 ──
from utils.json_utils import sanitize


# ── 定时清理调度 ──

async def _daily_cleanup_loop():
    import structlog as _sl
    _log = _sl.get_logger("cleanup_scheduler")
    while True:
        now = _dt.now()
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += _td(days=1)
        wait_secs = (next_run - now).total_seconds()
        _log.info("cleanup_scheduled",
                  next_run=next_run.strftime("%Y-%m-%d %H:%M"),
                  wait_secs=int(wait_secs))
        await _asyncio.sleep(wait_secs)
        try:
            from jobs.cleanup_job import run_all_cleanups
            result = run_all_cleanups()
            _log.info("cleanup_done", result=result)
        except Exception as e:
            _log.error("cleanup_error", error=str(e))


# ── 新闻定时抓取 ──

_NEWS_CONFIG_FILE = os.path.join(current_dir, ".news_auto_config.json")

def _load_news_config():
    """从本地文件加载配置，以上次保存的设置为准"""
    import json
    try:
        with open(_NEWS_CONFIG_FILE, "r") as f:
            cfg = json.load(f)
            return cfg.get("enabled", False), cfg.get("interval_hours", 4)
    except (FileNotFoundError, json.JSONDecodeError):
        return False, 4

def save_news_config(enabled, hours):
    """持久化到文件"""
    import json
    with open(_NEWS_CONFIG_FILE, "w") as f:
        json.dump({"enabled": enabled, "interval_hours": hours}, f)

_news_auto_enabled, _news_auto_fetch_hours = _load_news_config()
_next_fetch_time: _dt | None = None     # 下次自动抓取时间（供 API 暴露）
_last_fetch_time: _dt | None = None     # 上次自动抓取时间
_fetch_now_flag = False                  # 外部请求立即执行标记

async def _news_auto_fetch_loop():
    import structlog as _sl
    global _news_auto_enabled, _news_auto_fetch_hours, _next_fetch_time, _last_fetch_time, _fetch_now_flag
    _log = _sl.get_logger("news_scheduler")
    if _news_auto_fetch_hours <= 0:
        _news_auto_enabled = False
        _log.info("news_auto_fetch_disabled")
        return
    _log.info("news_auto_fetch_start", interval_hours=_news_auto_fetch_hours)

    # 首次启动：等满 interval 后执行（避免重启时立刻抓取）
    _next_fetch_time = _dt.now() + _td(hours=_news_auto_fetch_hours) if _news_auto_enabled else None

    while True:
        # 关闭状态：清除倒计时，低频轮询等待重新开启
        if not _news_auto_enabled:
            _next_fetch_time = None
            await _asyncio.sleep(60)
            continue

        # 开启状态：按 30s 粒度 sleep，支持中途检测 enabled 变化和立即执行标记
        # 循环条件统一守卫：await 让出控制权期间 HTTP handler 可能修改 _next_fetch_time / _news_auto_enabled
        if _next_fetch_time is None:
            _next_fetch_time = _dt.now() + _td(hours=_news_auto_fetch_hours)

        while _news_auto_enabled and _next_fetch_time is not None and _dt.now() < _next_fetch_time:
            if _fetch_now_flag:
                _fetch_now_flag = False
                break
            remaining = (_next_fetch_time - _dt.now()).total_seconds()
            await _asyncio.sleep(min(30, max(1, remaining)))

        if not _news_auto_enabled:
            _log.info("news_auto_fetch_paused")
            continue

        # 执行抓取
        try:
            from jobs.sync_news import sync_stock_news
            from core.database import db_session
            from models.quant_data import StockBasicInfo
            with db_session() as db:
                rows = db.query(StockBasicInfo.code, StockBasicInfo.name).filter(
                    StockBasicInfo.is_active == True
                ).all()
                names = {r.code: r.name for r in rows if r.name}
            if names:
                count = sync_stock_news([], stock_names=names)
                _log.info("news_auto_fetched", inserted=count)
            _last_fetch_time = _dt.now()
        except Exception as e:
            _log.error("news_auto_fetch_error", error=str(e))

        # 计算下次执行时间
        _next_fetch_time = _dt.now() + _td(hours=_news_auto_fetch_hours)

# ── 每日摘要推送 ──

async def _daily_summary_loop():
    """按 .notify_config.json 中 summary_push_hours 定时推送新闻摘要"""
    import structlog as _sl
    _log = _sl.get_logger("summary_scheduler")
    while True:
        # 每轮重新读取配置，支持前端热更新
        from services.notifier import load_config
        push_hours = load_config().get("summary_push_hours", [])
        if not push_hours:
            # 空列表 = 关闭推送，静默等待后重新检查
            await _asyncio.sleep(600)
            continue
        now = _dt.now()
        # 找今天最近的下一个推送时间点
        candidates = []
        for h in push_hours:
            t = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if t > now:
                candidates.append(t)
        if not candidates:
            # 今天的都过了，取明天最早的
            next_run = now.replace(hour=min(push_hours), minute=0, second=0, microsecond=0) + _td(days=1)
        else:
            next_run = min(candidates)
        wait_secs = (next_run - now).total_seconds()
        _log.info("summary_scheduled", next_run=next_run.strftime("%Y-%m-%d %H:%M"))
        await _asyncio.sleep(wait_secs)
        try:
            from jobs.daily_summary import send_daily_summary
            send_daily_summary()
        except Exception as e:
            _log.error("summary_error", error=str(e))


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan：启动时运行 DB 迁移 + 注册定时任务"""
    from core.database import migrate_backtest_results, migrate_stock_news, migrate_financial_columns
    migrate_backtest_results()
    migrate_stock_news()
    migrate_financial_columns()
    _asyncio.create_task(_daily_cleanup_loop())
    _asyncio.create_task(_news_auto_fetch_loop())
    _asyncio.create_task(_daily_summary_loop())
    yield


# ── 全局 NaN/Inf 安全：自定义 JSON 编码器 ──
import json as _json
import math as _math
import numpy as _np
from starlette.responses import JSONResponse as _BaseJSONResponse


class SafeJSONEncoder(_json.JSONEncoder):
    """将 NaN/Inf 编码为 null，兼容 numpy 类型"""

    def default(self, o):
        if isinstance(o, (_np.integer,)):
            return int(o)
        if isinstance(o, (_np.floating,)):
            v = float(o)
            if _math.isnan(v) or _math.isinf(v):
                return None
            return v
        if isinstance(o, _np.ndarray):
            return o.tolist()
        if isinstance(o, _np.bool_):
            return bool(o)
        return super().default(o)

    def encode(self, o):
        return super().encode(self._clean_nan(o))

    def _clean_nan(self, obj):
        if isinstance(obj, float):
            if _math.isnan(obj) or _math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: self._clean_nan(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._clean_nan(v) for v in obj]
        return obj


class SafeJSONResponse(_BaseJSONResponse):
    def render(self, content) -> bytes:
        return _json.dumps(
            content,
            cls=SafeJSONEncoder,
            ensure_ascii=False,
        ).encode("utf-8")


# Monkey-patch 原生 JSONResponse.render
# 子路由器 APIRouter() 默认用 JSONResponse 而非 SafeJSONResponse，
# 只设 default_response_class 无法覆盖子路由。
# 直接 patch 基类确保所有路由（含子路由器）都走安全编码。
_BaseJSONResponse.render = SafeJSONResponse.render  # type: ignore[assignment]


# ── FastAPI 应用 ──

app = FastAPI(
    title="QFO量化回测平台",
    description="多数据源集成 | 因子模块 | 策略回测 | 组合优化",
    version="1.0.1",
    lifespan=lifespan,
)




app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    traceback.print_exc()
    return SafeJSONResponse(
        status_code=500,
        content={"detail": f"服务端错误: {str(exc)}"}
    )



# ── 注册所有路由 ──

from routers.data_center import router as data_center_router
from routers.screener import router as screener_router
from routers.bonds import router as bonds_router
from routers.risk import router as risk_router
from routers.portfolio import router as portfolio_router
from routers.stocks import router as stocks_router
from routers.factors import router as factors_router
from routers.backtest import router as backtest_router
from routers.ws import router as ws_router
from routers.news import router as news_router
from routers.research import router as research_router
from routers.system_config import router as system_config_router

app.include_router(data_center_router, prefix="/api")
app.include_router(screener_router, prefix="/api")
app.include_router(bonds_router, prefix="/api")
app.include_router(risk_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(stocks_router, prefix="/api")
app.include_router(factors_router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(ws_router, prefix="/api")
app.include_router(news_router, prefix="/api")
app.include_router(research_router, prefix="/api")
app.include_router(system_config_router)


# ── 策略管理 CRUD（轻量，留在 main 中）──

from fastapi import Depends
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.strategy import StrategyCreate, StrategyResponse
from typing import List


@app.get("/api/strategies", response_model=List[StrategyResponse])
async def get_strategies(db: Session = Depends(get_db)):
    return db.query(all_models.Strategy).all()


@app.post("/api/strategies", response_model=StrategyResponse)
async def create_strategy(strategy: StrategyCreate, db: Session = Depends(get_db)):
    db_strategy = all_models.Strategy(
        name=strategy.name,
        description=strategy.description,
        strategy_type=strategy.strategy_type,
        parameters=strategy.parameters,
    )
    db.add(db_strategy)
    db.flush()
    db.refresh(db_strategy)
    return db_strategy


@app.delete("/api/strategies/{strategy_id}")
async def delete_strategy(strategy_id: int, db: Session = Depends(get_db)):
    strategy = db.query(all_models.Strategy).filter(
        all_models.Strategy.id == strategy_id
    ).first()
    if not strategy:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not found")
    db.delete(strategy)
    return {"success": True}


# ── 管理端点 ──

@app.post("/api/admin/cleanup")
async def manual_cleanup():
    try:
        from jobs.cleanup_job import run_all_cleanups
        result = run_all_cleanups()
        return {"status": "ok", "result": sanitize(result)}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


# ── 启动 ──

if __name__ == "__main__":
    import uvicorn
    import structlog as _sl

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    _sl.get_logger("main").info("server_start", host=host, port=port)
    uvicorn.run("main:app", host=host, port=port, reload=False)
