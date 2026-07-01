"""语音转文字模块
使用 faster-whisper 将音频转为文字，并自动保存为 txt 文件
"""
import os
from config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE, OUTPUT_DIR
from utils.progress import logger


class Transcriber:
    """语音转文字 - 使用 faster-whisper"""

    def __init__(self):
        self.model = None
        self._model_name = WHISPER_MODEL

    def _load_model(self):
        """延迟加载模型（首次使用时加载）"""
        if self.model is not None:
            return

        try:
            from faster_whisper import WhisperModel
            logger.detail(f"加载 Whisper 模型: {self._model_name} (设备: {WHISPER_DEVICE})...")
            self.model = WhisperModel(
                self._model_name,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
            logger.detail("Whisper 模型加载完成")
        except ImportError:
            raise ImportError(
                "请安装 faster-whisper: pip install faster-whisper\n"
                "或使用 openai-whisper: pip install openai-whisper"
            )

    def transcribe(self, audio_path: str, language: str = "zh") -> str:
        """
        将音频文件转写为文字，并自动保存为 .txt 文件

        Returns:
            转写文本
        """
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return f"音频文件不存在: {audio_path}"

        logger.step_begin("语音转文字")
        logger.detail(f"音频文件: {os.path.basename(audio_path)}")
        size_mb = os.path.getsize(audio_path) / 1024 / 1024
        logger.detail(f"文件大小: {size_mb:.1f}MB")

        try:
            self._load_model()

            logger.detail("Whisper 转写中 (VAD过滤 + beam=5)...")
            segments, info = self.model.transcribe(
                audio_path,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            # 检测到的语言
            detected_lang = info.language if info else "unknown"
            logger.detail(f"检测语言: {detected_lang}, 概率: {info.language_probability:.2f}" if info else "")

            # 收集所有文本段
            texts = []
            timestamped = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    texts.append(text)
                    timestamped.append(f"[{segment.start:.1f}s-{segment.end:.1f}s] {text}")

            full_text = "\n".join(texts)
            timestamped_text = "\n".join(timestamped)

            # 清理转写结果
            import re
            full_text = re.sub(r'\s+', ' ', full_text)
            full_text = full_text.strip()

            logger.detail(f"转写完成: {len(full_text)} 字符, {len(texts)} 段")

            # 保存转写文本
            txt_path = self._save_transcript(audio_path, full_text, timestamped_text)
            if txt_path:
                logger.detail(f"转写文本已保存: {os.path.basename(txt_path)}")

            logger.step_end()
            return full_text

        except Exception as e:
            logger.error(f"语音转写失败: {e}")
            return f"语音转写失败: {str(e)}"

    def _save_transcript(self, audio_path: str, plain_text: str, timestamped_text: str) -> str:
        """保存转写文本到文件"""
        try:
            # 基于音频文件名生成文本文件名
            base_name = os.path.splitext(os.path.basename(audio_path))[0]
            txt_path = os.path.join(OUTPUT_DIR, f"{base_name}_transcript.txt")

            import time
            content = f"""# 语音转写文本
# 音频文件: {os.path.basename(audio_path)}
# 转写时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
# 模型: {self._model_name}
# 字符数: {len(plain_text)}

{plain_text}

---
# 带时间戳版本

{timestamped_text}
"""
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return txt_path
        except Exception as e:
            logger.warn(f"保存转写文本失败: {e}")
            return ""

    def transcribe_with_timestamps(self, audio_path: str, language: str = "zh") -> list[dict]:
        """转写音频并带时间戳"""
        if not os.path.exists(audio_path):
            return []

        try:
            self._load_model()
            segments, _ = self.model.transcribe(audio_path, language=language, beam_size=5)

            results = []
            for segment in segments:
                results.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip(),
                })
            return results
        except Exception as e:
            logger.error(f"时间戳转写失败: {e}")
            return []
