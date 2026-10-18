# Build context is the eios/ directory, so the shared schemas package can be
# copied in alongside the service.
FROM python:3.12-slim

WORKDIR /app

COPY ingest/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Generated from the substrate's own contract so decoding cannot drift from
# what checkout actually produces.
COPY ingest/proto/demo.proto ./proto/demo.proto
RUN python -m grpc_tools.protoc -I./proto --python_out=. ./proto/demo.proto

COPY schemas/ ./schemas/
COPY telemetry/ ./telemetry/
COPY security/ ./security/
COPY intelligence/ ./intelligence/
COPY db/ ./db/
COPY ingest/*.py ./

ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
