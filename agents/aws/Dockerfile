# The aws mesh agent and its MCP server (a stdio child), serving A2A on 9000.
# Build context: the repository root.
FROM python:3.14-slim
WORKDIR /app
COPY agents/aws/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mesh ./mesh
COPY agents/aws ./agents/aws
WORKDIR /app/agents/aws
ENV PORT=9000 HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 9000
CMD ["python3", "main.py"]
