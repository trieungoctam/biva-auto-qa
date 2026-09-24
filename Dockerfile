# auto-qa — image cho web UI (PLAN-UI-DEPLOY.md)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY autoqa ./autoqa
RUN pip install --no-cache-dir '.[ui]'

# bots/ copy vào image nhưng runtime mount đè (compose) — raw/ bị .dockerignore chặn
COPY bots ./bots
COPY config.yaml ./config.yaml

EXPOSE 8788
CMD ["uvicorn", "autoqa.webui:create_app", "--factory", "--host", "0.0.0.0", "--port", "8788"]
