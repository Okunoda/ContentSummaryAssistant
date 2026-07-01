#!/bin/bash
# VideoCraw 启动脚本
# 自动处理代理环境变量冲突问题

set -e

cd "$(dirname "$0")"

echo "🎬 VideoCraw 启动中..."

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "📝 首次运行，从 .env.example 创建 .env 配置文件..."
    cp .env.example .env
    echo "⚠️  请编辑 .env 文件填入 LLM_API_KEY 后再启动"
    echo "   或者直接启动后在界面中输入 demo 体验演示模式"
fi

# 使用虚拟环境
if [ -f ".venv/bin/python3" ]; then
    PYTHON=".venv/bin/python3"
    PIP=".venv/bin/pip"
else
    PYTHON="python3"
    PIP="pip"
fi

# 清除可能冲突的 SOCKS 代理（httpx 不支持）
if [ -n "$ALL_PROXY" ] && echo "$ALL_PROXY" | grep -q "socks"; then
    echo "🔧 检测到 SOCKS 代理冲突，已自动处理"
    unset ALL_PROXY
fi

# 安装缺失依赖
$PYTHON -c "import gradio" 2>/dev/null || {
    echo "📦 安装依赖..."
    $PIP install -r requirements.txt websocket-client trafilatura html2text
}

echo "🚀 启动 Gradio 面板..."
echo "   访问: http://localhost:7860"
echo "   演示: 输入 demo 或点击演示按钮"
echo ""

$PYTHON app.py
