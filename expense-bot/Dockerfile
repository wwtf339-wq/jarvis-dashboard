FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=Asia/Tashkent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
# База /data да туради — хостингда шу папкага доимий диск (volume) уланади
ENV DB_PATH=/data/expenses.db
RUN mkdir -p /data
CMD ["python", "bot.py"]
