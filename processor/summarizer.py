"""LLM 总结模块
使用 OpenAI 兼容 API 进行文本总结
"""
from openai import OpenAI
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL


MAX_CONTENT_CHARS = 8000  # 传给 LLM 的最大文本长度


class Summarizer:
    """LLM 总结器"""

    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        if LLM_API_KEY:
            self.client = OpenAI(
                api_key=LLM_API_KEY,
                base_url=LLM_API_BASE,
            )

    def summarize_video(self, title: str, description: str, transcript: str) -> str:
        """
        总结视频内容

        Args:
            title: 视频标题
            description: 视频描述/简介
            transcript: 视频转写文本（字幕或Whisper结果）

        Returns:
            总结文本
        """
        if not self.client:
            return "⚠️ 未配置 LLM API Key，请在 .env 文件中设置 LLM_API_KEY"

        # 构建提示词
        prompt = self._build_video_prompt(title, description, transcript)

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的内容总结助手。请根据提供的视频信息，"
                            "生成一份清晰、结构化的内容总结。使用中文回复。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.3,
                # max_tokens=2000,
            )
            if not response.choices:
                return "LLM 返回了空结果，请检查 API 配置或稍后重试"
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"LLM 调用失败: {str(e)}"

    def summarize_article(self, title: str, author: str, content: str) -> str:
        """
        总结文章内容

        Args:
            title: 文章标题
            author: 作者/公众号名称
            content: 文章正文（Markdown格式）

        Returns:
            总结文本
        """
        if not self.client:
            return "⚠️ 未配置 LLM API Key，请在 .env 文件中设置 LLM_API_KEY"

        prompt = self._build_article_prompt(title, author, content)

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的内容总结助手。请根据提供的文章内容，"
                            "生成一份清晰、结构化的总结。使用中文回复。"
                            "总结应包括：核心观点、关键信息、文章结构。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.3,
                # max_tokens=2000,
            )
            if not response.choices:
                return "LLM 返回了空结果，请检查 API 配置或稍后重试"
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"LLM 调用失败: {str(e)}"

    def _build_video_prompt(self, title: str, description: str, transcript: str) -> str:
        """构建视频总结提示词"""
        parts = []

        parts.append("请总结以下视频的内容：\n")

        if title:
            parts.append(f"【视频标题】\n{title}\n")

        if description:
            parts.append(f"【视频简介】\n{description}\n")

        if transcript:
            # 如果文本太长，截断
            # if len(transcript) > MAX_CONTENT_CHARS:
            #     transcript = transcript[:MAX_CONTENT_CHARS] + "\n...(文本过长，已截断)"
            parts.append(f"【视频文稿/字幕】\n{transcript}\n")

        parts.append("\n请从以下几个方面总结：")
        parts.append("1. 一句话概括视频主题")
        parts.append("2. 核心内容要点（3-5个要点）")
        parts.append("3. 视频的关键信息或结论")
        parts.append("4. 适合什么样的人群观看")

        return "\n".join(parts)

    def _build_article_prompt(self, title: str, author: str, content: str) -> str:
        """构建文章总结提示词"""
        parts = []

        parts.append("请总结以下文章的内容：\n")

        if title:
            parts.append(f"【文章标题】\n{title}\n")

        if author:
            parts.append(f"【作者/公众号】\n{author}\n")

        if content:
            # 如果文本太长，截断
            # if len(content) > MAX_CONTENT_CHARS:
            #     content = content[:MAX_CONTENT_CHARS] + "\n...(文本过长，已截断)"
            parts.append(f"【文章正文】\n{content}\n")

        parts.append("\n请从以下几个方面总结：")
        parts.append("1. 一句话概括文章主题")
        parts.append("2. 核心观点和关键信息（3-5个要点）")
        parts.append("3. 文章的主要结论或启示")
        parts.append("4. 这篇文章适合什么样的人群阅读")

        return "\n".join(parts)
