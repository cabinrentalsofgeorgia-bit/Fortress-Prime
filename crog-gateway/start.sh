#!/bin/bash
# Quick start script for CROG Gateway

set -e

echo "🏗️  CROG Gateway - Quick Start"
echo "================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file. Please edit it with your API keys."
    echo ""
    read -p "Press Enter to open .env in editor (or Ctrl+C to exit)..."
    ${EDITOR:-nano} .env
fi

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📚 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting CROG Gateway..."
echo ""
echo "   API Docs: http://localhost:8000/docs"
echo "   Health:   http://localhost:8000/health"
echo "   Config:   http://localhost:8000/config"
echo ""
echo "   Press Ctrl+C to stop"
echo ""

# Run the application
python app/main.py
