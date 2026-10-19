FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    WEB_DIR=/app/web STORAGE_DIR=/data/files

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
COPY web/ /app/web/

# run as an unprivileged user; uploaded files live on a separate volume
RUN useradd --system --uid 10001 app && mkdir -p /data/files && chown -R app /data
USER app

EXPOSE 8000
# Trust X-Forwarded-For only from your reverse proxy: set FORWARDED_ALLOW_IPS to its address.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
