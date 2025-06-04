# ─── Dockerfile ─────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy requirements, then install
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY . /app

# Tell Cloud Run to listen on 8080
ENV PORT=8080
EXPOSE 8080

# Use Gunicorn to serve app:app, 1 worker (adjust as needed)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app", "--workers=1", "--threads=8"]
