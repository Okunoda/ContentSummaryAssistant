"""小红书视频爬取器

方案：
1. 解析小红书分享链接，获取笔记详情
2. 提取视频URL并下载
3. 提取文案/描述
4. 转写视频音频为文字
"""
import os
import re
import json
import subprocess
import requests
from crawlers.base import BaseCrawler, VideoResult
from config import DOWNLOAD_DIR, XHS_COOKIE, FFMPEG_PATH
from utils.helpers import extract_xiaohongshu_note_id, sanitize_filename
from utils.progress import logger


class XiaohongshuCrawler(BaseCrawler):
    """小红书视频爬取器"""

    def __init__(self):
        super().__init__()
        self.platform = "xiaohongshu"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
        }
        if XHS_COOKIE:
            self.headers['Cookie'] = XHS_COOKIE

        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def process(self, url: str) -> VideoResult:
        result = VideoResult(platform="xiaohongshu")

        try:
            # 1. 解析短链接（如果有）
            if 'xhslink.com' in url:
                url = self._resolve_short_link(url)
                if not url:
                    result.error = "无法解析小红书短链接"
                    return result

            # 2. 提取笔记ID
            note_id = extract_xiaohongshu_note_id(url)
            if not note_id:
                result.error = "无法从小红书链接中提取笔记ID"
                return result

            # 3. 获取笔记详情（传入完整URL以保留 xsec_token 等关键参数）
            note_data = self._fetch_note_data(note_id, source_url=url)
            if not note_data:
                result.error = "无法获取小红书笔记数据（可能需要 Cookie 或笔记不存在）"
                return result

            # 4. 提取基本信息
            result.title = note_data.get("title", "无标题")
            result.description = note_data.get("desc", "")

            # 5. 判断是否为视频
            note_type = note_data.get("type", "")
            if note_type != "video":
                result.error = f"该笔记不是视频类型（类型: {note_type}），请确认链接是视频"
                return result

            # 6. 下载视频
            video_url = self._extract_video_url(note_data)
            if video_url:
                result.video_url = video_url  # 保留流地址，用于在线截图
                result.video_path = self._download_video(video_url, result.title)
                if result.video_path:
                    # 提取音频用于转写
                    result.audio_path = self._extract_audio(result.video_path)
                    result.success = True
                else:
                    result.error = "视频下载失败"
            else:
                result.error = "无法提取视频地址"

        except Exception as e:
            result.error = f"小红书处理异常: {str(e)}"

        return result

    def _resolve_short_link(self, short_url: str) -> str:
        """解析 xhslink.com 短链接"""
        try:
            resp = self.session.get(short_url, allow_redirects=False, timeout=15)
            # 检查重定向
            if resp.status_code in (301, 302):
                location = resp.headers.get('Location', '')
                if location:
                    return location
            # 可能返回JS重定向页面
            if resp.status_code == 200:
                # 从JS中提取重定向URL
                match = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', resp.text)
                if match:
                    return match.group(1)
                # 尝试从 noscript 中提取
                match = re.search(r'URL=([^"\']+)', resp.text)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"解析短链接失败: {e}")
        return ""

    def _fetch_note_data(self, note_id: str, source_url: str = ""):
        """获取小红书笔记数据

        Args:
            note_id: 笔记ID
            source_url: 来源URL（优先使用，保留 xsec_token 等关键参数）
        """
        try:
            # 优先使用来源URL（保留 xsec_token 等参数），否则构造 /explore/ URL
            if source_url and 'xiaohongshu.com' in source_url:
                api_url = source_url
            else:
                api_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            resp = self.session.get(api_url, timeout=15)

            if resp.status_code != 200:
                return None

            # 从页面中提取 __INITIAL_STATE__ 数据
            match = re.search(
                r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>',
                resp.text, re.DOTALL
            )

            if not match:
                # 尝试另一种提取方式
                match = re.search(
                    r'<script>window\.__INITIAL_STATE__\s*=\s*({.*?})</script>',
                    resp.text, re.DOTALL
                )

            if match:
                raw_json = match.group(1)
                # 处理未转义的 undefined
                raw_json = raw_json.replace('undefined', 'null')
                data = json.loads(raw_json)

                # 提取笔记数据
                note_data = data.get("note", {})
                if note_data:
                    note_detail = note_data.get("noteDetailMap", {}).get(note_id, {})
                    note = note_detail.get("note", {})
                    if note:
                        return {
                            "title": note.get("title", ""),
                            "desc": note.get("desc", ""),
                            "type": note.get("type", ""),
                            "video": note.get("video", {}),
                            "imageList": note.get("imageList", []),
                        }

            return None
        except json.JSONDecodeError as e:
            print(f"JSON解析失败: {e}")
            return None
        except Exception as e:
            print(f"获取笔记数据失败: {e}")
            return None

    def _extract_video_url(self, note_data: dict) -> str:
        """从笔记数据中提取视频URL"""
        video_info = note_data.get("video", {})
        if not video_info:
            return ""

        # 优先级：高清 > 标清
        media = video_info.get("media", {})
        stream = media.get("stream", {})

        # 尝试不同清晰度
        for quality in ["h264", "h265", "h266"]:
            for level in ["1080p", "720p", "480p", "360p"]:
                streams = stream.get(quality, [])
                if isinstance(streams, list):
                    for s in streams:
                        if isinstance(s, dict):
                            url = s.get("masterUrl", "")
                            if url:
                                return url

        # 降级：使用 videoUrl
        video_url = video_info.get("videoUrl", "")
        if not video_url:
            video_url = media.get("videoUrl", "")

        return video_url

    def _download_video(self, video_url: str, title: str) -> str:
        """下载视频文件"""
        try:
            safe_title = sanitize_filename(title) if title else "xiaohongshu_video"
            ext = "mp4"
            filepath = os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")

            # 如果已下载则跳过
            if os.path.exists(filepath):
                return filepath

            resp = self.session.get(video_url, stream=True, timeout=120)
            if resp.status_code == 200:
                total = int(resp.headers.get('content-length', 0))
                downloaded = 0
                last_pct = -1
                with open(filepath, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = downloaded * 100 // total
                                if pct != last_pct and pct % 20 == 0:
                                    last_pct = pct
                                    logger.detail(f"视频下载: {pct}% ({downloaded/1024/1024:.1f}/{total/1024/1024:.1f}MB)")

                if downloaded > 0:
                    logger.detail(f"视频下载完成: {downloaded/1024/1024:.1f}MB")
                    return filepath

            return ""
        except Exception as e:
            print(f"下载视频失败: {e}")
            return ""

    def _extract_audio(self, video_path: str) -> str:
        """从视频中提取音频"""
        try:
            audio_path = video_path.rsplit('.', 1)[0] + '.mp3'
            if os.path.exists(audio_path):
                return audio_path

            cmd = [
                FFMPEG_PATH, "-i", video_path,
                "-vn", "-acodec", "libmp3lame",
                "-q:a", "2",
                audio_path, "-y"
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                print(f"ffmpeg 提取音频失败: {proc.stderr[:200]}")
                return ""
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                return audio_path
            return ""
        except Exception as e:
            print(f"提取音频失败: {e}")
            return ""
