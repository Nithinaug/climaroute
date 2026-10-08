# Image for the Fargate prepare task
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends osmium-tool curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-dev.txt requirements-prepare.txt ./
RUN pip install --no-cache-dir -r requirements-prepare.txt boto3 \
    && python -c "import duckdb; duckdb.sql('INSTALL httpfs')"

COPY shared/ shared/
COPY routing/ routing/
COPY shade/ shade/
COPY monsoon/ monsoon/
COPY prepare/ prepare/

CMD ["bash", "prepare/run.sh"]
