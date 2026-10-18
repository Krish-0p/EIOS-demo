# Full test runtime: production model libraries plus the API's dependencies.
FROM eios-phase2-intelligence
COPY orchestrator/requirements.txt /tmp/api-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt
COPY orchestrator/*.py /app/
COPY orchestrator/ /app/orchestrator/
COPY ingest/ /app/ingest/
COPY detect/ /app/detect/
ENV PYTHONPATH=/app
