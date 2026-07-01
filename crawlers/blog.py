"""通用博客/文章爬取器

支持任意 URL 的文章内容提取：
1. trafilatura 自动识别正文（去除导航、广告、侧边栏）
2. 提取标题、作者、发布时间
3. HTML → Markdown 转换
4. 保存为 .md 文件
"""
import os
import re
import requests
from bs4 import BeautifulSoup
from crawlers.base import BaseCrawler, ArticleResult
from config import OUTPUT_DIR
from utils.helpers import sanitize_filename
from utils.progress import logger


class BlogCrawler(BaseCrawler):
    """通用博客/文章爬取器 — 支持任意网页文章"""

    def __init__(self):
        super().__init__()
        self.platform = "blog"
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def process(self, url: str) -> ArticleResult:
        result = ArticleResult(platform="blog", source_url=url)

        try:
            logger.step_begin("获取文章")
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                result.error = f"请求失败: HTTP {resp.status_code}"
                return result

            # 自动检测编码
            if resp.encoding and resp.encoding.lower() != 'utf-8':
                resp.encoding = resp.apparent_encoding
            if not resp.encoding:
                resp.encoding = 'utf-8'
            html = resp.text
            logger.detail(f"页面大小: {len(html)} bytes")

            # 1. trafilatura 提取正文（自动去噪）
            logger.detail("trafilatura 提取正文...")
            extracted = self._extract_with_trafilatura(html, url)
            if extracted:
                result.title = extracted.get("title", "")
                result.author = extracted.get("author", "")
                result.publish_time = extracted.get("date", "")
                result.content_markdown = extracted.get("markdown", "")
                result.content_html = extracted.get("html", "")

                # 如果正文太短，可能是提取失败
                if len(result.content_markdown) < 50:
                    logger.warn("trafilatura 提取内容过短，尝试 BS4 降级")
                    extracted = None
                else:
                    logger.detail(f"正文提取: {len(result.content_markdown)} 字符")

            # 2. BS4 降级
            if not extracted:
                logger.detail("BS4 降级提取...")
                bs_result = self._extract_with_bs4(html)
                result.title = bs_result.get("title", result.title)
                result.author = bs_result.get("author", result.author)
                result.publish_time = bs_result.get("date", result.publish_time)
                result.content_markdown = bs_result.get("markdown", "")
                logger.detail(f"正文提取: {len(result.content_markdown)} 字符")

            if not result.title:
                result.title = "未知标题"
            logger.detail(f"标题: {result.title}")
            if result.author:
                logger.detail(f"作者: {result.author}")
            if result.publish_time:
                logger.detail(f"时间: {result.publish_time}")

            # 3. 下载图片并替换为本地路径
            if result.content_markdown:
                logger.step_begin("下载文章图片")
                modified_md, img_count = self._download_images(
                    html, result.content_markdown, result.title
                )
                if img_count > 0:
                    result.content_markdown = modified_md
                    logger.detail(f"共下载 {img_count} 张图片")
                else:
                    logger.detail("文章无图片或下载失败")
                logger.step_end()

            # 4. 保存 Markdown
            if result.content_markdown:
                result.markdown_path = self._save_markdown(result)
                logger.detail(f"已保存: {os.path.basename(result.markdown_path)}")
                result.success = True
            else:
                result.error = "无法提取文章正文内容"

            logger.step_end()

        except requests.Timeout:
            result.error = "请求超时，请检查网络连接"
        except requests.RequestException as e:
            result.error = f"网络请求异常: {str(e)}"
        except Exception as e:
            result.error = f"文章处理异常: {str(e)}"

        return result

    # ---------- trafilatura 提取 ----------

    def _extract_with_trafilatura(self, html: str, url: str):
        """使用 trafilatura 提取文章内容（首选方案）"""
        try:
            import trafilatura
            # 提取正文 Markdown
            markdown = trafilatura.extract(
                html,
                output_format='markdown',
                include_links=True,
                include_images=True,
                include_tables=True,
                url=url,
            )
            if not markdown or len(markdown.strip()) < 50:
                return None

            # 提取元数据
            metadata = trafilatura.extract(
                html,
                output_format='markdown',
                include_links=True,
                include_images=True,
                include_tables=True,
                url=url,
                with_metadata=True,
            )

            # 提取标题
            title = ""
            soup = BeautifulSoup(html, 'lxml')
            # og:title
            og = soup.find('meta', property='og:title')
            if og and og.get('content'):
                title = og['content'].strip()
            if not title:
                t = soup.find('title')
                if t:
                    title = t.get_text(strip=True)
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)

            # 提取作者
            author = ""
            og_author = soup.find('meta', property='article:author')
            if og_author and og_author.get('content'):
                author = og_author['content'].strip()
            if not author:
                author_meta = soup.find('meta', attrs={'name': 'author'})
                if author_meta and author_meta.get('content'):
                    author = author_meta['content'].strip()

            # 提取日期
            date = ""
            for prop in ['article:published_time', 'article:modified_time']:
                meta = soup.find('meta', property=prop)
                if meta and meta.get('content'):
                    date = meta['content'].strip()[:19]
                    break

            return {
                "title": title,
                "author": author,
                "date": date,
                "markdown": markdown.strip(),
                "html": "",
            }
        except ImportError:
            logger.warn("trafilatura 未安装，使用 BS4 降级方案")
            return None
        except Exception as e:
            logger.warn(f"trafilatura 提取异常: {e}")
            return None

    # ---------- BS4 降级提取 ----------

    def _extract_with_bs4(self, html: str) -> dict:
        """BeautifulSoup 降级方案：提取标题和正文"""
        soup = BeautifulSoup(html, 'lxml')

        # 标题
        title = ""
        og = soup.find('meta', property='og:title')
        if og and og.get('content'):
            title = og['content'].strip()
        if not title:
            t = soup.find('title')
            if t:
                title = t.get_text(strip=True)
        if not title:
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(strip=True)

        # 作者
        author = ""
        for meta_name in ['author', 'article:author']:
            m = soup.find('meta', attrs={'name': meta_name})
            if not m:
                m = soup.find('meta', property=meta_name)
            if m and m.get('content'):
                author = m['content'].strip()
                break

        # 日期
        date = ""
        for prop in ['article:published_time', 'article:modified_time']:
            m = soup.find('meta', property=prop)
            if m and m.get('content'):
                date = m['content'].strip()[:19]
                break

        # 正文 — 优先 <article>，其次常见内容容器
        markdown = ""
        content_elem = (
            soup.find('article')
            or soup.find(class_=re.compile(r'(post|article|content|entry|body)', re.I))
            or soup.find(id=re.compile(r'(post|article|content|entry|body)', re.I))
        )
        if content_elem:
            # 简单 HTML → Markdown
            markdown = self._simple_html_to_md(content_elem)
        else:
            # 拿 body 全部文本
            body = soup.find('body')
            if body:
                markdown = body.get_text('\n', strip=True)

        return {
            "title": title,
            "author": author,
            "date": date,
            "markdown": markdown,
        }

    def _simple_html_to_md(self, element) -> str:
        """简单 HTML → Markdown（处理标题/段落/链接/图片/列表）"""
        try:
            import html2text
            h = html2text.HTML2Text()
            h.body_width = 0
            h.ignore_links = False
            h.ignore_images = False
            h.ignore_emphasis = False
            return h.handle(str(element)).strip()
        except ImportError:
            pass

        # 纯 BS4 降级
        lines = []
        for tag in element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'pre', 'blockquote', 'img', 'a']):
            text = tag.get_text(strip=True)
            if not text and tag.name != 'img':
                continue
            if tag.name.startswith('h') and len(tag.name) == 2:
                level = int(tag.name[1])
                lines.append('#' * level + ' ' + text)
            elif tag.name == 'li':
                lines.append('- ' + text)
            elif tag.name == 'blockquote':
                lines.append('> ' + text)
            elif tag.name == 'pre':
                lines.append('```\n' + tag.get_text() + '\n```')
            elif tag.name == 'img':
                src = tag.get('src', '')
                alt = tag.get('alt', '图片')
                if src:
                    lines.append(f'![{alt}]({src})')
            elif tag.name == 'a':
                href = tag.get('href', '')
                if href and text:
                    lines.append(f'[{text}]({href})')
            else:
                lines.append(text)
        return '\n\n'.join(lines)

    # ---------- 图片下载 ----------

    def _download_images(self, html: str, markdown: str, title: str) -> tuple:
        """下载文章中所有图片到本地，替换 Markdown 中的远程 URL

        从原始 HTML 中提取所有 <img> 的 src，
        下载后替换 Markdown 中对应的远程 URL 为本地相对路径。

        Returns:
            (modified_markdown, downloaded_count)
        """
        soup = BeautifulSoup(html, 'lxml')
        content_elem = soup.find('article') or soup.find('body')
        if not content_elem:
            return markdown, 0

        imgs = content_elem.find_all('img')
        if not imgs:
            return markdown, 0

        # 去重：同一 URL 只下载一次
        seen = set()
        img_urls = []
        for img in imgs:
            src = img.get('data-src') or img.get('data-lazy-src') or img.get('src') or ''
            # 处理相对路径
            if src and not src.startswith('http'):
                continue
            if src not in seen:
                seen.add(src)
                img_urls.append(src)

        if not img_urls:
            return markdown, 0

        # 创建图片目录
        safe_title = sanitize_filename(title) if title else "blog_article"
        img_dir = os.path.join(OUTPUT_DIR, f"{safe_title}_images")
        os.makedirs(img_dir, exist_ok=True)

        # 下载并构建替换映射
        replacements = {}  # remote_url → local_path
        for i, img_url in enumerate(img_urls, 1):
            try:
                logger.detail(f"下载图片 {i}/{len(img_urls)}: {img_url[:80]}...")
                resp = self.session.get(img_url, timeout=30, stream=True)
                if resp.status_code != 200:
                    logger.warn(f"  图片下载失败: HTTP {resp.status_code}")
                    continue

                ext = self._guess_image_ext(img_url, resp.headers.get('content-type', ''))
                filename = f"img_{i:03d}{ext}"
                filepath = os.path.join(img_dir, filename)

                with open(filepath, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                size_kb = os.path.getsize(filepath) / 1024
                rel_path = f"./{safe_title}_images/{filename}"
                replacements[img_url] = rel_path
                logger.detail(f"  ✓ {filename} ({size_kb:.0f}KB)")

            except Exception as e:
                logger.warn(f"  图片下载异常: {e}")
                continue

        # 替换 Markdown 中的远程 URL
        if replacements:
            modified = markdown
            for remote, local in replacements.items():
                # Markdown 图片语法: ![alt](url)
                modified = modified.replace(remote, local)
            return modified, len(replacements)

        return markdown, 0

    def _guess_image_ext(self, url: str, content_type: str) -> str:
        """根据 URL 或 Content-Type 推断图片扩展名"""
        url_lower = url.split('?')[0].lower()
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp']:
            if url_lower.endswith(ext):
                return '.jpg' if ext == '.jpeg' else ext

        ct_map = {
            'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
            'image/webp': '.webp', 'image/svg+xml': '.svg', 'image/bmp': '.bmp',
        }
        return ct_map.get(content_type.split(';')[0].strip(), '.jpg')

    # ---------- 保存 ----------

    def _save_markdown(self, result: ArticleResult) -> str:
        """保存文章为 Markdown 文件"""
        safe_title = sanitize_filename(result.title) if result.title else "blog_article"

        # 加时间戳避免重名
        ts = ""
        if result.publish_time:
            m = re.search(r'(\d{4})\D*(\d{1,2})\D*(\d{1,2})', result.publish_time)
            if m:
                ts = f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}_"

        filename = f"{ts}{safe_title}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)

        parts = [f"# {result.title}\n"]
        if result.author:
            parts.append(f"**作者**: {result.author}\n")
        if result.publish_time:
            parts.append(f"**发布时间**: {result.publish_time}\n")
        parts.append(f"**原文链接**: {result.source_url}\n")
        parts.append("\n---\n\n")
        parts.append(result.content_markdown)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(parts))

        return filepath
