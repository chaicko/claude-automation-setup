FROM python:3.12-slim

# Install Node.js (for npx MCP servers) and system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY agent/ .

# Create data directory
RUN mkdir -p /data

# Entrypoint: run single cycle (systemd-style) or loop
ENTRYPOINT ["python", "claude-agent.py"]
CMD ["--loop"]
