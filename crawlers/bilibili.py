"""B站视频爬取器

方案：
1. 使用 bilibili-api-python 获取视频信息和字幕（CC字幕）
2. 若有字幕，直接使用字幕文本
3. 若无字幕，使用 yt-dlp 下载音频，再用 Whisper 转写

注意：B站对海外IP有地域限制，可能需要中国大陆代理
"""
import os
import re
import json
import subprocess
import requests as req
from crawlers.base import BaseCrawler, VideoResult
from config import DOWNLOAD_DIR, FFMPEG_PATH, BILI_SESSDATA, BILI_BILI_JCT, BILI_BUVID3, BILI_COOKIES_BROWSER, HTTP_PROXY
from utils.helpers import extract_bilibili_bvid, sanitize_filename
from utils.progress import logger


class BilibiliCrawler(BaseCrawler):
    """B站视频爬取器"""

    def __init__(self):
        super().__init__()
        self.platform = "bilibili"
        self.errors: list[str] = []  # 收集所有错误信息

    def _run_ytdlp_with_progress(self, cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
        """运行 yt-dlp 并实时打印下载进度

        yt-dlp 输出格式: [download]  12.3% of ~20MiB ...
        Returns: (returncode, stdout, stderr)
        """
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1)
        all_lines = []
        last_pct = -1

        try:
            for line in proc.stdout:
                all_lines.append(line)
                line = line.strip()
                if not line:
                    continue
                pct_match = re.search(r'([\d.]+)%', line)
                if pct_match and '[download]' in line:
                    pct = int(float(pct_match.group(1)))
                    if pct != last_pct and pct % 10 == 0:
                        last_pct = pct
                        logger.detail(f"下载进度: {pct}%")
                elif '[download]' in line and 'already been downloaded' in line:
                    logger.detail("文件已缓存，跳过下载")

            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            return (-1, "", "下载超时")
        except Exception:
            proc.kill()
            return (-1, "", "下载异常")

        return (proc.returncode, ''.join(all_lines), "")

    def _get_credential(self):
        """创建 B站 Credential（如果有 Cookie 则使用）"""
        if BILI_SESSDATA:
            from bilibili_api import Credential
            return Credential(
                sessdata=BILI_SESSDATA,
                bili_jct=BILI_BILI_JCT,
                buvid3=BILI_BUVID3,
            )
        return None

    def _build_ytdlp_cmd(self, *extra_args: str) -> list[str]:
        """构建 yt-dlp 命令（自动添加代理、Cookie、ffmpeg 参数）"""
        cmd = ["yt-dlp"]
        # 浏览器 Cookie（绕过 B站 HTTP 412）
        if BILI_COOKIES_BROWSER:
            cmd.extend(["--cookies-from-browser", BILI_COOKIES_BROWSER])
        if HTTP_PROXY:
            cmd.extend(["--proxy", HTTP_PROXY])
        if FFMPEG_PATH and FFMPEG_PATH != "ffmpeg":
            cmd.extend(["--ffmpeg-location", FFMPEG_PATH])
        cmd.extend(extra_args)
        return cmd

    def process(self, url: str) -> VideoResult:
        result = VideoResult(platform="bilibili")
        self.errors = []

        try:
            logger.step_begin("解析B站链接")
            # 1. 处理短链接 (b23.tv)
            if 'b23.tv' in url:
                logger.detail("检测到 b23.tv 短链接，正在解析...")
                resolved = self._resolve_short_link(url)
                if resolved:
                    url = resolved
                    logger.detail(f"短链接已解析: {url[:60]}...")
                else:
                    logger.error("短链接解析失败")
                    result.error = "无法解析 b23.tv 短链接，请提供完整的 B站视频链接 (https://www.bilibili.com/video/BV...)"
                    return result

            # 2. 提取 BV 号
            bvid = extract_bilibili_bvid(url)
            if not bvid:
                logger.error("无法提取BV号")
                result.error = "无法从链接中提取 BV 号，请提供完整的 B站视频链接"
                return result
            logger.detail(f"BV号: {bvid}")
            logger.step_end()

            # 3. 获取视频信息
            logger.step_begin("获取B站视频信息")
            result = self._fetch_video_info(bvid, result)
            if not result.title:
                error_detail = "; ".join(self.errors) if self.errors else "未知原因"
                logger.error(f"获取视频信息失败: {error_detail}")
                result.error = f"无法获取视频信息。可能原因：\n1. B站地域限制\n2. 视频已删除或不存在\n详细信息: {error_detail}"
                return result
            logger.detail(f"标题: {result.title}")
            logger.detail(f"时长: {result.description[:50] if result.description else '无描述'}...")
            logger.step_end()

            # 4. 下载音频（bilibili-api 直接获取下载链接）
            logger.step_begin("下载B站音频")
            audio_path = self._download_audio_via_api(bvid, result.title)
            if audio_path:
                result.audio_path = audio_path
                result.success = True
                logger.step_end()
            else:
                # 降级: yt-dlp
                logger.warn("bilibili-api 下载失败，降级到 yt-dlp...")
                audio_path = self._download_audio_ytdlp(url, result.title)
                if audio_path:
                    result.audio_path = audio_path
                    result.success = True
                    logger.step_end()
                else:
                    logger.error("两种下载方式均失败")
                    if not self.errors:
                        self.errors.append("音频下载失败")
                    logger.step_end("失败")

            # 5. 下载视频（用于截图）
            if result.audio_path and not result.video_path:
                logger.step_begin("下载B站视频（用于截图）")
                video_path = self._download_video_ytdlp(url, result.title)
                if video_path:
                    result.video_path = video_path
                    logger.detail(f"视频: {os.path.basename(video_path)}")
                else:
                    logger.warn("视频下载失败，报告将不含截图")
                logger.step_end()

            if self.errors:
                result.error = "; ".join(self.errors)

        except Exception as e:
            logger.error(f"B站处理异常: {e}")
            result.error = f"B站处理异常: {str(e)}"

        return result

    def _resolve_short_link(self, short_url: str) -> str:
        """解析 b23.tv 短链接"""
        try:
            resp = req.get(short_url, allow_redirects=True, timeout=15,
                           headers={'User-Agent': 'Mozilla/5.0'})
            final_url = resp.url
            if 'bilibili.com/video/' in final_url:
                return final_url
        except Exception as e:
            self.errors.append(f"短链接解析失败: {e}")
        return ""

    def _fetch_video_info(self, bvid: str, result: VideoResult) -> VideoResult:
        """使用 bilibili-api 获取视频信息，失败则降级到 yt-dlp"""
        # 方案A: bilibili-api-python
        try:
            from bilibili_api import video, sync
            credential = self._get_credential()
            v = video.Video(bvid=bvid, credential=credential)
            info = sync(v.get_info())

            code = info.get("code", 0)
            if code != 0:
                msg = info.get("message", "未知错误")
                self.errors.append(f"B站API返回错误 ({code}): {msg}")
                if code == 62002:
                    self.errors.append("提示: 该视频可能不可见/已删除/仅限中国大陆访问")
                # 降级到 yt-dlp
                return self._fetch_video_info_ytdlp(bvid, result)

            result.title = info.get("title", "")
            result.description = info.get("desc", "")
            return result

        except ImportError:
            self.errors.append("bilibili-api-python 未安装，使用 yt-dlp 降级")
            return self._fetch_video_info_ytdlp(bvid, result)
        except Exception as e:
            self.errors.append(f"bilibili-api 异常: {e}")
            return self._fetch_video_info_ytdlp(bvid, result)

    def _fetch_video_info_ytdlp(self, bvid: str, result: VideoResult) -> VideoResult:
        """使用 yt-dlp 获取视频信息（降级方案）"""
        try:
            url = f"https://www.bilibili.com/video/{bvid}"
            cmd = self._build_ytdlp_cmd("--dump-json", "--no-download", url)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if proc.returncode != 0 or not proc.stdout.strip():
                stderr = proc.stderr.strip()
                self.errors.append(f"yt-dlp 失败: {stderr[:200]}")

                # 检查是否为地域限制
                if "412" in stderr or "Precondition Failed" in stderr:
                    self.errors.append(
                        "提示: B站返回 HTTP 412，这通常是地域限制。"
                        "请使用中国大陆代理，或配置环境变量 HTTP_PROXY/https_proxy"
                    )
                return result

            info = json.loads(proc.stdout)
            result.title = info.get("title", "")
            result.description = info.get("description", "")
            return result

        except json.JSONDecodeError:
            self.errors.append("yt-dlp 返回了无效的 JSON")
            return result
        except Exception as e:
            self.errors.append(f"yt-dlp 异常: {e}")
            return result

    def _fetch_subtitles(self, bvid: str) -> str:
        """获取B站 CC字幕（需 cid，新API需要登录凭证）"""
        # 方案A: bilibili-api (需要 sessdata)
        try:
            from bilibili_api import video, sync

            credential = self._get_credential()
            v = video.Video(bvid=bvid, credential=credential)
            info = sync(v.get_info())
            cid = info.get("cid", 0)

            if not cid and info.get("pages"):
                cid = info["pages"][0].get("cid", 0)

            if not cid:
                return self._fetch_subtitles_ytdlp(bvid)

            # 新API (v17+): get_subtitle(cid=...)
            subtitle_data = sync(v.get_subtitle(cid=cid))

            subtitles = subtitle_data.get("subtitles", []) if subtitle_data else []
            if not subtitles:
                return self._fetch_subtitles_ytdlp(bvid)

            # 优先选中文
            selected = None
            for sub in subtitles:
                lan = sub.get("lan_doc", "").lower()
                if "zh" in lan or "中文" in lan:
                    selected = sub
                    break
            if not selected:
                selected = subtitles[0]

            subtitle_url = selected.get("subtitle_url", "")
            if not subtitle_url:
                return ""

            if subtitle_url.startswith("http:"):
                subtitle_url = "https:" + subtitle_url[5:]

            resp = req.get(subtitle_url, timeout=30)
            if resp.status_code != 200:
                return ""

            body = resp.json().get("body", [])
            lines = [item["content"] for item in body if item.get("content")]
            return "\n".join(lines)

        except ImportError:
            return self._fetch_subtitles_ytdlp(bvid)
        except Exception as e:
            err_msg = str(e)
            if "Credential" in err_msg or "sessdata" in err_msg:
                self.errors.append("B站字幕需要登录凭证，使用 yt-dlp 降级获取")
            else:
                self.errors.append(f"bilibili-api 字幕异常: {e}")
            return self._fetch_subtitles_ytdlp(bvid)

    def _fetch_subtitles_ytdlp(self, bvid: str) -> str:
        """使用 yt-dlp 获取字幕（降级方案）"""
        try:
            url = f"https://www.bilibili.com/video/{bvid}"
            sub_dir = os.path.join(DOWNLOAD_DIR, "subtitles")
            os.makedirs(sub_dir, exist_ok=True)

            cmd = self._build_ytdlp_cmd(
                "--write-subs", "--write-auto-subs",
                "--sub-lang", "zh-Hans,zh,en",
                "--skip-download",
                "--sub-format", "vtt",
                "-o", os.path.join(sub_dir, "%(id)s.%(ext)s"),
                url,
            )
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            for f in os.listdir(sub_dir):
                if f.endswith('.vtt'):
                    filepath = os.path.join(sub_dir, f)
                    return self._parse_vtt(filepath)
        except Exception:
            pass
        return ""

    def _parse_vtt(self, filepath: str) -> str:
        """解析 VTT 字幕文件为纯文本"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            lines = []
            for line in content.split('\n'):
                line = line.strip()
                if not line or line == 'WEBVTT' or line.isdigit():
                    continue
                if '-->' in line or line.startswith('NOTE') or line.startswith('STYLE'):
                    continue
                line = re.sub(r'<[^>]+>', '', line)
                if line:
                    lines.append(line)

            # 去重相邻行
            deduped = []
            for line in lines:
                if not deduped or line != deduped[-1]:
                    deduped.append(line)
            return '\n'.join(deduped)
        except Exception as e:
            self.errors.append(f"VTT解析失败: {e}")
            return ""

    def _download_audio_via_api(self, bvid: str, title: str) -> str:
        """使用 bilibili-api 获取下载链接，requests 下载音频"""
        try:
            from bilibili_api import video, sync

            logger.detail("通过 bilibili-api 获取下载链接...")
            credential = self._get_credential()
            if credential:
                logger.detail("使用 B站 Cookie 认证")
            v = video.Video(bvid=bvid, credential=credential)
            info = sync(v.get_info())
            cid = info.get("cid", 0)
            if not cid and info.get("pages"):
                cid = info["pages"][0].get("cid", 0)
            if not cid:
                self.errors.append("无法获取视频 cid")
                logger.error("无法获取 cid")
                return ""
            logger.detail(f"cid: {cid}")

            # 获取下载链接
            download_data = sync(v.get_download_url(cid=cid))
            if not download_data or "dash" not in download_data:
                self.errors.append("bilibili-api 返回的下载数据中没有 DASH 流")
                logger.error("下载数据中没有 DASH 流")
                return ""

            dash = download_data["dash"]
            audio_streams = dash.get("audio", [])
            if not audio_streams:
                self.errors.append("没有可用的音频流")
                logger.error("没有音频流")
                return ""
            logger.detail(f"找到 {len(audio_streams)} 个音频流")

            # 选最高质量音频
            best_audio = max(audio_streams, key=lambda a: a.get("bandwidth", 0))
            audio_url = best_audio.get("base_url") or best_audio.get("baseUrl", "")
            if not audio_url:
                self.errors.append("音频URL为空")
                return ""

            # 下载音频
            safe_title = sanitize_filename(title) if title else "bilibili_audio"
            ext = best_audio.get("mimeType", "audio/mp4").split("/")[-1].split(";")[0]
            if ext == "mp4":
                ext = "m4a"
            audio_path = os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")

            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                logger.detail(f"音频已缓存: {os.path.basename(audio_path)}")
                return audio_path

            bitrate = best_audio.get("bandwidth", 0) // 1000
            logger.detail(f"开始下载: {bitrate}kbps, 格式: {ext}")

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
            }
            proxies = {}
            if HTTP_PROXY:
                proxies["http"] = HTTP_PROXY
                proxies["https"] = HTTP_PROXY
                logger.detail(f"使用代理: {HTTP_PROXY}")

            resp = req.get(audio_url, headers=headers, proxies=proxies, stream=True, timeout=120)
            if resp.status_code != 200:
                self.errors.append(f"下载音频失败: HTTP {resp.status_code}")
                logger.error(f"HTTP {resp.status_code}")
                return ""

            total = 0
            total_size = int(resp.headers.get("content-length", 0))
            last_log_pct = -1
            with open(audio_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
                        if total_size:
                            pct = total * 100 // total_size
                            if pct - last_log_pct >= 10:  # 每10%输出一次
                                logger.progress(pct, 100, f"下载音频 {pct}% ({total/1024/1024:.1f}MB)")
                                last_log_pct = pct

            size_mb = total / 1024 / 1024
            logger.detail(f"下载完成: {size_mb:.1f}MB -> {os.path.basename(audio_path)}")
            if total > 0:
                return audio_path
            else:
                os.remove(audio_path)
                return ""
        except Exception as e:
            self.errors.append(f"bilibili-api 音频下载异常: {e}")
            logger.error(f"下载异常: {e}")
            return ""

    def _download_audio_ytdlp(self, url: str, title: str) -> str:
        """使用 yt-dlp 下载视频音频（降级方案）"""
        try:
            safe_title = sanitize_filename(title) if title else "bilibili_audio"
            output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

            cmd = self._build_ytdlp_cmd(
                "-f", "bestaudio[ext=m4a]/bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--newline",
                "-o", output_template,
                "--no-playlist",
                url,
            )
            logger.detail("yt-dlp 下载音频...")
            code, stdout, stderr = self._run_ytdlp_with_progress(cmd, timeout=180)

            if code != 0:
                self.errors.append(f"音频下载失败: {stderr.strip()[:200]}")
                return ""

            # 查找生成的音频文件
            for ext in ['mp3', 'm4a', 'webm', 'opus', 'wav']:
                audio_path = os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                    return audio_path

            return ""
        except Exception as e:
            self.errors.append(f"音频下载异常: {e}")
            return ""

    def _download_video_ytdlp(self, url: str, title: str) -> str:
        """使用 yt-dlp 下载视频（用于截图，只下 720p 节省带宽）"""
        try:
            safe_title = sanitize_filename(title) if title else "bilibili_video"

            # 缓存检测
            for ext in ['mp4', 'webm', 'mkv', 'flv']:
                cached = os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")
                if os.path.exists(cached) and os.path.getsize(cached) > 0:
                    logger.detail(f"视频已缓存: {os.path.basename(cached)}")
                    return cached

            output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

            cmd = self._build_ytdlp_cmd(
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "--merge-output-format", "mp4",
                "--newline",  # 强制每行换行，否则进度条被管道缓冲
                "-o", output_template,
                "--no-playlist",
                url,
            )
            logger.detail(f"yt-dlp 下载视频 ({safe_title}.mp4)...")
            code, stdout, stderr = self._run_ytdlp_with_progress(cmd, timeout=300)

            if code != 0:
                self.errors.append(f"视频下载失败: {stderr.strip()[:200]}")
                return ""

            for ext in ['mp4', 'webm', 'mkv', 'flv']:
                video_path = os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")
                if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
                    return video_path

            return ""
        except Exception as e:
            self.errors.append(f"视频下载异常: {e}")
            return ""

    def _get_video_stream_url(self, url: str) -> str:
        """使用 yt-dlp -g 获取视频直链（不下载文件）"""
        try:
            cmd = self._build_ytdlp_cmd(
                "-f", "best[height<=720]/best",
                "-g",  # 只打印 URL，不下载
                "--no-playlist",
                url,
            )
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip().split('\n')[0]
            return ""
        except Exception:
            return ""
