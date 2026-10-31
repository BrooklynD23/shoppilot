FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 APP_ENV=prod DATA_DIR=/tmp/shoppilot PORT=8000
WORKDIR /srv
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
RUN pip install uv==0.9.0 \
 && uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
 && pip install -r /tmp/req.txt && pip install --no-deps . \
 && useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
CMD ["sh","-c","exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
