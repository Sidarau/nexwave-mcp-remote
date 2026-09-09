FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV PORT=8080
EXPOSE 8080
CMD ["nexwave-mcp", "--http", "--host", "0.0.0.0", "--port", "8080"]
