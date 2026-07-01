"""视频报告生成器

生成统一文件夹：截图 + 时间戳转写 + AI总结
"""
import os
import re
from config import OUTPUT_DIR
from utils.helpers import sanitize_filename
from utils.screenshot import capture_screenshot
from utils.progress import logger


def generate_video_report(
    video_src: str,
    title: str,
    platform: str,
    duration: float,
    transcript_text: str = "",
    summary_text: str = "",
    segment_seconds: int = 15,
) -> str:
    """生成视频完整报告

    输出结构:
      output/{视频名}/
        ├── report.md        ← 完整报告（截图 + 转写 + 总结）
        ├── summary.md       ← AI 总结
        ├── transcript.txt   ← 转写文稿
        └── screenshots/
              ├── 00m00s.jpg
              ├── 00m15s.jpg
              └── ...

    Args:
        video_src: 视频文件路径 或 HTTP(S) 流地址
        title: 视频标题
        platform: 平台名 (bilibili/xiaohongshu)
        duration: 时长（秒）
        transcript_text: 转写文本
        summary_text: AI 总结
        segment_seconds: 截图间隔（秒）

    Returns:
        report.md 文件路径
    """
    safe_title = sanitize_filename(title) if title else "video"
    report_dir = os.path.join(OUTPUT_DIR, safe_title)
    screenshot_dir = os.path.join(report_dir, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    logger.step_begin("生成视频报告")
    logger.detail(f"输出目录: {report_dir}")

    # 1. 截图（如果有视频源）
    screenshots = []
    if video_src:
        timestamps = list(range(0, int(duration) + 1, segment_seconds))
        if timestamps and timestamps[-1] < duration - 2:
            timestamps.append(int(duration) - 1)

        for ts in timestamps:
            ts_str = _fmt_ts(ts)
            path = capture_screenshot(video_src, ts, screenshot_dir, name_prefix=safe_title)
            if path:
                screenshots.append((ts, path))
                logger.detail(f"截图 {ts_str}: {os.path.basename(path)}")
    else:
        logger.detail("无视频源，跳过截图")

    # 2. 生成时间戳段（如已有分段转写则用，否则按比例拆分）
    segments = _make_segments(transcript_text, duration, segment_seconds)

    # 3. 写 report.md
    report_path = os.path.join(report_dir, "report.md")
    platform_names = {"bilibili": "B站", "xiaohongshu": "小红书", "unknown": ""}
    pname = platform_names.get(platform, platform)

    lines = [
        f"# {title}",
        "",
        f"**平台**: {pname}  |  **时长**: {_fmt_duration(duration)}  |  **截图间隔**: {segment_seconds}秒",
        "",
        "---",
        "",
        "## 📸 视频截图 + 转写文稿",
        "",
    ]

    # 对齐截图和文本段
    for i, seg in enumerate(segments):
        t_start, t_end, text = seg

        # 找最接近该段起始时间的截图
        best_ts = None
        best_path = None
        for ts, path in screenshots:
            if ts <= t_end + 2 and (best_ts is None or abs(ts - t_start) < abs(best_ts - t_start)):
                best_ts = ts
                best_path = path

        lines.append(f"### [{_fmt_ts(t_start)} → {_fmt_ts(t_end)}]")
        lines.append("")

        if best_path:
            rel = os.path.relpath(best_path, report_dir)
            lines.append(f"![]({rel})")
            lines.append("")

        if text.strip():
            lines.append(text.strip())
            lines.append("")

    lines.extend([
        "---",
        "",
        "## 🤖 AI 总结",
        "",
    ])
    if summary_text.strip():
        lines.append(summary_text.strip())
    else:
        lines.append("*（无 AI 总结）*")

    lines.append("")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    logger.detail(f"报告已保存: {os.path.basename(report_path)}")

    # 4. 写 summary.md
    if summary_text.strip():
        summary_path = os.path.join(report_dir, "summary.md")
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title} — AI 总结\n\n{summary_text.strip()}\n")
        logger.detail(f"总结已保存: summary.md")

    # 5. 写 transcript.txt
    if transcript_text.strip():
        txt_path = os.path.join(report_dir, "transcript.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n# 转写文稿\n\n{transcript_text.strip()}\n")
        logger.detail(f"转写已保存: transcript.txt")

    logger.step_end()
    logger.detail(f"全部文件 → {report_dir}/")
    return report_path


# ---------- 内部 ----------

def _fmt_ts(seconds: float) -> str:
    """15.0 → '00m15s'"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}h{m:02d}m{s:02d}s"
    return f"{m:02d}m{s:02d}s"


def _fmt_duration(seconds: float) -> str:
    """125 → '2分5秒'"""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}分{s}秒"
    return f"{s}秒"


def _make_segments(text: str, duration: float, seg_sec: int) -> list:
    """将文本按时间分段

    如果文本中包含时间戳标记 [HH:MM:SS - HH:MM:SS] 则解析；
    否则按字数比例拆分。

    Returns:
        [(start_sec, end_sec, text), ...]
    """
    if not text:
        # 无文本时生成空段
        segments = []
        for t in range(0, int(duration) + 1, seg_sec):
            end = min(t + seg_sec, duration)
            if t < duration:
                segments.append((float(t), end, ""))
        return segments

    # 尝试解析已有时间戳
    ts_pattern = re.compile(
        r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?\s*[-–]\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*\n'
    )
    matches = list(ts_pattern.finditer(text))
    if matches:
        segments = []
        for m in matches:
            h1, m1, s1 = (int(m.group(1)), int(m.group(2)),
                          int(m.group(3) or 0))
            h2, m2, s2 = (int(m.group(4)), int(m.group(5)),
                          int(m.group(6) or 0))
            start = h1 * 3600 + m1 * 60 + s1
            end = h2 * 3600 + m2 * 60 + s2
            seg_text = text[m.end():]
            next_m = ts_pattern.search(text, m.end())
            if next_m:
                seg_text = text[m.end():next_m.start()]
            seg_text = seg_text.strip()
            segments.append((float(start), float(end), seg_text))
        return segments

    # 按字数比例拆分
    segments = []
    total_chars = len(text)
    if total_chars == 0:
        return []

    chars_per_sec = total_chars / duration if duration > 0 else 0
    for t in range(0, int(duration) + 1, seg_sec):
        end = min(t + seg_sec, duration)
        if t >= duration:
            break
        start_pos = int(t * chars_per_sec)
        end_pos = int(end * chars_per_sec)
        seg_text = text[start_pos:end_pos].strip()
        segments.append((float(t), end, seg_text))
    return segments
