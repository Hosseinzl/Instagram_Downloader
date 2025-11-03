#!/bin/bash
set -e

echo "🚀 Starting Tor instances..."

tor -f /app/tor-configs/tor1.conf > /app/tor_logs/tor1.log 2>&1 &
tor -f /app/tor-configs/tor2.conf > /app/tor_logs/tor2.log 2>&1 &
tor -f /app/tor-configs/tor3.conf > /app/tor_logs/tor3.log 2>&1 &
tor -f /app/tor-configs/tor4.conf > /app/tor_logs/tor4.log 2>&1 &

# Wait a few seconds for tor to boot fully
echo "⏳ Waiting for Tor to initialize..."
sleep 8

# Verify that ports are open
netstat -tuln | grep 905 || echo "⚠️  Warning: Some Tor ports might not be open yet"

echo "✅ All Tor instances started!"
echo "🚀 Starting FastAPI (Uvicorn)..."

uvicorn api_server:app --host 0.0.0.0 --port 4200 --log-level info
