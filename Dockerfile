# Use Playwright base image which includes browsers and required dependencies
FROM mcr.microsoft.com/playwright/python:latest

# Create app directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY . /app

# Expose a volume for tor instances if you plan to run them on the host
VOLUME ["/app/tor_instances"]

# Default command: run the test runner main script (adjust if you use a different entrypoint)
CMD ["python", "main.py"]
