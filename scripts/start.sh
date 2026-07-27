#!/bin/bash
# 一键启动 Enterprise RAG 前后端
# 用法: bash scripts/start.sh

set -e
cd "$(dirname "$0")/.."

echo "========================================"
echo "  Enterprise RAG — 启动中..."
echo "========================================"

# 检查 .env
if [ ! -f .env ]; then
    echo "[WARN] .env 文件不存在，使用 .env.example 作为模板"
    cp .env.example .env
    echo "请先编辑 .env 填入 API Key 后重新运行"
    exit 1
fi

# 检查 Qdrant
if ! curl -s http://localhost:6333 > /dev/null 2>&1; then
    echo "[INFO] Qdrant 未运行，启动 Docker..."
    docker compose up -d qdrant
    sleep 3
fi

# 激活虚拟环境
if [ -d .venv ]; then
    source .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate
elif [ -d venv ]; then
    source venv/Scripts/activate 2>/dev/null || source venv/bin/activate
fi

# 检查依赖
python -c "import fastapi" 2>/dev/null || {
    echo "[INFO] 安装依赖..."
    pip install -e . -q
    pip install streamlit -q
}

# 启动后端
echo "[INFO] 启动后端 API (port 8000)..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 2

# 检查后端
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "[OK] 后端启动成功: http://localhost:8000"
else
    echo "[WARN] 后端可能还在启动中..."
fi

# 启动前端
echo "[INFO] 启动前端 UI (port 8501)..."
streamlit run ui/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false &
FRONTEND_PID=$!
sleep 3

echo ""
echo "========================================"
echo "  启动完成！"
echo "  前端: http://localhost:8501"
echo "  后端: http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo "========================================"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号，同时杀前后端
cleanup() {
    echo "停止服务..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo "已停止"
}
trap cleanup EXIT

# 等待
wait
