from typing import Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

class StrategyBase(BaseModel):
    name: str
    description: Optional[str] = None
    strategy_type: str
    parameters: Dict[str, Any]

class StrategyCreate(StrategyBase):
    pass

class StrategyResponse(StrategyBase):
    id: int
    owner_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
