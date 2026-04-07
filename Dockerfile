FROM python:3.11-slim

LABEL maintainer="clinical-triage-team"
LABEL description="ClinicalTriage-Env — OpenEnv Emergency Department Triage Simulator"
LABEL org.opencontainers.image.title="ClinicalTriage-Env"
LABEL org.opencontainers.image.version="1.0.0"

# Hugging Face Spaces expects port 7860
ENV PORT=7860
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY env.py .
COPY server.py .
COPY inference.py .
COPY openenv.yaml .

# Copy dataset
COPY dataset/ ./dataset/

# Create non-root user for security best practices
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose the port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# Start the FastAPI server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
