FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    transformers>=4.36.0 \
    torch>=2.1.0 \
    fastapi>=0.109.0 \
    uvicorn[standard]>=0.27.0 \
    sentence-transformers>=2.3.0 \
    FlagEmbedding>=1.2.0

COPY serve.py .

EXPOSE 8001

CMD ["python", "serve.py"]
