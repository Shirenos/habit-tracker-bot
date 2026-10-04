FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

# Run as an unprivileged user; the SQLite database lives in the /data volume.
RUN useradd --system --create-home --uid 10001 bot \
    && mkdir -p /data \
    && chown bot:bot /data
USER bot

ENV DATABASE_PATH=/data/habits.db
VOLUME ["/data"]

CMD ["python", "-m", "habit_bot"]
