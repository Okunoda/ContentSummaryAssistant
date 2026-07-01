"""视频截图工具

使用 ffmpeg 从视频中抽取指定时刻的帧。
"""
import os
import subprocess
from config import OUTPUT_DIR


def capture_screenshot(src: str, timestamp: float,
                       output_dir: str = OUTPUT_DIR,
                       name_prefix: str = "") -> str:
    """从视频指定时刻截取一帧（支持本地文件或远程 URL）

    Args:
        src: 视频文件路径 或 HTTP(S) 流地址
        timestamp: 时间点（秒），支持小数如 10.5
        output_dir: 输出目录
        name_prefix: 输出文件名前缀（URL 模式下必填）

    Returns:
        截图文件路径，失败返回空字符串
    """
    is_url = src.startswith("http://") or src.startswith("https://")

    if not is_url and not os.path.exists(src):
        return ""

    # 文件名
    base = name_prefix or os.path.splitext(os.path.basename(src))[0]
    ts_str = _fmt_ts(timestamp)
    out_file = os.path.join(output_dir, f"{base}_screenshot_{ts_str}.jpg")

    if os.path.exists(out_file):
        return out_file  # 已存在，跳过

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", src,
        "-vframes", "1",
        "-q:v", "2",
        out_file,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and os.path.exists(out_file):
            return out_file
    except Exception:
        pass
    return ""


def capture_screenshots(src: str, timestamps: list[float],
                        output_dir: str = OUTPUT_DIR,
                        name_prefix: str = "") -> list[tuple[float, str]]:
    """批量截取多帧

    Returns:
        [(timestamp, filepath), ...] 成功的结果列表
    """
    results = []
    for ts in timestamps:
        path = capture_screenshot(src, ts, output_dir, name_prefix)
        if path:
            results.append((ts, path))
    return results


# ---------- 内部 ----------

def _fmt_ts(seconds: float) -> str:
    """格式化时间: 15.5 → '15.5s'"""
    s = f"{seconds:.1f}".rstrip('0').rstrip('.')
    return f"{s}s"
