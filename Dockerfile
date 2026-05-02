FROM python:3.11-bullseye

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install only minimal system dependencies required to build dlib/face-recognition
# and numerical libraries. Keep the layer small and clean up apt lists.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       cmake \
       pkg-config \
       python3-dev \
       libatlas-base-dev \
       libopenblas-dev \
       liblapack-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install Python build tools and project dependencies (use --no-cache-dir)
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements.txt

# Copy application source after installing dependencies to leverage Docker layer cache
COPY . /app

ENV PORT=10000
EXPOSE 10000

# Run with gunicorn (matches Procfile). Adjust workers as needed for production.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2"]
