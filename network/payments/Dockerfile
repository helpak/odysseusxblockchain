FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 9100
# --proxy-headers : derrière le reverse proxy HTTPS (Caddy/nginx).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9100", "--proxy-headers", "--forwarded-allow-ips", "*"]
