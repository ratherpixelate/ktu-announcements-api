# Use an official, lightweight Python image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV XDG_CACHE_HOME=/cache

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright OS dependencies for Firefox and fetch Camoufox browser into shared /cache
RUN mkdir -p /cache && \
    apt-get update && \
    playwright install-deps firefox && \
    python -m camoufox fetch && \
    chmod -R 777 /cache && \
    rm -rf /var/lib/apt/lists/*

ENV HOME=/tmp

# Copy the rest of your code into the container
COPY . .

# Expose the port FastAPI uses
EXPOSE 8000

# Command to run the server with fallback to port 8000 if PORT is not set by Render
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]