FROM python:3.12-slim

WORKDIR /app

COPY orchestrator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas/ ./schemas/
COPY telemetry/ ./telemetry/
COPY intelligence/ ./intelligence/
COPY db/ ./db/
COPY security/ ./security/
COPY orchestrator/*.py ./

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
