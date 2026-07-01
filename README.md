# 🎬 VideoCraw - 多平台内容获取与 AI 总结工具

可视化面板，输入链接即可自动获取 B站视频、小红书视频、微信公众号文章的内容，并调用 LLM 自动生成总结。

## ✨ 功能

| 平台 | 功能 | 实现方式 |
|------|------|----------|
| 📺 **B站视频** | 提取字幕/下载音频 → 语音转文字 → AI总结 | bilibili-api + yt-dlp + Whisper |
| 📕 **小红书视频** | 下载无水印视频 → 语音转文字 → AI总结 | 页面解析 + Whisper |
| 📰 **微信公众号** | 文章爬取 → 转 Markdown → AI总结 | requests + BeautifulSoup + WeSpy 降级 |

## 🚀 快速开始

### 1. 安装依赖

```bash
# Python 3.10+ 推荐
pip install -r requirements.txt

# 需要安装 ffmpeg（音频处理）
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows - 下载 https://ffmpeg.org/download.html
```

### 2. 配置 LLM API Key

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

### 3. 启动

```bash
# 如果在国内，设置代理环境变量（可选）
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897

python app.py
```

浏览器打开 `http://localhost:7860`，粘贴链接即可使用。

**💡 无需任何配置即可体验！** 输入 `demo` 或点击「🎮 演示」按钮查看模拟的完整处理流程。

### 4. 运行测试

```bash
python test_app.py
```

## 📋 支持的链接格式

```
# B站视频
https://www.bilibili.com/video/BV1xx411c7mD
https://b23.tv/xxxxx

# 小红书视频
https://www.xiaohongshu.com/discovery/item/64a1b2c3d4e5f6g7h8i9
https://xhslink.com/xxxxx

# 微信公众号文章
https://mp.weixin.qq.com/s/xxxxxxxxxxxxx
```

## 🏗️ 项目结构

```
videoCraw/
├── app.py                    # Gradio 可视化面板（主入口）
├── config.py                 # 全局配置（自动检测 ffmpeg 等）
├── test_app.py               # 17 个单元测试
├── requirements.txt          # 依赖清单
├── .env.example              # 配置模板
├── README.md                 # 项目文档
├── crawlers/
│   ├── base.py               # 爬虫基类 + VideoResult/ArticleResult 数据结构
│   ├── bilibili.py           # B站视频爬取（bilibili-api + yt-dlp 双引擎）
│   ├── xiaohongshu.py        # 小红书视频爬取（页面解析 + 无水印下载）
│   └── wechat.py             # 微信公众号文章爬取（requests + WeSpy 降级）
├── processor/
│   ├── transcriber.py        # 语音转文字（faster-whisper）
│   └── summarizer.py         # LLM 总结（OpenAI 兼容 API）
└── utils/
    └── helpers.py            # URL识别、BV号提取、工具函数
```

## 🔧 配置说明

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `LLM_API_KEY` | LLM API 密钥（必须） | - |
| `LLM_API_BASE` | LLM API 地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | LLM 模型名称 | `gpt-4o-mini` |
| `WHISPER_MODEL` | Whisper 模型大小 | `base` |
| `WHISPER_DEVICE` | 运行设备 | `cpu` |
| `FFMPEG_PATH` | ffmpeg 可执行文件路径 | 自动检测 |
| `XHS_COOKIE` | 小红书 Cookie（可选） | - |
| `DOWNLOAD_DIR` | 下载目录 | `./downloads` |
| `OUTPUT_DIR` | 输出目录 | `./output` |

## 🛠️ 技术栈

- **Web UI**: Gradio 6
- **B站**: bilibili-api-python + yt-dlp（支持代理）
- **微信公众号**: requests + BeautifulSoup + WeSpy 降级
- **语音转文字**: faster-whisper（本地运行）
- **LLM**: OpenAI 兼容 API（支持 DeepSeek、通义千问等）
- **HTML解析**: BeautifulSoup4 + 自研 HTML→Markdown 转换器

## 📝 注意事项

### B站
- ⚠️ **海外 IP 限制**：B站对非中国大陆 IP 返回 HTTP 412
  - 解决：使用中国大陆代理，设置 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量
  - 或使用 VPN/回国加速器
- bilibili-api 获取信息通常不受限，yt-dlp 下载受地域限制

### 微信公众号
- ⚠️ **SPA 架构变更**：微信已迁移到 Vite/React SPA，部分文章需要 JS 渲染
  - 本项目已集成 WeSpy 作为降级方案（`pip install wespy`）
  - 如果直接请求失败，会自动降级使用 WeSpy 获取内容
- 微信风控严格，请合理控制请求频率

### 小红书
- 建议配置 Cookie（从浏览器登录后复制），提升成功率
- 短链接 `xhslink.com` 需要先解析为完整链接

### Whisper
- 首次使用会自动下载模型文件（base 模型约 140MB）
- 下载需要网络代理（模型托管在 HuggingFace）

## 📄 License

MIT
