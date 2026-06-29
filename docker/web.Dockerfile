# Headless-browser image for Crucible visual QA: Playwright browsers are already in the base
# image (/ms-playwright); we add the matching Python package so the screenshot driver runs.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
RUN pip install --no-cache-dir playwright==1.47.0
WORKDIR /work
