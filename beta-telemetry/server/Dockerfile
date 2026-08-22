FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV BETA_DB_PATH=/data/beta.db \
    BETA_CAPTURES_DIR=/data/captures \
    BETA_SECRET_KEY_FILE=/data/flask-secret.key \
    BETA_LISTEN_PORT=8090

EXPOSE 8090
CMD ["gunicorn", "--bind", "0.0.0.0:8090", "--workers", "2", "--timeout", "60", "app:app"]
