FROM python:3.11-slim

WORKDIR /app
COPY aql_miner.py .

# All parameters are passed as arguments:
#   docker run … aql-miner --wallet 0x… --mode gpu --model-endpoint http://… --coordinator https://…
ENTRYPOINT ["python3", "aql_miner.py"]
