FROM python:3.12-slim-bookworm AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1001 appgroup && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appgroup . .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
