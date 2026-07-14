import uuid
import time
from typing import Dict, Any, Optional
from enum import Enum
from threading import Lock


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    IN_PROGRESS = "running"    # 废弃，统一用 RUNNING
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStore:
    """简单的内存任务存储，带防重复提交功能"""

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def create_task(self, task_type: str) -> str:
        """创建新任务（自动清理旧任务）"""
        self.cleanup_old_tasks()
        task_id = str(uuid.uuid4())
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "type": task_type,
                "status": TaskStatus.PENDING,
                "created_at": time.time(),
                "updated_at": time.time(),
                "result": None,
                "error": None,
            }
        return task_id

    def update_task(self, task_id: str, status: TaskStatus, result: Any = None, error: str = None):
        """更新任务状态"""
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                task["status"] = status
                task["updated_at"] = time.time()
                if result is not None:
                    task["result"] = result
                if error is not None:
                    task["error"] = error
        # 异步广播到 WebSocket（best-effort）
        self._broadcast_update(task_id)

    def _broadcast_update(self, task_id: str):
        """将任务状态推送到所有 WebSocket 连接（线程安全）"""
        try:
            from routers.ws import manager
            task = self._tasks.get(task_id)
            if not task or not manager.active:
                return
            msg = {
                "type": "task_update",
                "payload": {
                    "task_id": task_id,
                    "task_type": task.get("type"),
                    "status": task["status"],
                    "result": task.get("result"),
                    "error": task.get("error"),
                }
            }
            manager.broadcast_threadsafe(msg)
        except Exception:
            pass  # best-effort，绝不影响主流程

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务信息"""
        with self._lock:
            return self._tasks.get(task_id)

    def get_running_task(self, task_type: str) -> Optional[str]:
        """
        返回当前正在运行的同类型任务 ID。
        若不存在则返回 None。
        用于防止重复提交同类型长任务（如 full_sync）。
        """
        with self._lock:
            for tid, task in self._tasks.items():
                if task["type"] == task_type and task["status"] in (
                    TaskStatus.PENDING, TaskStatus.RUNNING,
                ):
                    return tid
        return None

    def has_any_running_sync(self) -> Optional[str]:
        """
        检查是否有任何同步类任务在运行（跨类型互斥）。
        SQLite 不支持并发写，需要阻止同时运行多个写任务。
        返回正在运行的任务类型，或 None。
        """
        sync_keywords = ("sync", "signal")
        with self._lock:
            for tid, task in self._tasks.items():
                if task["status"] in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    if any(kw in task["type"] for kw in sync_keywords):
                        return task["type"]
        return None

    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """清理已结束的旧任务"""
        current_time = time.time()
        with self._lock:
            to_remove = [
                tid for tid, task in self._tasks.items()
                if (current_time - task["updated_at"] > max_age_seconds
                    and task["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED))
            ]
            for tid in to_remove:
                del self._tasks[tid]


# 全局实例
task_store = TaskStore()
