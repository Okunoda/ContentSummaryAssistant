"""全流程日志系统 — 同时输出控制台和 UI 回调"""
import sys
import time
from datetime import datetime


class Logger:
    """统一日志：控制台 + UI 状态更新"""

    def __init__(self):
        self._ui_callback = None
        self._start_time = time.time()
        self._step_count = 0

    def set_ui(self, callback):
        """设置 UI 回调函数（Gradio generator yield 用）"""
        self._ui_callback = callback

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _elapsed(self) -> str:
        return f"{time.time() - self._start_time:.1f}s"

    def _emit(self, level: str, icon: str, message: str):
        """输出到控制台 + UI"""
        ts = self._ts()
        elapsed = self._elapsed()
        line = f"[{ts}] [{elapsed}] {icon} {message}"
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
        # UI 回调
        if self._ui_callback:
            self._ui_callback(f"{icon} {message}")

    def step_begin(self, step_name: str):
        """标记一个步骤开始"""
        self._step_count += 1
        self._emit("STEP", f"▶ [{self._step_count}]", step_name)

    def step_end(self, result: str = "完成"):
        self._emit("STEP", f"✓", result)

    def info(self, message: str):
        self._emit("INFO", "📎", message)

    def detail(self, message: str):
        """子步骤详情"""
        self._emit("DETAIL", "  └─", message)

    def progress(self, current: int, total: int, label: str = ""):
        """进度条（如百分比）"""
        pct = current * 100 // total if total else 0
        self._emit("PROG", f"▌{pct}%", f"{label} ({current}/{total})" if label else f"{current}/{total}")

    def warn(self, message: str):
        self._emit("WARN", "⚠️", message)

    def error(self, message: str):
        self._emit("ERROR", "❌", message)

    def success(self, message: str = "完成"):
        self._emit("DONE", "✅", f"{message} (耗时 {self._elapsed()})")


# 全局单例
logger = Logger()
