FROM python:3.12-slim

WORKDIR /app

# Install system deps if needed (none for now, but keep this layer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a directory for the SQLite database
RUN mkdir -p /app/instance

# Expose the Flask port
EXPOSE 5000

# Environment defaults
ENV PORT=5000
ENV FLASK_APP=run.py

# Run with Flask dev server (bind to 0.0.0.0 for Docker)
CMD ["sh", "-c", "flask run --host=0.0.0.0 --port=${PORT}"]
