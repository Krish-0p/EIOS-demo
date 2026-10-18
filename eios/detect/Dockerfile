# Build context is the eios/ directory so the shared schemas package is available.
FROM python:3.12-slim

WORKDIR /app

COPY detect/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas/ ./schemas/
COPY detect/*.py ./

ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
