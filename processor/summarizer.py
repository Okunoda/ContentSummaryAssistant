"""LLM 总结模块

五段式摘要：摘要 → 亮点 → 思考 → 术语 → 技术视角
"""
from openai import OpenAI
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

MAX_CONTENT_CHARS = 12000

SYSTEM_PROMPT = """你是一位拥有十年经验的资深工程师（Staff Engineer），负责帮团队做内容提炼。

核心任务：准确还原作者的观点和论证过程，而非做外部评价。

风格要求：
- 严谨精确，拒绝营销腔和空洞形容词（"颠覆性""秘籍"等）
- 价值评分依据：观点原创性、论证严谨度、方法可操作性
- 不做真实性/时效性/受众匹配度评价——只提炼，不验证"""

VIDEO_TEMPLATE = """请总结以下视频内容。

注意：【视频文稿】来自 ASR 语音转文字，存在同音错字、英文术语拼写错误、断句异常等问题。请自行纠正（如 "atoa"→"A2A"、"agentcart"→"Agent Card" 等），以纠正后内容为准。

【视频标题】{title}
【视频简介】{description}
【视频文稿/字幕】
{transcript}

---
## 一、内容摘要
概述性质，说明这个视频整体讲了什么。不限制字数——内容多就多写，忠实还原视频的完整面貌。

## 二、核心亮点
作者的主要观点及其论证来源（如果提到了的话）。数量不做限制，以实际情况为准。每个亮点标注：① 观点是什么 ② 如何论证的（数据/案例/类比/代码/理论推导等）。

## 三、深度思考
这个视频引发了哪些值得深入思考的方向？作者给出了什么答案（如果有的话）？有哪些值得进一步探索的开放问题？

## 四、术语解释
视频中出现的新术语、反复提及的核心概念。每个术语给出视频中的定义（如果作者给出了的话）和简要说明。

## 五、技术视角
从工程实践角度分析。核心观点背后的技术原理是什么？涉及哪些技术选型或架构决策？有哪些可复用的方法、模式或思路？"""

ARTICLE_TEMPLATE = """请总结以下文章内容。

【文章标题】{title}
【作者/来源】{author}
【文章正文】
{content}

---
## 一、内容摘要
概述性质，说明这篇文章整体讲了什么。不限制字数——内容多就多写，忠实还原文章的完整面貌。

## 二、核心亮点
作者的主要观点及其论证来源（如果提到了的话）。数量不做限制，以实际情况为准。每个亮点标注：① 观点是什么 ② 如何论证的（数据/案例/类比/代码/理论推导等）。

## 三、深度思考
这篇文章引发了哪些值得深入思考的方向？作者给出了什么答案（如果有的话）？有哪些值得进一步探索的开放问题？

## 四、术语解释
文章中出现的新术语、反复提及的核心概念。每个术语给出文中的定义（如果作者给出了的话）和简要说明。

## 五、技术视角
从工程实践角度分析。核心观点背后的技术原理是什么？涉及哪些技术选型或架构决策？有哪些可复用的方法、模式或思路？"""


class Summarizer:
    """五段式内容摘要器"""

    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        if LLM_API_KEY:
            self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)

    def summarize_video(self, title: str, description: str, transcript: str) -> str:
        if not self.client:
            return "⚠️ 未配置 LLM API Key"
        if transcript and len(transcript) > MAX_CONTENT_CHARS:
            transcript = transcript[:MAX_CONTENT_CHARS] + "\n...(文本过长，已截断)"
        prompt = VIDEO_TEMPLATE.format(
            title=title or "无标题",
            description=description or "无简介",
            transcript=transcript or "无文稿",
        )
        return self._call(prompt)

    def summarize_article(self, title: str, author: str, content: str) -> str:
        if not self.client:
            return "⚠️ 未配置 LLM API Key"
        if content and len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n...(文本过长，已截断)"
        prompt = ARTICLE_TEMPLATE.format(
            title=title or "无标题",
            author=author or "未知来源",
            content=content or "无正文",
        )
        return self._call(prompt)

    def _call(self, prompt: str) -> str:
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=1.0,
                max_tokens=100000,
            )
            try:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            except Exception:
                pass
            response = self.client.chat.completions.create(**kwargs)
            if not response.choices:
                return "LLM 返回了空结果"
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"LLM 调用失败: {str(e)}"
