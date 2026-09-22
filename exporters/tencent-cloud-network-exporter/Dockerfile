FROM python:3.13.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY exporter.py ./

USER 65534:65534

ENTRYPOINT ["python", "/app/exporter.py"]
CMD ["--config", "/etc/cloud-network-exporter/config.yml"]
