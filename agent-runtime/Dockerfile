FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir .
RUN mkdir -p /app/data/images /app/data/reports

EXPOSE 8100

CMD ["uvicorn", "car_agent.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
