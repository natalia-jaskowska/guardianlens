FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY app/ app/
COPY run.py .
COPY configs/ configs/

RUN pip install --no-cache-dir -e .

RUN mkdir -p outputs/screenshots

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:7860/healthz || exit 1

CMD ["python", "run.py", "--no-capture"]
