# ============================================
# StressForge Locust — Multi-Arch Dockerfile
# ============================================
FROM python:3.12-slim

LABEL maintainer="stressforge"
LABEL description="StressForge Locust Load Generator"

WORKDIR /locust

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY locustfile.py .

EXPOSE 8089

CMD ["locust", "-f", "locustfile.py", "--host", "http://api:8000", "--web-host", "0.0.0.0"]
