FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY dashboard/ ./dashboard/
COPY quant_research/ ./quant_research/
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Expose port
EXPOSE 8080

# Set PYTHONPATH so gunicorn can find src/ and quant_research/ modules
ENV PYTHONPATH=/app/src:/app/quant_research

# Run entrypoint script
CMD ["./entrypoint.sh"]
