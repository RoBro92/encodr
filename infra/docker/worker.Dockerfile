FROM python:3.12-slim

WORKDIR /app

COPY apps/worker /app

CMD ["python", "-m", "app.main"]

