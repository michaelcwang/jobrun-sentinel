FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

RUN addgroup --system sentinel && adduser --system --ingroup sentinel sentinel

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY alembic ./alembic
COPY alembic.ini .
COPY app ./app

RUN chown -R sentinel:sentinel /app
USER sentinel

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "app.container_boot"]
