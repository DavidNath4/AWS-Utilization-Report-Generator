#!/bin/bash
echo "============================================"
echo "  AWS Utilization Report Generator"
echo "============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 tidak ditemukan. Install Python 3.10+ dulu."
    exit 1
fi

# Install dependencies
echo "[1/3] Installing dependencies..."
pip3 install -r requirements.txt -q
echo ""

# Check .env
if [ ! -f .env ]; then
    echo "[ERROR] File .env tidak ditemukan!"
    echo "        Copy .env.example ke .env dan isi credentials."
    exit 1
fi

# Start server
echo "[2/3] Starting server..."
echo ""
echo "============================================"
echo "  Buka browser: http://localhost:8000"
echo "  Tekan Ctrl+C untuk stop"
echo "============================================"
echo ""

# Open browser (try multiple commands)
xdg-open http://localhost:8000 2>/dev/null || open http://localhost:8000 2>/dev/null &

# Run
python3 app.py
