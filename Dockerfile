FROM python:3.11-slim

WORKDIR /app

# Ensure we have the latest pip
RUN python -m pip install --upgrade pip

COPY requirements.txt .

# Use python -m pip to ensure it installs to the correct site-packages
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# This is the most reliable way to start Uvicorn inside a container
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]