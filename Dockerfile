FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY dashboard/ ./dashboard/

# Expose port
EXPOSE 8080

# Set PYTHONPATH so gunicorn can find src/ modules after cd dashboard
ENV PYTHONPATH=/app/src

# Run with gunicorn
CMD cd dashboard && gunicorn app:app --bind 0.0.0.0:8080 --workers 2 --timeout 120
