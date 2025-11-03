# Base image with Playwright + Python
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# Install tor
RUN apt-get update && apt-get install -y tor && apt-get clean

# Working directory
WORKDIR /app

# Copy dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app

# Prepare folders
RUN mkdir -p /app/tor_instances /app/tor_logs

# Expose ports (uvicorn + tor)
EXPOSE 4200 9050-9057

# Start script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
