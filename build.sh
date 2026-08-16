#!/usr/bin/env bash
# Render build command: build the React frontend, then prepare Django static files.
set -e

echo ">>> Building frontend..."
cd frontend
npm install
npm run build
cd ..

echo ">>> Installing Python dependencies..."
pip install -r backend/requirements.txt

echo ">>> Collecting Django static files..."
python backend/leadtriage/manage.py collectstatic --noinput

echo ">>> Build complete."
