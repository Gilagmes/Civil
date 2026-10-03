FROM python:3.12-slim
# шрифт нужен, чтобы на картинке-карте были подписи кириллицей
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_PATH=/data/civ.db PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 10000
CMD ["python", "bot.py"]
