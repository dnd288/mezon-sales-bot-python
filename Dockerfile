FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Install base tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md ./
RUN mkdir -p mebot && touch mebot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf mebot

# Copy the full source and install
COPY mebot/ mebot/
RUN uv pip install --system --no-cache .

# Create config directory
RUN mkdir -p /root/.mebot

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["mebot"]
CMD ["status"]
