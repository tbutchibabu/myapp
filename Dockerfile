# Start from the official Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy all other source code into /app
COPY . .

# Tell GCP to expect traffic on port 8080
ENV PORT 8080

# Launch your Flask app via Gunicorn (adjust 'app:app' if your app entrypoint differs)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
