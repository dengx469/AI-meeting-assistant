# Dockerfile
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制程序文件
COPY . .

# 设置环境变量
ENV PORT=8080

# 暴露端口
EXPOSE 8080

# 启动 Flask 服务（Cloud Run 用 gunicorn）

#CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "--threads", "8", "--timeout", "120", "--max-requests", "200", "--max-requests-jitter", "50", "app:app"]
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "--threads", "1", "--timeout", "120", "--max-requests", "200", "--max-requests-jitter", "50", "app_safe:app"]

