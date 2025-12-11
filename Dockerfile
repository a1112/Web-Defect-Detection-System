FROM python:3.11.8-slim


ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MYSQL_ROOT_PASSWORD=nercar

WORKDIR /app

# 安装 MySQL 服务和依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        mysql-server \
        build-essential \
        gcc \
        freetds-dev \
        unixodbc-dev \
        default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY configs configs
COPY link_project link_project
COPY run_server.bat run_server.bat
COPY run_server_dev.bat run_server_dev.bat
COPY pull_subprojects.bat pull_subprojects.bat

EXPOSE 8120 3306

# 初始化 MySQL 数据目录并启动 MySQL 服务
RUN mkdir -p /var/run/mysqld \
    && chown -R mysql:mysql /var/run/mysqld

# 启动脚本：先启动 MySQL，再启动 Python 服务
CMD service mysql start && \
    mysql -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${MYSQL_ROOT_PASSWORD}';" && \
    python app/server/main.py --config /app/configs/server.sample.json --host 0.0.0.0 --port 8120
