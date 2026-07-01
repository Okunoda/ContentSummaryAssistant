"""时间线总结代理 — Plan-Execute 架构

Plan 阶段：一个 LLM 调用，将内容拆分为多个章节
Execute 阶段：每个章节独立调用 LLM 进行总结
Merge 阶段：合并所有章节输出

每个章节的总结严格以原文实际表述为准，不虚构不曲解。
"""
import json
import re
from openai import OpenAI
from config import LLM_API_KEY, LLM_API_BASE, LLM_MODEL
from utils.progress import logger

MAX_CONTENT_CHARS = 12000
MAX_CHAPTER_CHARS = 4000  # 每章传给 LLM 的最大字符数

PLAN_PROMPT = """你是一个内容结构分析器。分析以下{content_type}的文稿，将其拆分为多个逻辑章节。

规则：
1. 按主题/话题的自然转换点拆分，不要按固定时间间隔硬切
2. 每个章节应该有独立的主题，章节之间主题不重复
3. 章节数量以实际内容为准，通常 3~10 个
4. 如果一个主题反复出现，合并到同一个章节
5. 为每个章节提取：① 章节标题（简洁概括主题）② 起始位置（视频为时间 MM:SS，文章为段落描述）

【标题】{title}
【文稿】
{content}

---
返回严格的 JSON 数组（不要包含其他内容），每项格式：
{{"title": "章节标题", "start": "起始位置", "summary": "一句话描述该章节内容"}}"""

EXECUTE_PROMPT = """你是一个精准的内容总结器。以下文稿来自'{title}'的一个章节。请严格以原文实际表述为准，输出该章节的结构化总结。

【章节名称】{chapter_title}
【章节文稿】
{chapter_content}

---
请输出：

## {chapter_title}
**位置**：{start}

### 主题概述
该章节的核心主题是什么，一句话概括。

### 论述内容
作者在该章节中实际讲了什么——按原文的叙述顺序，逐段提炼。每段注明：
- 观点/论断是什么
- 用了什么论据（案例、数据、类比、代码等，如果原文提到了的话）

### 关键引用
如果原文中有特别精炼或标志性的表述，摘录 1-3 句（标注为"原文大意"，ASR 可能有误）。"""


class TimelineAgent:
    """Plan-Execute 时间线总结代理

    Plan  → 1 次 LLM 调用，拆分章节
    Execute → N 次 LLM 调用，每章独立总结
    """

    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        if LLM_API_KEY:
            self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)

    def process(self, title: str, content: str,
                content_type: str = "视频") -> str:
        """完整 Plan-Execute 流程

        Args:
            title: 视频/文章标题
            content: 转写文稿/文章正文
            content_type: "视频" 或 "文章"

        Returns:
            完整的时间线总结 Markdown
        """
        if not self.client:
            return "⚠️ 未配置 LLM API Key"
        if not content.strip():
            return "⚠️ 内容为空"

        # 截断
        full_content = content
        if len(content) > MAX_CONTENT_CHARS:
            full_content = content[:MAX_CONTENT_CHARS]

        # ---------- Plan ----------
        logger.step_begin(f"Plan: 分析{content_type}结构")
        plan = self._plan(title, full_content, content_type)
        if not plan:
            logger.error("Plan 阶段失败")
            return "Plan 阶段失败，无法拆分章节"
        logger.detail(f"识别到 {len(plan)} 个章节")
        for i, ch in enumerate(plan, 1):
            logger.detail(f"  {i}. [{ch['start']}] {ch['title']}")
        logger.step_end()

        # ---------- Execute ----------
        logger.step_begin(f"Execute: 逐章总结 ({len(plan)} 章)")
        # 为每章切出对应的内容段
        chapter_contents = self._split_content(full_content, plan)
        chapters = []
        for i, (ch, ch_content) in enumerate(zip(plan, chapter_contents), 1):
            logger.progress(i, len(plan), f"总结: {ch['title']}")
            result = self._execute_chapter(title, ch, ch_content)
            chapters.append(result)
            logger.detail(f"  第{i}章完成: {len(result)} 字符")
        logger.step_end()

        # ---------- Merge ----------
        return self._merge(title, content_type, chapters)

    # ======== Plan 阶段 ========

    def _plan(self, title: str, content: str, content_type: str) -> list[dict]:
        """一次 LLM 调用，返回章节列表"""
        prompt = PLAN_PROMPT.format(
            content_type=content_type,
            title=title,
            content=content,
        )
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4000,
            )
            response = self.client.chat.completions.create(**kwargs)
            text = (response.choices[0].message.content or "").strip()
            return self._parse_plan_json(text)
        except Exception as e:
            logger.error(f"Plan 调用失败: {e}")
            return []

    def _parse_plan_json(self, text: str) -> list[dict]:
        """从 LLM 回复中提取 JSON 数组"""
        # 去掉可能的 markdown 代码块标记
        text = re.sub(r'^```(?:json)?\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text.strip())
        try:
            plan = json.loads(text)
            if isinstance(plan, list) and len(plan) > 0:
                return plan
        except json.JSONDecodeError:
            # 尝试提取 [...] 部分
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        logger.warn("Plan JSON 解析失败，使用原文降级")
        return []

    # ======== Execute 阶段 ========

    def _split_content(self, content: str, plan: list[dict]) -> list[str]:
        """按章节切分内容（简单按比例分配，后续可用更精确的定位）"""
        if len(plan) <= 1:
            return [content]

        # 按比例分配字符
        chunks = []
        chunk_size = len(content) // len(plan)
        for i in range(len(plan)):
            start = i * chunk_size
            if i == len(plan) - 1:
                end = len(content)
            else:
                end = (i + 1) * chunk_size
            # 扩展到最近的段落边界
            chunk = content[start:end].strip()
            # 截断过长章节
            if len(chunk) > MAX_CHAPTER_CHARS:
                chunk = chunk[:MAX_CHAPTER_CHARS] + "\n...(已截断)"
            chunks.append(chunk)
        return chunks

    def _execute_chapter(self, title: str, chapter: dict, content: str) -> str:
        """一次 LLM 调用，总结一个章节"""
        prompt = EXECUTE_PROMPT.format(
            title=title,
            chapter_title=chapter.get("title", "未命名"),
            start=chapter.get("start", ""),
            chapter_content=content,
        )
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=2000,
            )
            response = self.client.chat.completions.create(**kwargs)
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"*章节总结失败: {e}*"

    # ======== Merge 阶段 ========

    def _merge(self, title: str, content_type: str, chapters: list[str]) -> str:
        """合并所有章节输出"""
        lines = [
            f"# {title} — 时间线梳理",
            "",
            f"*由 Plan-Execute Agent 自动生成，共 {len(chapters)} 个章节*",
            "",
            "---",
            "",
        ]
        for i, ch in enumerate(chapters, 1):
            lines.append(ch)
            lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines)
