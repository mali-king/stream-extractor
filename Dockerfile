# Use the official Microsoft Playwright image as base 
# This incredibly helpful baseline image contains every single complicated Linux dependency required to run a virtual browser.
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Define the working directory inside the container
WORKDIR /app

# Copy Python requirements first to cache dependency installations
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium (Playwright will utilize this browser instance in headless mode)
RUN playwright install chromium

# Copy over the rest of the application code
COPY . .

# Gunicorn needs to know what port to bind to. Render dynamically assigns a port via the $PORT env variable.
# We set the number of workers to 2 to handle multiple extractions securely.
# Critically: We set the timeout to 120 seconds. Standard Gunicorn kills tasks taking longer than 30s, 
# but our anti-bot extraction takes 15-25 seconds and we don't want it to abruptly drop!
CMD gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120
