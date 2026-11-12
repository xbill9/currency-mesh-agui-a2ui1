# The azure mesh agent and its MCP server (a stdio child), serving A2A on 8080.
# Build context: the repository root.
FROM python:3.14-slim
WORKDIR /app
COPY agents/azure/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mesh ./mesh
COPY agents/azure ./agents/azure
WORKDIR /app/agents/azure
ENV PORT=8080 HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "main.py"]
