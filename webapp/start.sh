#!/bin/bash
cd /app/webapp
export PYTHONPATH=/app:$PYTHONPATH
export FLASK_APP=app.py
python -m flask run --host=0.0.0.0 --port=5056