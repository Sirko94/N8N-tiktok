FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl \
    nodejs \
    libass9 fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -U flask yt-dlp

WORKDIR /app
COPY app.py /app/app.py

EXPOSE 8580
CMD ["python", "/app/app.py"]
