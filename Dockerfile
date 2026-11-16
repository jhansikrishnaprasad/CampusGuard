# CampusGuard hosted image (Linux). UNTESTED in the build environment (no Docker available) - see docs/DEPLOYMENT.md.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home campus && mkdir -p /data && chown -R campus:campus /data /app
USER campus
# Hosted mode: login required, secure cookies, data on the mounted volume (/data -> database, videos, evidence, models)
ENV CAMPUS_HOME=/data CAMPUS_REQUIRE_LOGIN=true COOKIE_SECURE=true
EXPOSE 8000
# ONE worker only: the analysis job manager lives inside the process. --proxy-headers because Caddy terminates HTTPS in front.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
