#!/bin/bash
set -e

echo "=== Starting PTS Ranking Reporter ==="
echo "PORT=${PORT:-8080}"
echo "PYTHONPATH=${PYTHONPATH}"
echo "Working directory: $(pwd)"
echo "Files in /app/src: $(ls /app/src/ 2>/dev/null | head -5)"
echo "Files in /app/dashboard: $(ls /app/dashboard/ 2>/dev/null | head -5)"

cd /app/dashboard

echo "Testing imports..."
python3 -c "from app import app; print('Import OK')" || {
    echo "IMPORT FAILED!"
    python3 -c "import traceback; exec(open('/dev/stdin').read())" <<'PYEOF'
import sys, traceback
try:
    from app import app
except Exception as e:
    traceback.print_exc()
    sys.exit(1)
PYEOF
}

echo "Starting gunicorn on port ${PORT:-8080}..."
exec gunicorn app:app \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 2 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile -
