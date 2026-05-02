FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system build dependencies required for dlib/opencv and other native libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    git \
    wget \
    unzip \
    python3-dev \
    libboost-all-dev \
    libatlas-base-dev \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    libglib2.0-0 \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python build tools before installing requirements to ensure wheel builds work
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . /app

ENV PORT=10000

EXPOSE 10000

# Use gunicorn to run the flask app (matches Procfile)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2"]
