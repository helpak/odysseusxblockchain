FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Data (SQLite) and epoch settlements — mount these as volumes.
RUN mkdir -p /app/data /app/settlements
VOLUME ["/app/data", "/app/settlements"]

EXPOSE 9000
# --proxy-headers: behind the HTTPS reverse proxy (Caddy/nginx), the real client
# IPs and schemes are read from X-Forwarded-*.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--proxy-headers", "--forwarded-allow-ips", "*"]
