FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY app/ ./app/
COPY public/ ./public/

# 数据目录（挂载卷用）
RUN mkdir -p /app/data

EXPOSE 3000

CMD ["python", "app/app.py"]
