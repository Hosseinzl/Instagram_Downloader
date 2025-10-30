# Use Playwright base image which includes browsers and required dependencies
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# Create app directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Expose a volume for tor instances if you plan to run them on the host
VOLUME ["/app/tor_instances"]

# Expose API port used by uvicorn
EXPOSE 4200
ENV PORT=4200

# Default command: run the FastAPI app with uvicorn on port 4200
# This will start `api_server:app` (make sure api_server.py is present)
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "4200", "--log-level", "info"]
