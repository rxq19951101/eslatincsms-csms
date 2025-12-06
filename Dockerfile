#
# 本文件用于构建 csms 服务镜像：基于 Python 3.11-slim 运行 FastAPI 应用。
# 暴露端口 9000，并通过 uvicorn 启动。

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PORT=9000
EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]


