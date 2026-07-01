"""爬虫基类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Union


@dataclass
class VideoResult:
    """视频爬取结果"""
    platform: str
    title: str = ""
    description: str = ""
    video_path: str = ""        # 下载的视频文件路径
    audio_path: str = ""         # 提取的音频文件路径
    subtitle_text: str = ""      # 字幕文本（如果有）
    transcript_text: str = ""    # 转写文本（Whisper结果）
    summary: str = ""            # LLM总结
    success: bool = False
    error: str = ""


@dataclass
class ArticleResult:
    """文章爬取结果"""
    platform: str
    title: str = ""
    author: str = ""
    publish_time: str = ""
    content_html: str = ""
    content_markdown: str = ""
    markdown_path: str = ""      # 保存的 md 文件路径
    source_url: str = ""         # 原始链接
    summary: str = ""            # LLM总结
    success: bool = False
    error: str = ""


class BaseCrawler(ABC):
    """爬虫基类"""

    def __init__(self):
        self.platform = "unknown"

    @abstractmethod
    def process(self, url: str):
        """处理链接，返回结果"""
        pass
