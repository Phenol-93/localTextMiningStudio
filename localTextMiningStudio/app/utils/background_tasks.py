"""Reusable background task helpers for PySide6 pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot

from app.utils.logging import get_logger, redact_sensitive


TaskCallable = Callable[["TaskContext"], Any]


class TaskCancelled(Exception):
    """Raised when a background task is cancelled cooperatively."""


@dataclass
class TaskContext:
    """Context passed to a background task."""

    progress_callback: Callable[[int, int, str], None] | None = None
    cancelled: bool = False

    def report(self, done: int, total: int, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(max(0, done), max(1, total), message)

    def cancel(self) -> None:
        self.cancelled = True

    def is_cancelled(self) -> bool:
        return self.cancelled

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelled("任务已取消。")


class BackgroundTaskWorker(QObject):
    """Run a callable in a worker thread and emit UI-safe signals."""

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)
    canceled = Signal(str)

    def __init__(self, task_name: str, task: TaskCallable) -> None:
        super().__init__()
        self.task_name = task_name
        self.task = task
        self.context = TaskContext(progress_callback=self.progress.emit)
        self.logger = get_logger("background_tasks")

    @Slot()
    def run(self) -> None:
        try:
            self.context.check_cancelled()
            result = self.task(self.context)
            self.context.check_cancelled()
        except TaskCancelled as error:
            message = safe_error_message(str(error))
            self.logger.info("%s canceled: %s", self.task_name, message)
            self.canceled.emit(message)
        except Exception as error:
            message = safe_error_message(str(error))
            self.logger.exception("%s failed: %s", self.task_name, message)
            self.failed.emit(message)
        else:
            self.finished.emit(result)

    @Slot()
    def cancel(self) -> None:
        self.context.cancel()


def safe_error_message(value: Any, *, limit: int = 500) -> str:
    """Redact secrets and truncate long texts before UI/log display."""
    message = str(redact_sensitive(str(value)))
    message = " ".join(message.split())
    if len(message) > limit:
        return message[:limit] + "..."
    return message
