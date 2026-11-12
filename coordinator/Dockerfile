# The mesh coordinator: ADK + Gemini over AG-UI, calling the three cloud agents over A2A.
# Build context: the repository root.
FROM python:3.14-slim
WORKDIR /app
COPY coordinator/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mesh ./mesh
COPY coordinator ./coordinator
ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "coordinator/main.py"]
