#!/bin/bash
# LearnMentor Offline — 一键启动脚本
set -e

echo "🧠 LearnMentor Offline — AI 驱动的自适应学习系统"
echo "================================================"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 需要安装 Docker。请访问 https://docs.docker.com/get-docker/"
    exit 1
fi

# Start DB + Redis
echo "📦 启动 PostgreSQL + Redis..."
docker compose up -d db redis
echo "   等待数据库就绪..."
sleep 5

# Backend setup
echo "🔧 配置后端..."
cd backend
if [ ! -d ".venv" ]; then
    echo "   创建 Python 虚拟环境..."
    uv sync 2>/dev/null || (python3 -m venv .venv && .venv/bin/pip install -e ".[dev]")
fi

echo "   应用数据库迁移..."
.venv/bin/alembic upgrade head 2>/dev/null

echo "🚀 启动后端 (http://localhost:8000)..."
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000 &
BACKEND_PID=$!
cd ..

# Frontend setup
echo "🎨 配置前端..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "   安装依赖..."
    npm install
fi

echo "🚀 启动前端 (http://localhost:3000)..."
npx next dev --port 3000 &
FRONTEND_PID=$!
cd ..

echo ""
echo "================================================"
echo "✅ LearnMentor 已启动！"
echo ""
echo "   前端: http://localhost:3000"
echo "   后端: http://localhost:8000"
echo "   API:  http://localhost:8000/docs"
echo ""
echo "💡 首次使用请在 Settings 页配置 LLM："
echo "   - 本地: 安装 Ollama (https://ollama.ai) 后添加模型"
echo "   - 云端: 添加 OpenAI / Anthropic API Key"
echo ""
echo "   按 Ctrl+C 停止所有服务"
echo "================================================"

# Wait and cleanup
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo '已停止所有服务'" EXIT
wait
