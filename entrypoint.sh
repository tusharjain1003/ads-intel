#!/usr/bin/env bash
set -e

echo "Waiting for Postgres..."
until pg_isready -h postgres -U postgres; do
  sleep 1
done
echo "Postgres is ready."

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting Uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
