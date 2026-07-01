"""URL 识别和工具函数"""
import re
import os
from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    """
    根据 URL 识别平台类型
    返回: 'bilibili' | 'xiaohongshu' | 'wechat' | 'unknown'
    """
    url = url.strip()

    # B站: bilibili.com/video/BV... 或 b23.tv/...
    if re.search(r'bilibili\.com/video/|b23\.tv|bilibili\.com/bangumi/', url):
        return 'bilibili'

    # 小红书: xiaohongshu.com/discovery/item/... 或 xhslink.com/...
    if re.search(r'xiaohongshu\.com|xhslink\.com|rednote\.com', url):
        return 'xiaohongshu'

    # 微信公众号: mp.weixin.qq.com/s/...
    if re.search(r'mp\.weixin\.qq\.com', url):
        return 'wechat'

    # 其他 HTTP(S) 链接 → 通用博客文章
    if re.match(r'https?://', url):
        return 'blog'

    return 'unknown'


def extract_bilibili_bvid(url: str):
    """从B站链接中提取 BV 号"""
    # BV号格式: BV1xx411c7mD
    match = re.search(r'(BV[a-zA-Z0-9]{10})', url)
    if match:
        return match.group(1)

    # b23.tv 短链接 - 需要跟进重定向
    if 'b23.tv' in url:
        return None  # 需要先解析短链接

    return None


def extract_xiaohongshu_note_id(url: str):
    """从小红书链接中提取笔记 ID"""
    # 格式: xiaohongshu.com/discovery/item/64a1b2c3d4e5f6g7h8i9
    match = re.search(r'/item/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)

    # 格式: xhslink.com/xxxxx
    if 'xhslink.com' in url:
        return None  # 需要先解析短链接

    return None


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除非法字符"""
    # 替换文件系统不允许或不便使用的字符
    illegal_chars = r'[<>:"/\\|?*\r\n\t\s]'
    sanitized = re.sub(illegal_chars, '_', filename)
    # 合并连续下划线
    sanitized = re.sub(r'_+', '_', sanitized)
    # 限制长度
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized.strip('_')


def is_video_url(url: str) -> bool:
    """判断是否为视频链接"""
    platform = detect_platform(url)
    return platform in ('bilibili', 'xiaohongshu')


def is_article_url(url: str) -> bool:
    """判断是否为文章链接"""
    platform = detect_platform(url)
    return platform in ('wechat', 'blog')
