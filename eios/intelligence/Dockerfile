FROM python:3.12-slim
WORKDIR /app
COPY intelligence/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY schemas/ ./schemas/
COPY telemetry/ ./telemetry/
COPY security/ ./security/
COPY db/ ./db/
COPY intelligence/ ./intelligence/
ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
RUN mkdir -p /models
CMD ["python", "-m", "intelligence.main"]
