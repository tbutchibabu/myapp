# ─── Use the official Python 3.11 slim image ─────────────────────────────
FROM python:3.11-slim

# Set a working directory
WORKDIR /app

# Copy requirements.txt (if you have one), otherwise install dependencies inline.
# If you don’t already have a requirements.txt, create one next to app.py with:
#   Flask
#   google-cloud-storage
#   pandas
#   # (plus any others your app needs, e.g. xml, etc.)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY . /app

# Tell Cloud Run to listen on port 8080 (this is also set in app.py via $PORT)
ENV PORT=8080

# Expose port 8080
EXPOSE 8080

# Run the Flask app (Gunicorn is recommended for production)
# Here we use Gunicorn with 4 workers. Adjust as needed.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app", "--workers=4", "--threads=8"]
