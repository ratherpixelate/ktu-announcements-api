# Use an official, lightweight Python image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its system dependencies
RUN playwright install chromium
RUN playwright install-deps

# Copy the rest of your code into the container
COPY . .

# Expose the port FastAPI uses
EXPOSE 8000

# Command to run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]