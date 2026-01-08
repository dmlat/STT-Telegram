#!/bin/bash

# Скрипт для автоматического обновления и перезапуска бота на сервере
# Использование: ./update.sh

echo "🚀 Starting update process..."

# 1. Pull latest changes from git
echo "📥 Pulling latest changes from GitHub..."
git pull
if [ $? -ne 0 ]; then
    echo "❌ Git pull failed! Please check your connection or conflicts."
    exit 1
fi

# 2. Rebuild and restart containers
echo "🔄 Rebuilding and restarting containers..."
docker compose up --build -d
if [ $? -ne 0 ]; then
    echo "❌ Docker compose failed!"
    exit 1
fi

# 3. Clean up unused images (optional but good for server)
echo "🧹 Cleaning up old docker images..."
docker image prune -f

# 4. Check status
echo "✅ Bot updated and restarted successfully!"
echo "📊 Current status:"
docker ps

# 5. Show logs for a few seconds
echo "📜 Showing logs (Ctrl+C to exit logs, bot will keep running):"
timeout 10s docker compose logs -f bot

