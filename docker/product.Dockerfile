# Image for Crucible "product mode": runs a generated FastAPI service + integration tests
# inside a container with --network none (loopback still works, so the app and its tests talk
# over 127.0.0.1; no external network). Deps are baked in because --network none blocks pip.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "fastapi==0.116.1" "uvicorn[standard]==0.35.0" "pydantic==2.11.7" "httpx==0.28.1"

WORKDIR /app
CMD ["sleep", "infinity"]
