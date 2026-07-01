"""
全局配置 - 从环境变量或 .env 文件加载
"""
import os
import shutil
from dotenv import load_dotenv

load_dotenv()


def _find_ffmpeg() -> str:
    """查找 ffmpeg 可执行文件路径"""
    # 使用 shutil.which 查找完整路径
    path = shutil.which("ffmpeg")
    if path:
        return path
    # 常见路径 fallback
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return "ffmpeg"


FFMPEG_PATH = os.getenv("FFMPEG_PATH", _find_ffmpeg())

# --- LLM 配置 ---
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# --- Whisper 配置 ---
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")  # tiny, base, small, medium, large-v3
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")   # cpu / cuda
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8 / float16

# --- 讯飞语音听写配置 ---
XF_IAT_APP_ID = os.getenv("XF_IAT_APP_ID", "")
XF_IAT_API_KEY = os.getenv("XF_IAT_API_KEY", "")
XF_IAT_API_SECRET = os.getenv("XF_IAT_API_SECRET", "")
XF_IAT_FAST = os.getenv("XF_IAT_FAST", "true").lower() == "true"  # 快发模式，默认开
XF_IAT_SEGMENT_SECONDS = int(os.getenv("XF_IAT_SEGMENT_SECONDS", "15") or "0")  # 时间戳分段秒数
# 语音转文字引擎: "xfyun" (讯飞，推荐) 或 "whisper" (本地)
ASR_ENGINE = os.getenv("ASR_ENGINE", "whisper")

# --- 代理配置 ---
HTTP_PROXY = os.getenv("HTTP_PROXY", "") or os.getenv("http_proxy", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "") or os.getenv("https_proxy", "")

# --- 下载目录 ---
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", os.path.join(os.path.dirname(__file__), "downloads"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "output"))

# --- 小红书 Cookie (可选，提升下载成功率) ---
XHS_COOKIE = os.getenv("XHS_COOKIE", "")

# --- B站配置 ---
# 从浏览器读取 Cookie（无需登录，打开过 bilibili.com 即可）
BILI_COOKIES_BROWSER = os.getenv("BILI_COOKIES_BROWSER", "chrome")
# 手动 Cookie（可选，优先级高于浏览器读取）
BILI_SESSDATA = os.getenv("BILI_SESSDATA", "")
BILI_BILI_JCT = os.getenv("BILI_BILI_JCT", "")
BILI_BUVID3 = os.getenv("BILI_BUVID3", "")

# 确保目录存在
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
