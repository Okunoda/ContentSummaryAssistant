"""讯飞语音听写 (IAT) 集成模块

通过 WebSocket 流式接口将音频转为文字。
- 自动将音频转换为 PCM 16kHz 单声道格式
- 自动处理超过 60 秒的长音频（分段转写）
- 比本地 Whisper 准确率高，且不占用本地资源

接口文档: https://www.xfyun.cn/doc/asr/voicedictation/API.html
"""
import base64
import datetime
import difflib
import hashlib
import hmac
import json
import os
import re
import ssl
import subprocess
import tempfile
import threading
import time
from time import mktime
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

import websocket

from config import OUTPUT_DIR
from utils.progress import logger

# IAT WebSocket 地址（讯飞官方使用 ws://，不支持 wss://）
IAT_WS_URL = "ws://iat.xf-yun.com/v1"
# 单段最大时长（秒），留 5 秒余量确保不超 API 的 60 秒限制
MAX_CHUNK_SECONDS = 55
# 发送帧大小（字节）
FRAME_SIZE = 1280
# 发送间隔（秒），仅在 fast=False 时生效，模拟实时流
SEND_INTERVAL = 0.04
# 音频参数
SAMPLE_RATE = 16000
# 重叠秒数：相邻段之间重叠 X 秒，消除边界截断
OVERLAP_SECONDS = 3


def _format_timestamp(start: float, end: float, text: str) -> str:
    """格式化时间戳行: [MM:SS - MM:SS] 文字"""
    def _fmt(sec):
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    return f"[{_fmt(start)} - {_fmt(end)}]\n{text}"


class XfyunASR:
    """讯飞语音听写 - 流式 WebSocket API"""

    def __init__(self, app_id: str = "", api_key: str = "", api_secret: str = "",
                 fast: bool = True, segment_seconds: int = 0):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        # 快发模式：发送不等待，离线文件秒级处理；关闭则模拟实时流
        self.fast = fast
        # 时间戳分段：>0 则每 N 秒一段，输出带 [MM:SS - MM:SS] 标记
        self.segment_seconds = segment_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.app_id and self.api_key and self.api_secret)

    def transcribe(self, audio_path: str, language: str = "zh",
                   segment_seconds=None) -> str:
        """将音频文件转写为文字

        自动处理：
        - 格式转换（→ PCM 16kHz mono）
        - 长音频分段（>55s 自动切分）
        - 可选时间戳分段（segment_seconds > 0）

        Args:
            audio_path: 音频文件路径
            language: 识别语言，默认 zh（中文普通话）
            segment_seconds: 时间分段秒数。0 = 仅按 API 限制切分（>55s）；
                             10/15/20 = 每 N 秒一段，转写结果带时间戳。

        Returns:
            转写文本（纯文字，不含时间戳）
        """
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return ""

        if not self.is_configured:
            logger.error("讯飞 ASR 未配置，请在 .env 中设置 XF_IAT_APP_ID / XF_IAT_API_KEY / XF_IAT_API_SECRET")
            return ""

        if segment_seconds is None:
            segment_seconds = self.segment_seconds

        logger.step_begin("讯飞语音转文字")
        size_mb = os.path.getsize(audio_path) / 1024 / 1024
        logger.detail(f"音频文件: {os.path.basename(audio_path)} ({size_mb:.1f}MB)")

        # 1. 获取音频时长
        duration = self._get_duration(audio_path)
        logger.detail(f"音频时长: {duration:.0f}秒")

        # 2. 转换 + 分段
        tmpdir = None
        pcm_chunks, chunk_starts = self._convert_and_split(
            audio_path, duration, segment_seconds
        )
        if pcm_chunks:
            tmpdir = os.path.dirname(pcm_chunks[0])
        if segment_seconds > 0:
            logger.detail(f"时间戳分段: 每{segment_seconds}秒, 共{len(pcm_chunks)}段")
        else:
            logger.detail(f"分段数: {len(pcm_chunks)}")

        # 3. 逐段转写
        raw_texts = []
        for i, pcm_file in enumerate(pcm_chunks, 1):
            if len(pcm_chunks) > 1:
                logger.progress(i, len(pcm_chunks), "讯飞转写进度")

            try:
                text = self._transcribe_pcm(pcm_file, language)
                if text:
                    text = re.sub(r'\s+', '', text)
                    raw_texts.append(text)
                else:
                    logger.warn(f"分段 {i}/{len(pcm_chunks)} 返回空白")
                    raw_texts.append("")
            except Exception as e:
                logger.error(f"分段 {i}/{len(pcm_chunks)} 转写失败: {e}")
                raw_texts.append("")
                continue
            finally:
                if os.path.exists(pcm_file):
                    try:
                        os.unlink(pcm_file)
                    except OSError:
                        pass

        # 4. 裁剪头尾 overlap（按字数比例，比文本匹配更可靠）
        if segment_seconds > 0 and len(raw_texts) > 1:
            merged = []
            for i, text in enumerate(raw_texts):
                is_first = (i == 0)
                is_last = (i == len(raw_texts) - 1)
                win = (segment_seconds + OVERLAP_SECONDS) if is_first \
                    else (segment_seconds + 2 * OVERLAP_SECONDS)
                merged.append(self._trim_overlap(text, win, is_first, is_last))
        else:
            merged = raw_texts

        # 5. 生成结果
        full_text = "".join(merged) if merged else ""
        timestamped = []
        if segment_seconds > 0:
            for i, text in enumerate(merged):
                if text and i < len(chunk_starts):
                    t_start = chunk_starts[i]
                    t_end = min(t_start + segment_seconds, duration)
                    timestamped.append(_format_timestamp(t_start, t_end, text))
        timestamped_text = "\n\n".join(timestamped) if timestamped else ""

        logger.detail(f"转写完成: {len(full_text)} 字符")
        logger.step_end()

        # 6. 清理临时目录
        if tmpdir and os.path.isdir(tmpdir):
            try:
                for f in os.listdir(tmpdir):
                    try:
                        os.unlink(os.path.join(tmpdir, f))
                    except OSError:
                        pass
                os.rmdir(tmpdir)
            except OSError:
                pass

        # 7. 保存转写文本
        if full_text:
            txt_path = self._save_transcript(audio_path, full_text, timestamped_text)
            if txt_path:
                logger.detail(f"转写文本已保存: {os.path.basename(txt_path)}")

        if not full_text:
            logger.warn("讯飞返回为空，可能是音频质量问题或 API 限制")

        return full_text

    # ---------- 内部方法 ----------

    def _save_transcript(self, audio_path: str, plain_text: str,
                          timestamped_text: str = "") -> str:
        """保存转写文本到 output 目录"""
        try:
            base_name = os.path.splitext(os.path.basename(audio_path))[0]
            txt_path = os.path.join(OUTPUT_DIR, f"{base_name}_transcript.txt")

            import time
            parts = [
                f"# 语音转写文本",
                f"# 音频文件: {os.path.basename(audio_path)}",
                f"# 转写时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"# 引擎: 讯飞语音听写 (IAT)",
                f"# 字符数: {len(plain_text)}",
                "",
                plain_text,
            ]
            if timestamped_text:
                parts.extend([
                    "",
                    "---",
                    "# 带时间戳版本",
                    "",
                    timestamped_text,
                ])

            content = "\n".join(parts)
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return txt_path
        except Exception as e:
            logger.warn(f"保存转写文本失败: {e}")
            return ""

    def _trim_overlap(self, text: str, window_sec: float, is_first: bool,
                       is_last: bool) -> str:
        """按时间比例裁掉窗口头尾的 overlap 区域

        每段含 OVERLAP_SECONDS 前瞻/回看，对应文本按字数比例估算后裁掉。
        ASR 输出不完全一致，用文本匹配不可靠，按时间裁剪更稳定。
        """
        if not text or OVERLAP_SECONDS <= 0:
            return text

        char_rate = len(text) / window_sec if window_sec > 0 else 0
        drop_n = int(char_rate * OVERLAP_SECONDS)

        start = 0
        end = len(text)

        if not is_first and drop_n > 0:
            start = min(drop_n, len(text) // 3)  # 最多裁 1/3
        if not is_last and drop_n > 0:
            end = len(text) - min(drop_n, len(text) // 3)

        if start >= end:
            return text  # 保护：不裁空
        return text[start:end]

    def _get_duration(self, audio_path: str) -> float:
        """用 ffprobe 获取音频时长（秒）"""
        try:
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, timeout=10,
            )
            return float(proc.stdout.strip()) if proc.stdout.strip() else 0.0
        except Exception:
            return 0.0

    def _convert_and_split(self, audio_path: str, duration: float,
                            segment_seconds: int = 0) -> tuple:
        """将音频转为 PCM 16kHz mono，按需切分

        切分策略：
        - segment_seconds=0: 仅切 >55s 的段（API 限制），无重叠
        - segment_seconds>0: 滑动窗口 + 前后重叠 OVERLAP_SECONDS 秒，
          消除段边界截断。每段独立含上下文，后续去重合并。

        Returns:
            (pcm_chunks, chunk_starts) — chunk_starts 是每段展示起始秒数
        """
        if duration <= 0:
            duration = 999

        tmpdir = tempfile.mkdtemp(prefix="xfyun_")
        bytes_per_sec = SAMPLE_RATE * 2  # 32000

        # 先转成完整 PCM
        full_pcm = os.path.join(tmpdir, "full.pcm")
        self._ffmpeg_to_pcm(audio_path, full_pcm)

        # 确定分段参数
        if segment_seconds > 0:
            # 时间戳模式：滑动窗口
            stride = segment_seconds
            overlap = OVERLAP_SECONDS
            window_sec = stride + overlap  # 主内容 + 前瞻
            # 中间段多加一段回看
            mid_window_sec = stride + 2 * overlap
        else:
            # 普通模式：仅按 API 限制切分
            stride = MAX_CHUNK_SECONDS
            overlap = 0
            window_sec = stride

        if duration <= stride:
            return [full_pcm], [0.0]

        # 滑动窗口切分
        chunks = []
        starts = []
        with open(full_pcm, "rb") as fp:
            idx = 0
            while True:
                # 计算当前窗口的字节偏移
                if idx == 0:
                    byte_offset = 0
                    win = window_sec  # 首段：主内容 + 前瞻
                else:
                    byte_offset = int((idx * stride - overlap) * bytes_per_sec)
                    fp.seek(byte_offset)
                    win = mid_window_sec if overlap > 0 else window_sec

                data = fp.read(int(win * bytes_per_sec))
                if not data:
                    break

                chunk_file = os.path.join(tmpdir, f"chunk_{idx:03d}.pcm")
                with open(chunk_file, "wb") as out:
                    out.write(data)
                chunks.append(chunk_file)
                starts.append(float(idx * stride))
                idx += 1

        os.unlink(full_pcm)

        if not chunks:
            return [full_pcm], [0.0]
        return chunks, starts

    def _ffmpeg_to_pcm(self, input_path: str, output_path: str):
        """用 ffmpeg 将音频转为 PCM 16kHz mono"""
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(SAMPLE_RATE),
             "-f", "s16le", output_path],
            capture_output=True, text=True, timeout=120,
        )

    def _transcribe_pcm(self, pcm_file: str, language: str) -> str:
        """通过 WebSocket 将 PCM 文件发送给讯飞并获取识别结果"""
        # 构造鉴权 URL
        ws_url = self._build_auth_url()

        # 共享状态
        result_text = ""
        result_event = threading.Event()
        error_info = {"msg": ""}

        def on_open(ws):
            """连接建立后，启动线程发送音频"""
            def send_audio():
                try:
                    self._send_audio_frames(ws, pcm_file, language)
                except Exception as e:
                    error_info["msg"] = str(e)
                    result_event.set()

            t = threading.Thread(target=send_audio, daemon=True)
            t.start()

        # 单词位置数组（讯飞使用增量替换式协议，需按位置维护）
        word_slots = []

        def on_message(ws, message):
            """处理识别结果（增量替换式协议）"""
            nonlocal result_text, word_slots
            try:
                msg = json.loads(message)
                code = msg.get("header", {}).get("code", 0)
                status = msg.get("header", {}).get("status", 0)
                if code != 0:
                    error_info["msg"] = f"讯飞 API 错误码: {code}"
                    ws.close()
                    return

                payload = msg.get("payload", {})
                if payload:
                    raw = payload.get("result", {}).get("text", "")
                    if raw:
                        decoded = json.loads(base64.b64decode(raw).decode("utf-8"))
                        pgs = decoded.get("pgs", "")  # "rpl"=替换, "apd"=追加
                        new_words = []
                        for wg in decoded.get("ws", []):
                            for cw in wg.get("cw", []):
                                new_words.append(cw.get("w", ""))

                        if pgs == "rpl":
                            rg = decoded.get("rg", [1, 1])  # 1-indexed, inclusive
                            start_1, end_1 = rg[0], rg[1]
                            # 扩展数组
                            while len(word_slots) < end_1:
                                word_slots.append("")
                            # 替换指定范围
                            for i, w in enumerate(new_words):
                                pos = start_1 - 1 + i
                                if pos < len(word_slots):
                                    word_slots[pos] = w
                        elif pgs == "apd":
                            word_slots.extend(new_words)

                # status == 2 表示识别结束，组装最终结果
                if status == 2:
                    result_text = "".join(word_slots)
                    ws.close()
            except Exception as e:
                error_info["msg"] = f"解析讯飞响应失败: {e}"

        def on_error(ws, error):
            error_info["msg"] = str(error)
            result_event.set()

        def on_close(ws, code, msg):
            nonlocal result_text
            # 兜底：如果 status==2 消息未设置 result_text，用 word_slots
            if not result_text and word_slots:
                result_text = "".join(word_slots)
            result_event.set()

        # 建立 WebSocket 连接
        ws_app = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        # 在独立线程中运行 WebSocket
        ws_thread = threading.Thread(
            target=lambda: ws_app.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=10,
                ping_timeout=5,
            ),
            daemon=True,
        )
        ws_thread.start()

        # 等待完成（最长等待时间 = 音频时长 * 1.5 + 10秒余量）
        timeout = MAX_CHUNK_SECONDS * 1.5 + 10
        result_event.wait(timeout=timeout)

        if error_info["msg"]:
            logger.warn(f"讯飞 WebSocket 错误: {error_info['msg']}")

        return result_text

    def _send_audio_frames(self, ws, pcm_file: str, language: str):
        """发送音频帧到讯飞"""
        # 规范化语言码：讯飞 IAT 需要 zh_cn 格式
        lang_map = {"zh": "zh_cn", "en": "en_us", "ja": "ja_jp", "ko": "ko_kr"}
        iat_lang = lang_map.get(language, language)

        status_first = 0
        status_continue = 1
        status_last = 2

        with open(pcm_file, "rb") as fp:
            status = status_first
            while True:
                buf = fp.read(FRAME_SIZE)
                audio_b64 = base64.b64encode(buf).decode("utf-8") if buf else ""

                if not buf:
                    status = status_last

                if status == status_first:
                    # 第一帧：携带参数
                    d = {
                        "header": {"status": 0, "app_id": self.app_id},
                        "parameter": {
                            "iat": {
                                "domain": "slm",
                                "language": iat_lang,
                                "accent": "mandarin",
                                "dwa": "wpgs",
                                "result": {
                                    "encoding": "utf8",
                                    "compress": "raw",
                                    "format": "plain",
                                }
                            }
                        },
                        "payload": {
                            "audio": {
                                "audio": audio_b64,
                                "sample_rate": SAMPLE_RATE,
                                "encoding": "raw",
                            }
                        },
                    }
                    ws.send(json.dumps(d))
                    status = status_continue

                elif status == status_continue:
                    d = {
                        "header": {"status": 1, "app_id": self.app_id},
                        "parameter": {
                            "iat": {
                                "domain": "slm",
                                "language": iat_lang,
                                "accent": "mandarin",
                                "dwa": "wpgs",
                                "result": {
                                    "encoding": "utf8",
                                    "compress": "raw",
                                    "format": "plain",
                                }
                            }
                        },
                        "payload": {
                            "audio": {
                                "audio": audio_b64,
                                "sample_rate": SAMPLE_RATE,
                                "encoding": "raw",
                            }
                        },
                    }
                    ws.send(json.dumps(d))

                elif status == status_last:
                    d = {
                        "header": {"status": 2, "app_id": self.app_id},
                        "parameter": {
                            "iat": {
                                "domain": "slm",
                                "language": iat_lang,
                                "accent": "mandarin",
                                "dwa": "wpgs",
                                "result": {
                                    "encoding": "utf8",
                                    "compress": "raw",
                                    "format": "plain",
                                }
                            }
                        },
                        "payload": {
                            "audio": {
                                "audio": audio_b64,
                                "sample_rate": SAMPLE_RATE,
                                "encoding": "raw",
                            }
                        },
                    }
                    ws.send(json.dumps(d))
                    break

                if not self.fast:
                    time.sleep(SEND_INTERVAL)

    def _build_auth_url(self) -> str:
        """构造讯飞 IAT WebSocket 鉴权 URL

        严格按照讯飞官方 demo 的方式：
        - 使用 format_date_time 生成 RFC1123 时间
        - 使用 ws:// 协议（非 wss://）
        - HMAC-SHA256 签名
        """
        # 生成 RFC1123 格式的时间戳（与 demo 完全一致）
        now = datetime.datetime.now()
        date_str = format_date_time(mktime(now.timetuple()))

        # 拼接签名原文
        signature_origin = (
            "host: iat.xf-yun.com\n"
            "date: " + date_str + "\n"
            "GET /v1 HTTP/1.1"
        )

        # HMAC-SHA256 签名
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode("utf-8")

        # 构造 Authorization
        auth_origin = (
            'api_key="%s", algorithm="%s", headers="%s", signature="%s"'
            % (self.api_key, "hmac-sha256", "host date request-line", signature)
        )
        authorization = base64.b64encode(auth_origin.encode("utf-8")).decode("utf-8")

        # 拼接 URL 参数
        params = {
            "authorization": authorization,
            "date": date_str,
            "host": "iat.xf-yun.com",
        }
        return IAT_WS_URL + "?" + urlencode(params)
