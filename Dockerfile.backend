FROM python:3.11-slim

LABEL maintainer="clinical-triage-team"
LABEL description="ClinicalTriage-Env — OpenEnv Emergency Department Triage Simulator"
LABEL org.opencontainers.image.title="ClinicalTriage-Env"
LABEL org.opencontainers.image.version="1.0.0"

ENV PORT=7860
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY env.py server.py inference.py openenv.yaml ./

# Copy dataset
COPY dataset/ ./dataset/

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
