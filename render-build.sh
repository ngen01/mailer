#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Install Playwright browsers (without system deps as Render doesn't allow sudo)
playwright install chromium
