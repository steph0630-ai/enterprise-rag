FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖（python-magic 需要 libmagic）
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir . && pip install --no-cache-dir streamlit

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
