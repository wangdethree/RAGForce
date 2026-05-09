"""BGE model inference service supporting both embedding and reranking."""

import os

from fastapi import FastAPI
from pydantic import BaseModel
import torch
from transformers import AutoModel, AutoTokenizer

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/bge-m3")
SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "8001"))

app = FastAPI(title="BGE Model Service")

tokenizer = None
model = None


@app.on_event("startup")
async def load_model():
    global tokenizer, model
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModel.from_pretrained(MODEL_PATH)
    model.eval()
    if torch.cuda.is_available():
        model = model.cuda()


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    inputs = tokenizer(request.texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        attention_mask = inputs["attention_mask"]
        hidden = outputs.last_hidden_state
        mask_expanded = attention_mask.unsqueeze(-1).expand(hidden.size()).float()
        sum_hidden = torch.sum(hidden * mask_expanded, 1)
        sum_mask = torch.clamp(mask_expanded.sum(1), min=1e-9)
        embeddings = sum_hidden / sum_mask
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

    return EmbedResponse(embeddings=embeddings.cpu().tolist())


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_k: int = 5


class RerankResult(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]


@app.post("/rerank", response_model=RerankResponse)
async def rerank(request: RerankRequest):
    pairs = [[request.query, doc] for doc in request.documents]
    inputs = tokenizer(pairs, padding=True, truncation=True, max_length=512, return_tensors="pt")
    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        scores = outputs.logits.squeeze(-1).cpu().tolist()
        if isinstance(scores, float):
            scores = [scores]

    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    results = [
        RerankResult(index=idx, score=score)
        for idx, score in ranked[: request.top_k]
    ]

    return RerankResponse(results=results)


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_PATH}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
