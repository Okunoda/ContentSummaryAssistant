"""LLM 总结模块

聚焦内容本身：还原作者的观点和论证过程，提取可复用的方法论。
"""
from openai import OpenAI
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL

MAX_CONTENT_CHARS = 12000

SYSTEM_PROMPT = """你是一位拥有十年经验的资深工程师（Staff Engineer），负责帮团队做内容提炼。你的核心任务是：准确还原作者的观点和论证过程，而非做外部评价。

你的输出风格：
- 严谨、精确、结构化，拒绝营销腔和空洞形容词（如"颠覆性""彻底改变""秘籍"等）
- 重点关注：作者的核心观点是什么、这些观点是怎么得出的（推理、案例、数据、类比）、有哪些可复用的方法或思路
- 价值评分依据：观点的原创性、论证的严谨程度、方法的可操作性。纯观点罗列无推理 → 低分。有完整推导链路或可落地实践 → 高分
- 不需要评价内容的真实性、时效性或受众匹配度——你只负责提炼，不负责验证

在输出前，先于 <thinking> 标签内完成以下分析：
1. 核心观点链：作者提出了哪几个主要观点？它们之间的逻辑关系是什么？
2. 论证方式：每个观点通过什么方式支撑（案例、数据、类比、代码演示、理论推导、个人经验等）
3. 可提取的方法/思路：有哪些跨场景可复用的工程方法、设计思路或思维模型

回复格式固定为以下结构，不要添加额外内容，不要在回复中提及你的分析过程。"""

VIDEO_TEMPLATE = """请审阅以下视频内容，提炼核心观点和论证过程。

注意：以下【视频文稿】来自语音转文字（ASR），可能存在同音错字、英文术语拼写错误、断句异常等问题。请在阅读时自行纠正明显的识别错误（如 "atoa" 应为 "A2A"，"agentcart" 应为 "Agent Card"，"talk" 应为 "token" 等），以纠正后的内容为准进行总结。

【视频标题】
{title}

【视频简介】
{description}

【视频文稿/字幕】
{transcript}

---
请先在 <thinking> 标签内完成三维度分析，再输出正式回复：

<thinking>
1. 核心观点链：
2. 论证方式：
3. 可提取的方法/思路：
</thinking>

## 价值评分：X/10
（基于观点原创性、论证严谨度、方法可操作性综合评定）

## 核心观点
（作者提出了哪几个主要观点，观点之间的逻辑链是怎样的）

## 论证与推导
（每个观点是如何得出的——用了什么案例、数据、类比、代码、推理——把论证路径还原出来）

## 方法论 / 可复用思路
（从内容中可以提取哪些跨场景适用的工程方法、设计模式、思维模型；如果内容深度不足，说明"无值得提炼的方法论"）

## 建议
（"值得花时间看原视频" 或 "看总结即可，无需观看原视频" 或 "不推荐观看"）"""

ARTICLE_TEMPLATE = """请审阅以下文章内容，提炼核心观点和论证过程。

【文章标题】
{title}

【作者/来源】
{author}

【文章正文】
{content}

---
请先在 <thinking> 标签内完成三维度分析，再输出正式回复：

<thinking>
1. 核心观点链：
2. 论证方式：
3. 可提取的方法/思路：
</thinking>

## 价值评分：X/10
（基于观点原创性、论证严谨度、方法可操作性综合评定）

## 核心观点
（作者提出了哪几个主要观点，观点之间的逻辑链是怎样的）

## 论证与推导
（每个观点是如何得出的——用了什么案例、数据、类比、代码、推理）

## 方法论 / 可复用思路
（从内容中可以提取哪些跨场景适用的工程方法、设计模式、思维模型；如果内容深度不足，说明"无值得提炼的方法论"）

## 建议
（"值得花时间读原文" 或 "看总结即可" 或 "不推荐阅读"）"""


class Summarizer:
    """LLM 总结器 — 聚焦内容提炼，不做外部评价"""

    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        if LLM_API_KEY:
            self.client = OpenAI(
                api_key=LLM_API_KEY,
                base_url=LLM_API_BASE,
            )

    def summarize_video(self, title: str, description: str, transcript: str) -> str:
        if not self.client:
            return "⚠️ 未配置 LLM API Key，请在 .env 文件中设置 LLM_API_KEY"

        if transcript and len(transcript) > MAX_CONTENT_CHARS:
            transcript = transcript[:MAX_CONTENT_CHARS] + "\n...(文本过长，已截断)"

        prompt = VIDEO_TEMPLATE.format(
            title=title or "无标题",
            description=description or "无简介",
            transcript=transcript or "无文稿",
        )
        return self._call_llm(prompt)

    def summarize_article(self, title: str, author: str, content: str) -> str:
        if not self.client:
            return "⚠️ 未配置 LLM API Key，请在 .env 文件中设置 LLM_API_KEY"

        if content and len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n...(文本过长，已截断)"

        prompt = ARTICLE_TEMPLATE.format(
            title=title or "无标题",
            author=author or "未知来源",
            content=content or "无正文",
        )
        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> str:
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
                return "LLM 返回了空结果，请检查 API 配置或稍后重试"
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"LLM 调用失败: {str(e)}"
