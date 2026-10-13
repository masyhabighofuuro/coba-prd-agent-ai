FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/

ENV FLASK_HOST=0.0.0.0
ENV DB_PATH=/app/data/app.db

EXPOSE 5000

CMD ["python", "app.py"]
