FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

RUN useradd --create-home bot && mkdir -p /data && chown bot /data
USER bot
ENV DATABASE_PATH=/data/habits.db

CMD ["python", "-m", "habit_bot.main"]
