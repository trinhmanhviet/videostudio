FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY videostudio ./videostudio
COPY static ./static
RUN pip install --no-cache-dir .
ENV VS_DATABASE=/data/jobs.sqlite3 VS_OUTPUT_DIR=/videos VS_WORKER_ENABLED=0
EXPOSE 8877
CMD ["uvicorn", "videostudio.api:app", "--host", "0.0.0.0", "--port", "8877"]
