from sqlalchemy import Column, DateTime
from datetime import datetime

class TimestampMixin:
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
