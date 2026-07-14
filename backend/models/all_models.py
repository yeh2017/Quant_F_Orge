from sqlalchemy import Column, Integer, String, Float, JSON, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from core.database import Base
from models.mixins import TimestampMixin

class User(Base, TimestampMixin):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Integer, default=1)
    
    strategies = relationship("Strategy", back_populates="owner")
    backtests = relationship("BacktestResult", back_populates="owner")

class Strategy(Base, TimestampMixin):
    __tablename__ = "strategies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    strategy_type = Column(String)  # multifactor, etc.
    parameters = Column(JSON)       # {factors: [], weights: {}}
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    owner = relationship("User", back_populates="strategies")
    backtests = relationship("BacktestResult", back_populates="strategy")

class BacktestResult(Base, TimestampMixin):
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # 异步任务关联
    task_id = Column(String(64), nullable=True, unique=True, index=True, comment="异步任务ID")
    strategy_type = Column(String(32), nullable=True, comment="策略类型")
    codes = Column(Text, nullable=True, comment="股票代码 JSON")
    universe_config = Column(Text, nullable=True, comment="动态标的池配置 JSON")
    start_date = Column(String(16), nullable=True)
    end_date = Column(String(16), nullable=True)

    # 结果摘要
    total_return = Column(Float)
    annual_return = Column(Float)
    max_drawdown = Column(Float)
    sharpe_ratio = Column(Float)
    win_rate = Column(Float, nullable=True, comment="胜率(%)")

    # 完整结果
    result_data = Column(JSON, nullable=True)       # 原有字段保留
    result_json = Column(Text, nullable=True, comment="完整回测结果 JSON")  # 新增

    strategy = relationship("Strategy", back_populates="backtests")
    owner = relationship("User", back_populates="backtests")

    __table_args__ = (
        Index('idx_bt_task_id', 'task_id'),
        Index('idx_bt_strategy_date', 'strategy_type', 'created_at'),
        {"extend_existing": True},
    )
