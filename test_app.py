#!/usr/bin/env python3
"""VideoCraw 测试脚本 - 验证所有模块功能"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from utils.helpers import (
    detect_platform, extract_bilibili_bvid, extract_xiaohongshu_note_id,
    sanitize_filename, is_video_url, is_article_url,
)
from crawlers.base import VideoResult, ArticleResult
from crawlers import get_crawler
from processor.summarizer import Summarizer


class TestURLDetection(unittest.TestCase):
    """URL 检测测试"""

    def test_bilibili(self):
        self.assertEqual(detect_platform("https://www.bilibili.com/video/BV1xx411c7mD"), "bilibili")
        self.assertEqual(detect_platform("https://b23.tv/abc123"), "bilibili")
        self.assertEqual(detect_platform("https://www.bilibili.com/bangumi/play/ep123"), "bilibili")

    def test_xiaohongshu(self):
        self.assertEqual(detect_platform("https://www.xiaohongshu.com/discovery/item/abc123"), "xiaohongshu")
        self.assertEqual(detect_platform("https://xhslink.com/abc123"), "xiaohongshu")

    def test_wechat(self):
        self.assertEqual(detect_platform("https://mp.weixin.qq.com/s/test123"), "wechat")
        self.assertEqual(detect_platform("https://mp.weixin.qq.com/s/abc-def-ghi"), "wechat")

    def test_unknown(self):
        self.assertEqual(detect_platform("https://google.com"), "unknown")
        self.assertEqual(detect_platform("https://youtube.com/watch?v=abc"), "unknown")


class TestIDExtraction(unittest.TestCase):
    """ID 提取测试"""

    def test_bilibili_bvid(self):
        self.assertEqual(extract_bilibili_bvid("https://www.bilibili.com/video/BV1xx411c7mD"), "BV1xx411c7mD")
        self.assertEqual(extract_bilibili_bvid("https://www.bilibili.com/video/BV1xx411c7mD?spm=123"), "BV1xx411c7mD")
        self.assertIsNone(extract_bilibili_bvid("https://b23.tv/abc123"))

    def test_xiaohongshu_note_id(self):
        self.assertEqual(
            extract_xiaohongshu_note_id("https://www.xiaohongshu.com/discovery/item/64a1b2c3d4e5f6"),
            "64a1b2c3d4e5f6"
        )
        self.assertIsNone(extract_xiaohongshu_note_id("https://xhslink.com/abc"))


class TestHelpers(unittest.TestCase):
    """工具函数测试"""

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename('test:file?name'), 'test_file_name')
        self.assertEqual(sanitize_filename('normal_file'), 'normal_file')
        self.assertEqual(sanitize_filename('a' * 300), 'a' * 200)

    def test_is_video_url(self):
        self.assertTrue(is_video_url("https://www.bilibili.com/video/BV123"))
        self.assertTrue(is_video_url("https://www.xiaohongshu.com/discovery/item/123"))
        self.assertFalse(is_video_url("https://mp.weixin.qq.com/s/test"))

    def test_is_article_url(self):
        self.assertTrue(is_article_url("https://mp.weixin.qq.com/s/test"))
        self.assertFalse(is_article_url("https://www.bilibili.com/video/BV123"))


class TestDataStructures(unittest.TestCase):
    """数据结构测试"""

    def test_video_result(self):
        r = VideoResult(platform="bilibili")
        self.assertFalse(r.success)
        self.assertEqual(r.platform, "bilibili")

    def test_article_result(self):
        r = ArticleResult(platform="wechat", title="测试文章")
        self.assertEqual(r.title, "测试文章")
        self.assertFalse(r.success)

    def test_result_defaults(self):
        r = VideoResult(platform="xiaohongshu")
        self.assertEqual(r.title, "")
        self.assertEqual(r.description, "")
        self.assertEqual(r.error, "")


class TestCrawlerRouting(unittest.TestCase):
    """爬虫路由测试"""

    def test_bilibili_route(self):
        c = get_crawler("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(c.platform, "bilibili")

    def test_xiaohongshu_route(self):
        c = get_crawler("https://www.xiaohongshu.com/discovery/item/abc123")
        self.assertEqual(c.platform, "xiaohongshu")

    def test_wechat_route(self):
        c = get_crawler("https://mp.weixin.qq.com/s/test123")
        self.assertEqual(c.platform, "wechat")

    def test_invalid_route(self):
        with self.assertRaises(ValueError):
            get_crawler("https://unknown.com/test")


class TestSummarizer(unittest.TestCase):
    """总结器测试"""

    def test_summarizer(self):
        # 测试总结器（可能已配置 API Key 或未配置）
        s = Summarizer()
        result = s.summarize_video("测试视频", "测试描述", "测试内容")
        # 未配置时返回提示，已配置时返回实际总结
        self.assertTrue(
            "未配置" in result or len(result) > 20,
            f"总结器返回异常: {result[:100]}"
        )


def run_tests():
    """运行所有测试并打印结果"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestURLDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestIDExtraction))
    suite.addTests(loader.loadTestsFromTestCase(TestHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestDataStructures))
    suite.addTests(loader.loadTestsFromTestCase(TestCrawlerRouting))
    suite.addTests(loader.loadTestsFromTestCase(TestSummarizer))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print(f"测试总数: {result.testsRun}")
    print(f"通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")

    if result.wasSuccessful():
        print("✅ 所有测试通过!")
    else:
        print("❌ 存在失败的测试")
        for test, traceback in result.failures + result.errors:
            print(f"\n--- {test} ---")
            print(traceback)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
