from crawlers.base import BaseCrawler, VideoResult, ArticleResult
from crawlers.bilibili import BilibiliCrawler
from crawlers.xiaohongshu import XiaohongshuCrawler
from crawlers.wechat import WechatCrawler
from crawlers.blog import BlogCrawler
from utils.helpers import detect_platform


def get_crawler(url: str) -> BaseCrawler:
    """根据 URL 自动选择合适的爬虫"""
    platform = detect_platform(url)
    crawlers = {
        'bilibili': BilibiliCrawler,
        'xiaohongshu': XiaohongshuCrawler,
        'wechat': WechatCrawler,
        'blog': BlogCrawler,
    }
    crawler_cls = crawlers.get(platform)
    if crawler_cls:
        return crawler_cls()
    raise ValueError(f"不支持的链接类型: {url}\n"
                     f"支持的链接: B站视频、小红书视频、微信公众号文章、任意博客文章")
