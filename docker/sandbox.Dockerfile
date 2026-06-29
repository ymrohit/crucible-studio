# Persistent sandbox image for Crucible (§10): python:3.12-slim + pyright + hypothesis.
# Used by oracle/sandbox.py DockerSandbox when a Docker daemon is available.
FROM python:3.12-slim

# pyright needs node; install it plus the Python deps the gauntlet runs against.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g pyright@1.1.403 \
    && pip install --no-cache-dir hypothesis==6.135.26 \
    && apt-get purge -y npm \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
# Container is run with --network none --read-only --tmpfs /tmp by the sandbox launcher;
# each candidate is a fresh `python -` process with PYTHONHASHSEED=0.
USER nobody
CMD ["sleep", "infinity"]
