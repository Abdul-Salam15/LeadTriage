#!/usr/bin/env bash
# Render build command: build the React frontend, then prepare Django static files.
set -e

echo ">>> Building frontend..."
cd frontend
npm install
npm run build
cd ..

echo ">>> Copying frontend build into Django static dir..."
rm -rf backend/leadtriage/frontend_static
cp -r frontend/dist backend/leadtriage/frontend_static

echo ">>> Installing Python dependencies..."
pip install -r backend/requirements.txt

echo ">>> Collecting Django static files..."
python backend/leadtriage/manage.py collectstatic --noinput

echo ">>> Build complete."
