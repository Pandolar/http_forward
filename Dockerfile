# 使用官方Python 3.12镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建配置文件目录并设置权限
RUN mkdir -p /config && \
    touch /config/config.yml && \
    chmod 666 /config/config.yml && \
    ln -sf /config/config.yml /app/config.yml

# 暴露端口
EXPOSE 8190

# 运行命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8190"]