FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Données (SQLite) et règlements d'époques — à monter en volumes.
RUN mkdir -p /app/data /app/settlements
VOLUME ["/app/data", "/app/settlements"]

EXPOSE 9000
# --proxy-headers : derrière le reverse proxy HTTPS (Caddy/nginx), les IP et
# schémas clients réels sont lus depuis X-Forwarded-*.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--proxy-headers", "--forwarded-allow-ips", "*"]
