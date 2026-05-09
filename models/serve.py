"""BGE 模型推理服务，支持 embedding 和 reranker 两种模式"""

import os

from fastapi import FastAPI
from pydantic import BaseModel
import torch
from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/bge-m3")
MODEL_TYPE = os.environ.get("MODEL_TYPE", "embedding")  # embedding 或 reranker
SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "8001"))

app = FastAPI(title=f"BGE {MODEL_TYPE.title()} Service")

tokenizer = None
model = None


@app.on_event("startup")
async def load_model():
    global tokenizer, model
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

    if MODEL_TYPE == "reranker":
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
    else:
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
    """BGE-M3 文本向量化"""
    if MODEL_TYPE != "embedding":
        return EmbedResponse(embeddings=[[0.0] for _ in request.texts])

    inputs = tokenizer(
        request.texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
    )
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
    """BGE-Reranker-v2-m3 Cross-Encoder 重排序"""
    if MODEL_TYPE != "reranker":
        return RerankResponse(results=[])

    pairs = [[request.query, doc] for doc in request.documents]
    inputs = tokenizer(
        pairs, padding=True, truncation=True, max_length=512, return_tensors="pt"
    )
    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        scores = outputs.logits.squeeze(-1).cpu().tolist()
        if isinstance(scores, float):
            scores = [scores]

    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    results = [
        RerankResult(index=idx, score=round(score, 6))
        for idx, score in ranked[: request.top_k]
    ]

    return RerankResponse(results=results)


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_PATH, "type": MODEL_TYPE}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
