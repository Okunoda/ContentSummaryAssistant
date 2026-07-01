"""
VideoCraw - 多平台内容获取与总结工具

主应用入口 - 基于 Gradio 的可视化面板
支持: B站视频、小红书视频、微信公众号文章、任意博客
"""
import os
import sys

# 确保 localhost 不走代理（否则 httpx/Gradio 启动时连接自己也会被代理拦截）
for _no_proxy_var in ("NO_PROXY", "no_proxy"):
    existing = os.environ.get(_no_proxy_var, "")
    if "localhost" not in existing:
        os.environ[_no_proxy_var] = (existing + ",localhost,127.0.0.1,0.0.0.0").strip(",")

import gradio as gr

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(__file__))

from crawlers import get_crawler, VideoResult, ArticleResult
from processor import Transcriber, Summarizer, XfyunASR, generate_video_report
from utils.helpers import detect_platform, is_video_url
from utils.progress import logger
from config import (
    LLM_API_KEY as _LLM_API_KEY,
    OUTPUT_DIR,
    ASR_ENGINE,
    XF_IAT_APP_ID, XF_IAT_API_KEY, XF_IAT_API_SECRET,
    XF_IAT_FAST, XF_IAT_SEGMENT_SECONDS,
)


# --- 启动诊断 ---
def run_diagnostics() -> dict:
    """检查外部依赖是否可用"""
    import subprocess
    status = {
        "ffmpeg": False,
        "yt_dlp": False,
        "bilibili_api": False,
        "faster_whisper": False,
        "llm_api": False,
    }
    # ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        status["ffmpeg"] = True
    except Exception:
        try:
            subprocess.run(["/opt/homebrew/bin/ffmpeg", "-version"], capture_output=True, timeout=5)
            status["ffmpeg"] = True
        except Exception:
            pass

    # yt-dlp
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
        status["yt_dlp"] = True
    except Exception:
        pass

    # bilibili-api
    try:
        import bilibili_api
        status["bilibili_api"] = True
    except ImportError:
        pass

    # faster-whisper
    try:
        import faster_whisper
        status["faster_whisper"] = True
    except ImportError:
        pass

    # LLM API Key
    status["llm_api"] = bool(_LLM_API_KEY)

    return status

_diag = run_diagnostics()

_diag_html = '<div class="status-row">'
for key, label in [("ffmpeg", "ffmpeg"), ("yt_dlp", "yt-dlp"), ("bilibili_api", "bili"), ("faster_whisper", "whisper"), ("llm_api", "llm")]:
    cls = "ok" if _diag[key] else ""
    _diag_html += f'<span class="{cls}">{label}</span>'
_diag_html += '</div>'

# --- 全局处理器实例 ---
def _create_asr():
    """根据配置创建语音转文字引擎"""
    if ASR_ENGINE == "xfyun" and XF_IAT_APP_ID:
        asr = XfyunASR(
            app_id=XF_IAT_APP_ID,
            api_key=XF_IAT_API_KEY,
            api_secret=XF_IAT_API_SECRET,
            fast=XF_IAT_FAST,
            segment_seconds=XF_IAT_SEGMENT_SECONDS,
        )
        if asr.is_configured:
            logger.info("使用讯飞语音听写 (XfyunASR)")
            return asr
    logger.info("使用本地 Whisper 语音转文字")
    return Transcriber()

transcriber = _create_asr()
summarizer = Summarizer()


# --- CSS 样式 ---
CUSTOM_CSS = """
.gradio-container { max-width: 100% !important; width: 100% !important; margin: 0 !important; padding: 1.5rem 3rem !important; }
.gradio-container .contain { max-width: 100% !important; width: 100% !important; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
footer { visibility: hidden; }

/* ----- 悬浮卡片效果 ----- */
.gradio-container textarea {
    background: #fafbfd !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02) !important;
    transition: box-shadow 0.2s, transform 0.2s, border-color 0.2s !important;
    padding: 0.8rem 1rem !important;
}
.gradio-container textarea:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04) !important;
    transform: scale(1.005) !important;
    border-color: #d1d5db !important;
}
.gradio-container textarea:focus {
    box-shadow: 0 4px 16px rgba(99,102,241,0.1), 0 2px 6px rgba(99,102,241,0.05) !important;
    transform: scale(1.005) !important;
    border-color: #6366f1 !important;
    outline: none !important;
}

/* ----- 按钮悬浮 ----- */
.gradio-container button {
    transition: box-shadow 0.2s, transform 0.2s !important;
}
.gradio-container button:hover {
    transform: scale(1.03) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
}

/* ----- 结果卡片 ----- */
.result-box {
    font-size: 0.9rem !important; line-height: 1.7 !important; color: #374151 !important;
    padding: 1.25rem !important; border: 1px solid #eef0f2 !important;
    background: #fafbfd !important; border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03) !important;
    transition: box-shadow 0.2s, transform 0.2s !important;
}
.result-box:hover {
    box-shadow: 0 4px 14px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.03) !important;
    transform: scale(1.003) !important;
}
.result-box h1, .result-box h2, .result-box h3 { color: #111827 !important; font-weight: 600 !important; }
.result-box code { background: #f3f4f6; color: #e11d48; padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
.result-box pre { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; overflow-x: auto; }
.result-box blockquote { border-left: 3px solid #6366f1; margin-left: 0; padding-left: 1rem; color: #6b7280; }

.summary-box {
    font-size: 0.9rem !important; line-height: 1.7 !important; color: #374151 !important;
    padding: 1.25rem !important; border: 1px solid #eef0f2 !important;
    background: #fafbfd !important; border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03) !important;
    transition: box-shadow 0.2s, transform 0.2s !important;
}
.summary-box:hover {
    box-shadow: 0 4px 14px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.03) !important;
    transform: scale(1.003) !important;
}

.status-row {
    display: flex; gap: 16px; justify-content: center;
    padding: 8px 0; margin-bottom: 12px; font-size: 0.75rem; color: #9ca3af;
}
.status-row span { display: flex; align-items: center; gap: 4px; }
.status-row span::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #d1d5db; }
.status-row span.ok::before { background: #22c55e; }

.platform-tag { display: inline-block; padding: 2px 10px; border-radius: 100px; font-size: 0.72rem; font-weight: 600; }
.tag-bilibili { background: #ffe4ec; color: #e11d48; }
.tag-xiaohongshu { background: #ffe4e4; color: #dc2626; }
.tag-wechat { background: #dcfce7; color: #16a34a; }
"""


# --- 演示数据 ---
DEMO_DATA = {
    "bilibili": {
        "title": "Python 异步编程最佳实践 - Async/Await 深度解析",
        "platform_tag": '<span class="platform-tag tag-bilibili">B站 演示</span>',
        "transcript": (
            "大家好，今天我们来深入探讨 Python 的异步编程。\n\n"
            "首先，我们需要理解什么是协程。协程是一种可以在执行中暂停和恢复的函数。"
            "在 Python 中，我们使用 async def 来定义协程，使用 await 来等待协程的执行结果。\n\n"
            "异步编程的核心优势在于 IO 密集型任务。当程序需要等待网络请求或文件读取时，"
            "事件循环可以切换到其他任务，从而充分利用 CPU 时间。\n\n"
            "常见的坑包括：在协程中使用同步阻塞调用会导致整个事件循环卡住；"
            "忘记 await 协程对象不会执行它；以及在非异步环境中调用异步函数。\n\n"
            "最后推荐几个实用库：aiohttp 用于异步 HTTP 请求，"
            "aiomysql 用于异步数据库操作，fastapi 是目前最快的异步 Web 框架之一。"
        ),
        "summary": (
            "### 🤖 AI 总结\n\n"
            "**一句话概括：** 这是一期深入讲解 Python 异步编程核心概念和实战技巧的教学视频。\n\n"
            "**核心要点：**\n"
            "1. 协程通过 async/await 实现，可在 IO 等待时让出控制权\n"
            "2. 异步编程最大优势是提升 IO 密集型任务的并发性能\n"
            "3. 常见错误：协程中混用同步阻塞调用、忘记 await、在同步环境调用异步函数\n"
            "4. 推荐工具：aiohttp、aiomysql、FastAPI\n\n"
            "**适合人群：** 有 Python 基础，希望提升后端开发性能的中级开发者"
        ),
    },
    "xiaohongshu": {
        "title": "3天2夜成都美食探店之旅 🌶️ 本地人强推的隐藏小店",
        "platform_tag": '<span class="platform-tag tag-xiaohongshu">小红书 演示</span>',
        "transcript": (
            "姐妹们！这次去成都真的吃爽了！给大家分享几家本地人推荐的神仙店铺。\n\n"
            "第一家：藏在玉林小区里的老火锅，锅底才 28 块，毛肚新鲜到弹牙！"
            "必点：鲜鸭血、鹅肠、黄喉。人均 60 吃到扶墙走。\n\n"
            "第二家：建设巷的甜不辣，开了 20 年的老字号。"
            "他们家的酱料是秘制的，甜中带辣，蘸什么都好吃。\n\n"
            "第三家：宽窄巷子附近的蛋烘糕，真的是成都人从小吃到大的味道。"
            "推荐奶油肉松口味，外酥里嫩绝了！\n\n"
            "最后提醒：成都菜偏辣，不太能吃辣的宝宝记得点微辣哦！"
        ),
        "summary": (
            "### 🤖 AI 总结\n\n"
            "**一句话概括：** 一份来自本地人推荐的成都隐藏美食地图。\n\n"
            "**核心要点：**\n"
            "1. 玉林老火锅：锅底28元，毛肚鲜嫩，人均60元超高性价比\n"
            "2. 建设巷甜不辣：20年老店，秘制酱料是灵魂\n"
            "3. 宽窄巷子蛋烘糕：推荐奶油肉松口味，成都人童年回忆\n"
            "4. 辣度警告：不太能吃辣记得选微辣\n\n"
            "**适合人群：** 计划去成都旅游、热爱美食探店的朋友"
        ),
    },
    "wechat": {
        "title": "深度解析：2024年AI行业十大趋势与投资机会",
        "platform_tag": '<span class="platform-tag tag-wechat">微信公众号 演示</span>',
        "content_md": (
            "> 本文首发于「科技前沿观察」，作者：李明\n\n"
            "## 引言\n\n"
            "2024年是AI行业从技术爆发走向商业化落地的关键一年。"
            "本文将从技术、产业、投资三个维度，全面解析AI行业的最新趋势。\n\n"
            "## 一、大模型走向垂直化\n\n"
            "通用大模型的竞争已趋于白热化，头部玩家格局基本确定。"
            "2024年最大的机会在于垂直领域模型——法律、医疗、金融、教育等行业的专用模型将迎来爆发。\n\n"
            "## 二、Agent 从概念走向产品\n\n"
            "AI Agent 不再只是论文里的概念。微软 Copilot、Claude Code 等产品已经展示了"
            "Agent 在实际工作场景中的巨大价值。能够自主规划、执行、验证的 AI 系统正在改变软件开发、"
            "数据分析等行业的工作方式。\n\n"
            "## 三、多模态成为标配\n\n"
            "GPT-4V、Gemini、Claude 3 等模型都已经支持图像理解。"
            "视频生成领域 Sora 的出现更是震撼了整个影视行业。"
            "多模态能力不再是加分项，而是基础能力。\n\n"
            "## 结语\n\n"
            "AI 正在以前所未有的速度改变世界。"
            "对于创业者和投资者来说，关键是找到技术与实际需求的结合点。"
        ),
        "summary": (
            "### 🤖 AI 总结\n\n"
            "**一句话概括：** 从技术、产业、投资三维度解析 2024 AI 行业十大趋势。\n\n"
            "**核心观点：**\n"
            "1. 大模型从通用走向垂直——法律、医疗、金融等行业模型是下一个蓝海\n"
            "2. AI Agent 产品化——Copilot、Claude Code 等已验证商业化可行性\n"
            "3. 多模态能力成为标配——图像/视频/语音理解不再是加分项\n"
            "4. 投资机会在技术与实际需求的结合点\n\n"
            "**适合人群：** AI 行业从业者、科技投资者、创业者"
        ),
    },
}


def _run_demo(enable_llm: bool) -> tuple:
    """演示模式 - 展示三种平台的模拟处理结果"""
    status = "🎮 演示模式"
    title = "演示：三种平台内容获取与 AI 总结"
    platform_tag = ""
    content_parts = []
    summary_parts = []
    download_parts = []

    for platform, data in DEMO_DATA.items():
        content_parts.append(f"---\n### {data['platform_tag']}\n")
        content_parts.append(f"#### {data['title']}\n")

        if platform == "wechat":
            content_parts.append(data["content_md"][:600] + "\n\n*...(演示数据已截断)*\n")
        else:
            content_parts.append(f"**视频文稿：**\n{data['transcript'][:400]}\n\n*...(演示数据已截断)*\n")

        if enable_llm:
            summary_parts.append(f"---\n{data['summary']}\n")
        else:
            summary_parts.append(f"---\n*（AI 总结未启用，勾选「启用 AI 总结」查看）*\n")

        if platform == "wechat":
            download_parts.append(f"📄 微信公众号 → 保存为 `.md` 文件")
        else:
            download_parts.append(f"🎬 {platform} → 提取字幕/转写音频 → AI 总结")

    content_text = "\n".join(content_parts)
    summary_text = "\n".join(summary_parts) if enable_llm else "### 🤖 演示模式\n\n勾选「启用 AI 总结」复选框查看模拟的 AI 总结效果。"
    download_info = "\n".join(download_parts)

    return status, title, platform_tag, content_text, summary_text, download_info


def process_url(url: str, enable_llm: bool = True) -> tuple:
    """
    处理用户输入的链接

    Returns:
        (status, title, platform_tag, content_text, summary_text, download_info)
    """
    url = url.strip()
    if not url:
        return "⚠️ 请输入链接", "", "", "", "", ""

    # 演示模式
    if url.lower() == "demo" or url.lower() == "演示":
        return _run_demo(enable_llm)

    # 检测平台
    platform = detect_platform(url)
    if platform == "unknown":
        return (
            "❌ 不支持的链接类型",
            "",
            "",
            "请检查链接是否完整，支持的链接：\n"
            "- B站视频: https://www.bilibili.com/video/BV...\n"
            "- 小红书视频: https://www.xiaohongshu.com/discovery/item/...\n"
            "- 微信公众号文章: https://mp.weixin.qq.com/s/...\n"
            "- 任意博客文章: https://...",
            "",
            "",
        )

    platform_names = {
        "bilibili": "📺 B站视频",
        "xiaohongshu": "📕 小红书视频",
        "wechat": "📰 微信公众号",
        "blog": "📄 博客文章",
    }
    platform_tags = {
        "bilibili": '<span class="platform-tag tag-bilibili">B站</span>',
        "xiaohongshu": '<span class="platform-tag tag-xiaohongshu">小红书</span>',
        "wechat": '<span class="platform-tag tag-wechat">微信公众号</span>',
        "blog": '<span class="platform-tag tag-wechat">📄 文章</span>',
    }

    platform_name = platform_names.get(platform, platform)
    platform_tag = platform_tags.get(platform, platform)

    try:
        # 1. 爬取内容
        crawler = get_crawler(url)
        result = crawler.process(url)

        if not result.success:
            error_msg = result.error or "未知错误"
            return f"❌ 处理失败", result.title or "", platform_tag, f"错误: {error_msg}", "", ""

        # 2. 处理视频/文章
        if isinstance(result, VideoResult):
            return _handle_video_result(result, platform_tag, enable_llm)
        elif isinstance(result, ArticleResult):
            return _handle_article_result(result, platform_tag, enable_llm)
        else:
            return f"❌ 未知结果类型", "", platform_tag, "", "", ""

    except ValueError as e:
        return f"❌ {str(e)}", "", platform_tag, f"错误: {str(e)}", "", ""
    except Exception as e:
        return f"❌ 系统异常", "", platform_tag, f"处理异常: {str(e)}", "", ""


def _format_progress(step: str, detail: str = "", content: str = "", summary: str = "", download: str = "") -> tuple:
    """格式化进度输出"""
    status = f"⏳ {step}"
    if detail:
        status += f"\n> {detail}"
    return status, "", "", content, summary, download


def process_url_streaming(url: str, enable_llm: bool = True):
    """流式处理链接，每步都 yield 进度到 UI + 输出控制台日志"""
    url = url.strip()
    if not url:
        yield _format_progress("请输入链接")
        return

    # 演示模式
    if url.lower() == "demo" or url.lower() == "演示":
        yield _run_demo(enable_llm)
        return

    logger.step_begin(f"处理链接: {url[:80]}...")
    platform = detect_platform(url)
    if platform == "unknown":
        logger.error(f"不支持的链接类型: {url[:60]}")
        yield ("❌ 不支持的链接类型", "", "",
               "请检查链接是否完整，支持的链接：\n- B站视频\n- 小红书视频\n- 微信公众号文章\n- 任意博客文章", "", "")
        return

    platform_names = {"bilibili": "📺 B站视频", "xiaohongshu": "📕 小红书视频", "wechat": "📰 微信公众号", "blog": "📄 博客文章"}
    platform_tags = {
        "bilibili": '<span class="platform-tag tag-bilibili">B站</span>',
        "xiaohongshu": '<span class="platform-tag tag-xiaohongshu">小红书</span>',
        "wechat": '<span class="platform-tag tag-wechat">微信公众号</span>',
        "blog": '<span class="platform-tag tag-wechat">📄 文章</span>',
    }
    platform_tag = platform_tags.get(platform, platform)
    platform_name = platform_names.get(platform, platform)
    logger.info(f"平台: {platform_name}")

    def _status(msg):
        """生成包含最近步骤的状态列表"""
        return f"⏳ {msg}"

    try:
        # Step 1: 爬取
        yield _status(f"🔗 {platform_name} — 连接中..."), "", platform_tag, "", "", ""
        crawler = get_crawler(url)

        yield _status(f"🔗 {platform_name} — 获取内容..."), "", platform_tag, "", "", ""
        result = crawler.process(url)

        if not result.success:
            error_msg = result.error or "未知错误"
            logger.error(f"获取失败: {error_msg}")
            yield (f"❌ 处理失败", result.title or "", platform_tag, f"错误: {error_msg}", "", "")
            return

        logger.info(f"标题: {result.title}")

        if isinstance(result, VideoResult):
            # === 视频处理 ===
            transcript_text = result.subtitle_text

            if result.audio_path and not transcript_text:
                size_mb = os.path.getsize(result.audio_path) / 1024 / 1024
                logger.info(f"音频: {size_mb:.1f}MB, 开始语音转文字")
                yield _status(f"🎤 {platform_name} — 语音转文字中 (Whisper)..."), "", platform_tag, "", "", ""

                try:
                    transcript_text = transcriber.transcribe(result.audio_path)
                    if transcript_text and not transcript_text.startswith("音频文件") and not transcript_text.startswith("语音转写"):
                        result.transcript_text = transcript_text
                        logger.info(f"转写完成: {len(transcript_text)} 字符")
                        # 显示转写预览
                        preview = transcript_text[:2000] + ("..." if len(transcript_text) > 2000 else "")
                        yield _status(f"📝 {platform_name} — 转写完成 ({len(transcript_text)}字)"), "", platform_tag, \
                            f"### {result.title}\n\n{preview}", "", ""
                    else:
                        logger.warn(f"转写返回异常: {transcript_text[:100]}")
                except Exception as e:
                    logger.error(f"转写异常: {e}")

            # AI 总结
            summary = ""
            if enable_llm and transcript_text:
                logger.step_begin("LLM总结")
                yield _status(f"🤖 {platform_name} — AI 总结中..."), "", platform_tag, "", "", ""
                summary = summarizer.summarize_video(
                    title=result.title,
                    description=result.description or "",
                    transcript=transcript_text,
                )
                logger.step_end()

            # 生成完整报告（截图 + 转写 + 总结）
            report_path = ""
            video_src = result.video_url or result.video_path
            if transcript_text:
                logger.step_begin("生成视频报告")
                has_video = bool(video_src)
                msg = "生成报告中（截图+转写+总结）..." if has_video else "生成报告中（无视频源，跳过截图）..."
                yield _status(f"📋 {platform_name} — {msg}"), "", platform_tag, "", "", ""
                try:
                    import subprocess
                    dur_proc = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", video_src if has_video else result.audio_path],
                        capture_output=True, text=True, timeout=10,
                    )
                    duration = float(dur_proc.stdout.strip()) if dur_proc.stdout.strip() else 60.0
                except Exception:
                    duration = 60.0

                report_path = generate_video_report(
                    video_src=video_src or "",
                    title=result.title,
                    platform=platform,
                    duration=duration,
                    transcript_text=transcript_text,
                    summary_text=summary,
                    segment_seconds=15,
                )
                logger.step_end()

            logger.success("处理完成")

            # 构建完整内容展示
            full_content = f"### {result.title}\n\n{transcript_text}" if transcript_text else ""
            download_info = ""
            if result.video_path:
                download_info = f"🎬 视频: `{result.video_path}`"
            if result.audio_path:
                download_info += f"\n🎵 音频: `{result.audio_path}`" if download_info else f"🎵 音频: `{result.audio_path}`"
            if result.transcript_text:
                txt_name = os.path.splitext(os.path.basename(result.audio_path))[0] + "_transcript.txt"
                download_info += f"\n📝 转写: `{OUTPUT_DIR}/{txt_name}`" if download_info else f"📝 转写: `{OUTPUT_DIR}/{txt_name}`"
            if report_path:
                download_info += f"\n📋 报告: `{report_path}`" if download_info else f"📋 报告: `{report_path}`"

            yield f"✅ {platform_name} 处理完成", result.title, platform_tag, full_content, summary, download_info
            return

        elif isinstance(result, ArticleResult):
            # === 文章处理 ===
            logger.info(f"文章: {len(result.content_markdown)} 字符")
            yield _status(f"📄 {platform_name} — 已获取文章 ({len(result.content_markdown)}字)"), "", platform_tag, \
                f"### {result.title}\n\n{result.content_markdown[:1500]}...", "", \
                f"📄 Markdown: `{result.markdown_path}`"

            if enable_llm and result.content_markdown:
                logger.step_begin("LLM总结文章")
                yield _status(f"🤖 {platform_name} — AI 总结中..."), "", platform_tag, "", "", ""
                summary = summarizer.summarize_article(
                    title=result.title,
                    author=result.author,
                    content=result.content_markdown,
                )
                logger.step_end()
                logger.success("处理完成")
                full_md = f"### {result.title}\n\n{result.content_markdown}"
                yield f"✅ {platform_name} 处理完成", result.title, platform_tag, full_md, summary, \
                    f"📄 Markdown: `{result.markdown_path}`"
                return

            full_md = f"### {result.title}\n\n{result.content_markdown}" if result.content_markdown else ""
            yield f"✅ {platform_name} 处理完成", result.title, platform_tag, full_md, "", \
                f"📄 Markdown: `{result.markdown_path}`"

    except ValueError as e:
        logger.error(f"不支持的链接: {e}")
        yield (f"❌ {e}", "", "", f"错误: {e}", "", "")
    except Exception as e:
        logger.error(f"系统异常: {e}")
        yield (f"❌ 系统异常", "", "", f"异常: {e}", "", "")


def _handle_video_result(result: VideoResult, platform_tag: str, enable_llm: bool) -> tuple:
    """处理视频结果"""
    status = "✅ 视频信息获取成功"
    title = result.title
    content_parts = []

    # 基本信息
    content_parts.append(f"### 📹 {result.title}\n")
    if result.description:
        content_parts.append(f"**简介：** {result.description}\n")

    # 字幕/转写文本
    transcript = result.subtitle_text or result.transcript_text
    if transcript:
        content_parts.append("---\n")
        content_parts.append("### 📝 视频文稿\n")
        content_parts.append(transcript)
    elif result.audio_path:
        content_parts.append("---\n")
        content_parts.append("### 🎤 正在转写音频...\n")
        transcript_text = transcriber.transcribe(result.audio_path)
        if transcript_text and not transcript_text.startswith("音频文件不存在") and not transcript_text.startswith("语音转写失败"):
            result.transcript_text = transcript_text
            content_parts.append(transcript_text)
        else:
            content_parts.append(f"*音频转写失败或暂无字幕: {transcript_text}*")

    content_text = "\n".join(content_parts)

    # LLM 总结
    summary_text = ""
    if enable_llm:
        final_transcript = result.subtitle_text or result.transcript_text
        if final_transcript:
            summary_text = summarizer.summarize_video(
                title=result.title,
                description=result.description,
                transcript=final_transcript,
            )
        else:
            summary_text = "⚠️ 没有可用的视频文稿，无法生成总结"

    # 下载信息
    download_info_parts = []
    if result.video_path:
        download_info_parts.append(f"📥 视频: `{result.video_path}`")
    if result.audio_path:
        download_info_parts.append(f"🎵 音频: `{result.audio_path}`")
    download_info = "\n".join(download_info_parts) if download_info_parts else ""

    return status, title, platform_tag, content_text, summary_text, download_info


def _handle_article_result(result: ArticleResult, platform_tag: str, enable_llm: bool) -> tuple:
    """处理文章结果"""
    status = "✅ 文章获取成功"
    title = result.title

    info_parts = []
    if result.author:
        info_parts.append(f"**作者：** {result.author}")
    if result.publish_time:
        info_parts.append(f"**发布时间：** {result.publish_time}")
    info_line = " | ".join(info_parts) if info_parts else ""

    content_parts = []
    content_parts.append(f"### 📄 {result.title}\n")
    if info_line:
        content_parts.append(f"{info_line}\n")
    content_parts.append("---\n")

    if result.markdown_path:
        content_parts.append(f"📥 已保存为: `{result.markdown_path}`\n")
        content_parts.append("---\n")

    # 正文
    if result.content_markdown:
        content_parts.append(result.content_markdown)

    content_text = "\n".join(content_parts)

    # LLM 总结
    summary_text = ""
    if enable_llm:
        summary_text = summarizer.summarize_article(
            title=result.title,
            author=result.author,
            content=result.content_markdown,
        )

    # 下载信息
    download_info = f"📥 文章文件: `{result.markdown_path}`" if result.markdown_path else ""

    return status, title, platform_tag, content_text, summary_text, download_info


# --- 构建 Gradio 界面 ---
def create_ui():
    with gr.Blocks(title="VideoCraw") as app:

        # Header
        gr.Markdown("# VideoCraw")
        gr.HTML(_diag_html)

        # Input row
        url_input = gr.Textbox(
            label="链接",
            placeholder="粘贴链接 (B站/小红书/微信/任意博客)...",
        )
        with gr.Row():
            enable_llm = gr.Checkbox(label="AI 总结", value=True)
            demo_btn = gr.Button("演示", variant="secondary")
            submit_btn = gr.Button("开始", variant="primary")

        # Status
        status_output = gr.Markdown("")
        download_output = gr.Markdown("")

        # Results
        platform_output = gr.HTML("")
        title_output = gr.Markdown("")

        with gr.Tabs():
            with gr.TabItem("内容"):
                content_output = gr.Markdown("", elem_classes=["result-box"])
            with gr.TabItem("总结"):
                summary_output = gr.Markdown("", elem_classes=["summary-box"])

        # Events
        def on_submit(url, do_summary):
            for progress in process_url_streaming(url, do_summary):
                status, title, tag, content, summary, download = progress
                yield status, tag, f"### {title}" if title else "", content, summary, download

        def on_demo(do_summary):
            return process_url("demo", do_summary)

        outputs = [status_output, platform_output, title_output, content_output, summary_output, download_output]

        submit_btn.click(fn=on_submit, inputs=[url_input, enable_llm], outputs=outputs)
        demo_btn.click(fn=on_demo, inputs=[enable_llm], outputs=outputs)
        url_input.submit(fn=on_submit, inputs=[url_input, enable_llm], outputs=outputs)

    return app


# --- 入口 ---
if __name__ == "__main__":
    app = create_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        css=CUSTOM_CSS,
        theme=gr.themes.Soft(),
    )
