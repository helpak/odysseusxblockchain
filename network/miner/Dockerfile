FROM python:3.11-slim

WORKDIR /app
COPY aql_miner.py .

# Tous les paramètres passent en arguments :
#   docker run … aql-miner --wallet 0x… --mode gpu --model-endpoint http://… --coordinator https://…
ENTRYPOINT ["python3", "aql_miner.py"]
