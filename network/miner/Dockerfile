FROM python:3.11-slim

WORKDIR /app
COPY odysseus_miner.py .

# Tous les paramètres passent en arguments :
#   docker run … odysseus-miner --wallet 0x… --mode gpu --coordinator http://…
ENTRYPOINT ["python3", "odysseus_miner.py"]
