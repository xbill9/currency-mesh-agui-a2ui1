# The gcp mesh agent and its MCP server (a stdio child), serving A2A on 8080.
# Build context: the repository root.
FROM python:3.14-slim
WORKDIR /app
COPY agents/gcp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mesh ./mesh
COPY agents/gcp ./agents/gcp
WORKDIR /app/agents/gcp
ENV PORT=8080 HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "main.py"]
