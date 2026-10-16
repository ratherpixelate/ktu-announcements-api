# Use an official, lightweight Python image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright OS dependencies and fetch Camoufox browser
RUN playwright install-deps firefox
RUN python -m camoufox fetch

# Copy the rest of your code into the container
COPY . .

# Expose the port FastAPI uses
EXPOSE 8000

# Command to run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]