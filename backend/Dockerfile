FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /srv/backend
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH="/srv/backend/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY app ./app
RUN useradd --create-home --uid 10001 app
USER app
CMD ["celery", "-A", "app.tasks.celery_app:celery_app", "worker", "-Q", "documents,maintenance", "--concurrency=2", "--loglevel=INFO"]
