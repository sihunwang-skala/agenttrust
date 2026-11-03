FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV AGENTTRUST_DATABASE_URL=sqlite:////data/agenttrust.db AGENTTRUST_KEY_DIR=/data/keys
CMD ["uvicorn", "app.main:default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
