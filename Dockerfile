FROM python:3.9-slim

WORKDIR /app

# Install system dependencies (ffmpeg is required for audio processing/compression)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set PYTHONPATH to include the /app directory so 'src' module can be found
ENV PYTHONPATH=/app

CMD ["python", "src/bot.py"]
