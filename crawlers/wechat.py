"""微信公众号文章爬取器

方案：
1. 使用微信移动端 User-Agent + Referer 绕过基础风控
2. BeautifulSoup 解析 HTML，提取标题/作者/正文
3. HTML → Markdown 转换，保存为 .md 文件

如果直接 HTTP 请求失败（SPA 渲染问题），降级使用 WeSpy 库。
"""
import os
import re
import requests
from bs4 import BeautifulSoup
from crawlers.base import BaseCrawler, ArticleResult
from config import OUTPUT_DIR
from utils.helpers import sanitize_filename
from utils.progress import logger


class WechatCrawler(BaseCrawler):
    """微信公众号文章爬取器"""

    def __init__(self):
        super().__init__()
        self.platform = "wechat"
        # 使用微信移动端 UA + 正确 Referer 是获取内容的关键
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 '
                'MicroMessenger/8.0.5'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://mp.weixin.qq.com/',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def process(self, url: str) -> ArticleResult:
        result = ArticleResult(platform="wechat", source_url=url)

        try:
            logger.step_begin("获取微信公众号文章")
            # 1. 获取文章页面
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                logger.error(f"请求失败: HTTP {resp.status_code}")
                result.error = f"请求文章页面失败，状态码: {resp.status_code}"
                return result

            resp.encoding = 'utf-8'
            html = resp.text
            logger.detail(f"页面大小: {len(html)} bytes")

            # 检测是否被拦截
            if self._is_blocked(html):
                logger.error("页面被微信风控拦截")
                result.error = "请求被微信拦截，请稍后再试或更换IP"
                return result

            # 2. 解析文章内容
            soup = BeautifulSoup(html, 'html.parser')
            logger.detail("解析 HTML...")

            # 提取标题
            result.title = self._extract_title(soup)
            logger.detail(f"标题: {result.title}")

            # 提取作者
            result.author = self._extract_author(soup)
            if result.author:
                logger.detail(f"作者: {result.author}")

            # 提取发布时间
            result.publish_time = self._extract_publish_time(soup)
            if result.publish_time:
                logger.detail(f"发布时间: {result.publish_time}")

            # 提取正文
            content_html = self._extract_content(soup)
            if not content_html:
                logger.warn("HTML 中未找到正文，降级到 WeSpy...")
                return self._fallback_wespy(url, result)

            logger.detail(f"正文HTML: {len(content_html)} chars")
            result.content_html = content_html

            # 3. 下载图片到本地（绕过微信防盗链）
            logger.step_begin("下载文章图片")
            img_count = self._download_images(soup, result.title)
            if img_count > 0:
                logger.detail(f"已下载 {img_count} 张图片")
            else:
                logger.detail("文章无图片或下载失败")
            logger.step_end()

            # 4. 转换为 Markdown（图片已替换为本地路径）
            logger.detail("转换为 Markdown...")
            result.content_markdown = self._html_to_markdown(soup)
            logger.detail(f"Markdown: {len(result.content_markdown)} 字符")

            # 4. 保存文件
            result.markdown_path = self._save_markdown(result)
            logger.detail(f"已保存: {os.path.basename(result.markdown_path)}")

            if result.title and result.content_markdown:
                result.success = True
                logger.step_end()
            elif not result.title:
                logger.error("无法提取文章标题")
                result.error = "无法提取文章标题"

        except requests.Timeout:
            result.error = "请求超时，请检查网络连接"
        except requests.RequestException as e:
            result.error = f"网络请求异常: {str(e)}"
        except Exception as e:
            result.error = f"微信公众号处理异常: {str(e)}"
            # 降级到 wespy
            return self._fallback_wespy(url, result)

        return result

    def _fallback_wespy(self, url: str, result: ArticleResult) -> ArticleResult:
        """降级方案：使用 WeSpy 库，保留已提取的信息"""
        try:
            from wespy.main import ArticleFetcher
            fetcher = ArticleFetcher()
            wespy_result = fetcher.fetch_article(
                url, output_dir=OUTPUT_DIR,
                save_html=False, save_json=False, save_markdown=True,
            )
            if wespy_result:
                # 仅当直接提取为空时才用 WeSpy 结果覆盖
                if not result.title:
                    result.title = wespy_result.get("title", "")
                if not result.author:
                    result.author = wespy_result.get("author", "")
                if not result.publish_time:
                    result.publish_time = wespy_result.get("publish_time", "")
                # 正文任何时候都以 WeSpy 为准（因为我们就是因为正文为空才降级的）
                content_text = wespy_result.get("content_text", "")
                if content_text:
                    result.content_markdown = content_text
                    result.markdown_path = self._save_markdown(result)
                    result.success = True
                elif not result.content_markdown:
                    result.error = "WeSpy 也无法获取文章正文内容"
            else:
                if not result.error:
                    result.error = "WeSpy 也无法获取文章内容，可能需要浏览器渲染"
        except ImportError:
            if not result.error:
                result.error = (
                    "直接请求无法获取文章内容（微信已迁移到 SPA 架构）。"
                    "请安装 wespy: pip install wespy"
                )
        except Exception as e:
            if not result.error:
                result.error = f"WeSpy 降级失败: {str(e)}"
        return result

    def _is_blocked(self, html: str) -> bool:
        """检测是否被微信风控拦截"""
        blocked_keywords = [
            '请输入验证码',
            '环境异常',
            '当前访问疑似黑客攻击',
        ]
        for keyword in blocked_keywords:
            if keyword in html:
                return True
        return False

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取文章标题"""
        # 方法1: h1.rich_media_title (微信标准结构)
        title_elem = soup.find('h1', class_='rich_media_title')
        if title_elem:
            text = title_elem.get_text(strip=True)
            if text:
                return text

        # 方法2: #activity-name
        title_elem = soup.find(id='activity-name')
        if title_elem:
            return title_elem.get_text(strip=True)

        # 方法3: og:title meta
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()

        # 方法4: <title>
        title_tag = soup.find('title')
        if title_tag:
            text = title_tag.get_text(strip=True)
            if text:
                return text

        return "未知标题"

    def _extract_author(self, soup: BeautifulSoup) -> str:
        """提取公众号名称"""
        # 方法1: #js_name
        name_elem = soup.find(id='js_name')
        if name_elem:
            return name_elem.get_text(strip=True)

        # 方法2: .profile_nickname
        name_elem = soup.find(class_='profile_nickname')
        if name_elem:
            return name_elem.get_text(strip=True)

        # 方法3: meta author
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            return author_meta['content'].strip()

        return ""

    def _extract_publish_time(self, soup: BeautifulSoup) -> str:
        """提取发布时间"""
        # 方法1: #publish_time
        time_elem = soup.find(id='publish_time')
        if time_elem:
            return time_elem.get_text(strip=True)

        # 方法2: .rich_media_meta_text
        time_elem = soup.find(class_='rich_media_meta_text')
        if time_elem:
            return time_elem.get_text(strip=True)

        # 方法3: 正则搜索
        time_patterns = [
            r'(\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2})',
            r'(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})',
        ]
        text = soup.get_text()
        for pattern in time_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return ""

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """提取文章正文（返回HTML）"""
        # 方法1: #js_content (微信标准结构)
        content_elem = soup.find(id='js_content')
        if content_elem:
            # 移除 visibility:hidden 样式
            if content_elem.get('style'):
                style = content_elem['style']
                style = style.replace('visibility: hidden', 'visibility: visible')
                content_elem['style'] = style
            return str(content_elem)

        # 方法2: .rich_media_content
        content_elem = soup.find(class_='rich_media_content')
        if content_elem:
            return str(content_elem)

        return ""

    # 块级标签：应该递归处理子元素
    BLOCK_TAGS = {'p', 'div', 'section', 'article', 'main', 'aside', 'header', 'footer',
                  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                  'ul', 'ol', 'li', 'blockquote', 'pre', 'table', 'figure', 'figcaption'}
    # 行内标签：格式化后拼接到一行
    INLINE_TAGS = {'strong', 'b', 'em', 'i', 'u', 'a', 'span', 'label', 'font',
                   'code', 'del', 's', 'strike', 'sub', 'sup', 'small', 'mark'}

    def _html_to_markdown(self, soup: BeautifulSoup) -> str:
        """将微信文章HTML转换为Markdown"""
        content_elem = soup.find(id='js_content') or soup.find(class_='rich_media_content')
        if not content_elem:
            return ""

        # 移除隐藏元素
        for hidden in content_elem.find_all(style=re.compile(r'display\s*:\s*none')):
            hidden.decompose()

        markdown_lines = []
        self._convert_block(content_elem, markdown_lines)
        # 合并为文本并清理多余空行
        text = '\n'.join(markdown_lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 清理行尾空白（但保留行首缩进，尤其是代码块）
        text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
        return text.strip()

    def _convert_block(self, element, lines: list):
        """处理块级元素：递归解析子节点，区分块级和行内"""
        for child in element.children:
            if child.name is None:
                # 纯文本节点
                text = str(child)
                # 保留有意义的文本，跳过纯空白
                if text.strip():
                    lines.append(text.strip())
                elif text and not lines:
                    pass  # 跳过开头空白
                continue

            name = child.name.lower()

            if name in ('br', 'hr'):
                lines.append('')

            elif name in self.BLOCK_TAGS:
                self._dispatch_block_tag(name, child, lines)

            elif name in self.INLINE_TAGS or name in ('img', 'br'):
                # 行内元素 → 转成内联 Markdown
                inline_text = self._render_inline(child)
                if inline_text:
                    lines.append(inline_text)

            else:
                # 未知元素：递归进入其子节点
                self._convert_block(child, lines)

    def _dispatch_block_tag(self, name: str, child, lines: list):
        """根据块级标签类型决定如何渲染"""
        # 标题
        if name.startswith('h') and len(name) == 2 and name[1].isdigit():
            lines.append('')
            text = self._render_inline(child)
            if text:
                level = int(name[1])
                lines.append('#' * level + ' ' + text)
            lines.append('')
            return

        # 列表
        if name in ('ul', 'ol'):
            items = child.find_all('li', recursive=False)
            for i, item in enumerate(items):
                prefix = f'{i+1}.' if name == 'ol' else '-'
                item_text = self._render_inline(item)
                if item_text:
                    lines.append(f'{prefix} {item_text}')
            return

        if name == 'li':
            # 单个 li 由父级 ul/ol 处理，这里只递归块级内容
            text = self._render_inline(child)
            if text:
                lines.append(text)
            return

        # 引用块
        if name == 'blockquote':
            inner_lines = []
            self._convert_block(child, inner_lines)
            for l in inner_lines:
                stripped = l.strip()
                if stripped:
                    lines.append(f'> {stripped}')
            # 引用后用空行分隔
            if inner_lines:
                lines.append('')
            return

        # 代码块
        if name == 'pre':
            # 保留原始缩进：用 .get_text() 会保留内部空白
            code_text = child.get_text()
            # 移除首尾空行但保留内部缩进
            code_text = code_text.strip('\n')
            if code_text.strip():
                lines.append('')
                lines.append('```')
                for code_line in code_text.split('\n'):
                    lines.append(code_line)
                lines.append('```')
                lines.append('')
            return

        # 表格
        if name == 'table':
            self._convert_table(child, lines)
            return

        # 处理图片容器（微信常见：图片被包在 <p> 里）
        imgs = child.find_all('img', recursive=False)
        if imgs:
            for img in imgs:
                src = img.get('data-src') or img.get('src', '')
                if src:
                    lines.append('')
                    lines.append(f'![图片]({src})')
                    lines.append('')
                    # 标记已处理，避免 _render_inline 重复渲染
                    img['data-src'] = ''
                    img['src'] = ''
            return

        # 通用块级标签（p, div, section 等）：递归混合处理
        block_children = self._has_block_children(child)
        if block_children:
            # 包含块级子元素 → 递归展开
            lines.append('')
            self._convert_block(child, lines)
            lines.append('')
        else:
            # 纯行内内容 → 渲染为单段
            text = self._render_inline(child)
            if text:
                lines.append('')
                lines.append(text)
                lines.append('')

    def _has_block_children(self, element) -> bool:
        """检查元素是否直接包含块级子元素"""
        for child in element.children:
            if child.name and child.name.lower() in self.BLOCK_TAGS:
                return True
        return False

    def _render_inline(self, element) -> str:
        """将行内 HTML 转为 Markdown 行内格式，保留样式"""
        parts = []
        for child in element.children:
            if child.name is None:
                text = str(child)
                parts.append(text)
            elif child.name in ('br',):
                parts.append('\n')
            elif child.name == 'img':
                src = child.get('data-src') or child.get('src', '')
                if src:
                    parts.append(f'![图片]({src})')
            elif child.name in ('strong', 'b'):
                inner = self._render_inline(child)
                parts.append(f'**{inner}**')
            elif child.name in ('em', 'i'):
                inner = self._render_inline(child)
                parts.append(f'*{inner}*')
            elif child.name in ('u', 'ins'):
                inner = self._render_inline(child)
                parts.append(f'<u>{inner}</u>')  # Markdown 没有下划线标准语法
            elif child.name in ('del', 's', 'strike'):
                inner = self._render_inline(child)
                parts.append(f'~~{inner}~~')
            elif child.name == 'code':
                code_text = child.get_text()
                parts.append(f'`{code_text}`')
            elif child.name == 'a':
                href = child.get('href', '')
                inner = self._render_inline(child)
                if href and inner:
                    parts.append(f'[{inner}]({href})')
                elif inner:
                    parts.append(inner)
            elif child.name in ('sub',):
                inner = self._render_inline(child)
                parts.append(f'~{inner}~')
            elif child.name in ('sup',):
                inner = self._render_inline(child)
                parts.append(f'^{inner}^')
            elif child.name in ('span', 'label', 'font', 'small', 'mark', 'abbr'):
                # 行内容器：递归渲染内部
                inner = self._render_inline(child)
                parts.append(inner)
            elif child.name in self.BLOCK_TAGS:
                # 行内出现块级元素 → 还原为换行符 + 递归
                parts.append('\n\n')
                # 无法在这里产生多行，插入原始文本
                parts.append(child.get_text())
            else:
                # 未知元素：取其文本
                parts.append(self._render_inline(child))

        result = ''.join(parts)
        # 压缩多余空白，但保留单个换行符
        result = re.sub(r' +', ' ', result)
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()

    def _convert_table(self, table_element, lines: list):
        """将 HTML 表格转为 Markdown 表格"""
        rows = table_element.find_all('tr')
        if not rows:
            return

        lines.append('')
        for ri, row in enumerate(rows):
            cells = row.find_all(['td', 'th'])
            cell_texts = [self._render_inline(c).replace('\n', ' ').replace('|', '\\|') for c in cells]
            lines.append('| ' + ' | '.join(cell_texts) + ' |')
            # 表头分隔线
            if ri == 0:
                lines.append('| ' + ' | '.join(['---'] * len(cells)) + ' |')
        lines.append('')

    def _download_images(self, soup: BeautifulSoup, article_title: str) -> int:
        """下载文章中所有图片到本地，替换 src 为相对路径（绕过微信防盗链）"""
        content_elem = soup.find(id='js_content') or soup.find(class_='rich_media_content')
        if not content_elem:
            return 0

        imgs = content_elem.find_all('img')
        if not imgs:
            return 0

        # 创建图片目录
        safe_title = sanitize_filename(article_title) if article_title else "wechat_article"
        img_dir = os.path.join(OUTPUT_DIR, f"{safe_title}_images")
        os.makedirs(img_dir, exist_ok=True)

        downloaded = 0
        for i, img in enumerate(imgs):
            # 微信图片的真实URL通常在 data-src 属性中
            src = img.get('data-src') or img.get('src', '')
            if not src or not src.startswith('http'):
                continue

            try:
                logger.detail(f"下载图片 {i+1}/{len(imgs)}: {src[:80]}...")
                resp = self.session.get(src, timeout=30, stream=True)
                if resp.status_code != 200:
                    logger.warn(f"图片下载失败: HTTP {resp.status_code}")
                    continue

                # 从URL或Content-Type推断扩展名
                ext = self._guess_image_ext(src, resp.headers.get('content-type', ''))
                img_filename = f"img_{i+1:03d}{ext}"
                img_path = os.path.join(img_dir, img_filename)

                with open(img_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                # 替换 img 标签的 src 为相对路径
                rel_path = f"./{safe_title}_images/{img_filename}"
                img['src'] = rel_path
                if img.get('data-src'):
                    img['data-src'] = rel_path

                downloaded += 1
                logger.detail(f"  ✓ 保存: {img_filename} ({os.path.getsize(img_path)/1024:.0f}KB)")

            except Exception as e:
                logger.warn(f"图片下载异常: {e}")
                continue

        return downloaded

    def _guess_image_ext(self, url: str, content_type: str) -> str:
        """根据URL或Content-Type推断图片扩展名"""
        # 先从URL推断
        url_lower = url.lower()
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp']:
            if ext in url_lower:
                return ext if ext != '.jpeg' else '.jpg'

        # 从Content-Type推断
        ct_map = {
            'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
            'image/webp': '.webp', 'image/svg+xml': '.svg', 'image/bmp': '.bmp',
        }
        return ct_map.get(content_type.split(';')[0].strip(), '.jpg')

    def _save_markdown(self, result: ArticleResult) -> str:
        """保存文章为 Markdown 文件"""
        safe_title = sanitize_filename(result.title) if result.title else "wechat_article"

        # 添加时间戳避免重名
        timestamp = ""
        if result.publish_time:
            ts_match = re.search(r'(\d{4})[-年](\d{1,2})[-月](\d{1,2})', result.publish_time)
            if ts_match:
                timestamp = f"{ts_match.group(1)}{int(ts_match.group(2)):02d}{int(ts_match.group(3)):02d}_"

        filename = f"{timestamp}{safe_title}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)

        # 构建完整的 Markdown 文件（含 frontmatter）
        parts = []
        parts.append(f"# {result.title}\n")
        if result.author:
            parts.append(f"**公众号**: {result.author}\n")
        if result.publish_time:
            parts.append(f"**发布时间**: {result.publish_time}\n")
        parts.append(f"**原文链接**: {result.source_url}\n")
        parts.append("\n---\n\n")
        parts.append(result.content_markdown)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(parts))

        return filepath
