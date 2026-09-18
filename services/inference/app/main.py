from contextlib import asynccontextmanager, contextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, FiniteFloat
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.api_errors import upstream_exception_handler, http_exception_handler, validation_exception_handler, unhandled_exception_handler

from shared.service_auth import require_service_api_key
from shared.config import LoggingConfig
from shared.logging_config import configure_logging
from shared.tracing import install_trace_middleware
from shared.upstream import UpstreamServiceError, upstream_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(LoggingConfig())
    if not hasattr(app.state, "dense"):
        _load_components()
    yield
    _stop_components()


app = FastAPI(title="Brain Inference API", lifespan=lifespan)
install_trace_middleware(app, service_name="inference")


app.add_exception_handler(UpstreamServiceError, upstream_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    dense = getattr(app.state, "dense", None)
    if dense is None or not dense.ready:
        raise HTTPException(status_code=503, detail="inference is not ready")
    sparse = getattr(app.state, "sparse", None)
    rerank = getattr(app.state, "rerank", None)
    return {
        "status": "ready",
        "capabilities": {
            "dense": True,
            "sparse": sparse is not None and sparse.ready,
            "rerank": rerank is not None and rerank.ready,
        },
    }


class EmbeddingsRequest(BaseModel):
    input: str | list[str] = Field(min_length=1)
    model: str | None = None


class EmbeddingData(BaseModel):
    object: str = "embedding"
    embedding: list[FiniteFloat]
    index: int


class EmbeddingsResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str | None = None


class SparseEmbeddingData(BaseModel):
    object: str = "sparse_embedding"
    indices: list[int]
    values: list[FiniteFloat]
    index: int


class SparseEmbeddingsResponse(BaseModel):
    object: str = "list"
    data: list[SparseEmbeddingData]
    model: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_k: int = Field(default=5, ge=1)
    model: str | None = None


class RerankResult(BaseModel):
    index: int
    document: dict[str, str]
    relevance_score: FiniteFloat


class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str | None = None


def get_dense():
    dense = getattr(app.state, "dense", None)
    if dense is None or not dense.ready:
        raise HTTPException(status_code=503, detail="inference is not ready")
    return dense


def get_rerank():
    rerank = getattr(app.state, "rerank", None)
    if rerank is None:
        raise HTTPException(status_code=404, detail="rerank is not enabled")
    if not rerank.ready:
        raise HTTPException(status_code=503, detail="inference is not ready")
    return rerank


def get_sparse():
    sparse = getattr(app.state, "sparse", None)
    if sparse is None:
        raise HTTPException(status_code=404, detail="sparse embedding is not enabled")
    if not sparse.ready:
        raise HTTPException(status_code=503, detail="inference is not ready")
    return sparse


def _load_components() -> None:
    from services.inference.app.config import load_inference_config

    config = load_inference_config()
    if config.siliconflow is not None:
        from services.inference.providers.siliconflow import SiliconFlowInferenceClient

        remote = config.siliconflow
        client = SiliconFlowInferenceClient(
            base_url=remote.base_url, api_key=remote.api_key,
            dense_model=remote.dense_model, rerank_model=remote.rerank_model,
            dimensions=remote.dimensions, dense_timeout=remote.dense_timeout,
            rerank_timeout=remote.rerank_timeout, retry=remote.retry,
        )
        app.state.dense = client.dense
        app.state.sparse = None
        app.state.rerank = client.rerank
        return

    if config.volcengine is not None:
        from services.inference.providers.volcengine import VolcengineInferenceClient

        client = VolcengineInferenceClient(config.volcengine)
        app.state.dense = client.dense
        app.state.sparse = client.sparse
        app.state.rerank = client.rerank
        return

    if config.tei is not None:
        from services.inference.providers.tei import TeiInferenceClient

        client = TeiInferenceClient(config.tei)
        app.state.dense = client.dense
        app.state.sparse = client.sparse
        app.state.rerank = client.rerank
        return

    if config.vllm is not None:
        from services.inference.providers.vllm import VllmInferenceClient

        client = VllmInferenceClient(config.vllm)
        app.state.dense = client.dense
        app.state.sparse = client.sparse
        app.state.rerank = client.rerank
        return

    from services.inference.providers.embedded import BgeM3Sparse, CrossEncoderRerank, HuggingFaceDense
    dense = HuggingFaceDense(
        model_name=config.dense.model_path,
        batch_size=config.dense.batch_size,
        release_memory=config.dense.release_memory,
    )
    dense.start()
    app.state.dense = dense
    if config.sparse is not None:
        sparse = BgeM3Sparse(
            model_name=config.sparse.model_path,
            batch_size=config.sparse.batch_size,
            release_memory=config.sparse.release_memory,
        )
        sparse.start()
        app.state.sparse = sparse
    else:
        app.state.sparse = None
    if config.rerank is not None:
        rerank = CrossEncoderRerank(model_name=config.rerank.model_path)
        rerank.start()
        app.state.rerank = rerank
    else:
        app.state.rerank = None


@contextmanager
def _inference_errors():
    try:
        yield
    except (UpstreamServiceError, HTTPException):
        raise
    except Exception as exc:
        raise upstream_error("inference", exc) from exc


@app.get("/v1/models", dependencies=[Depends(require_service_api_key)])
def models():
    with _inference_errors():
        dense = get_dense()
        return {
            "dense": {**_model_spec(dense), "dimensions": dense.vector_size},
            "sparse": _model_spec(getattr(app.state, "sparse", None)),
            "rerank": _model_spec(getattr(app.state, "rerank", None)),
        }


def _model_spec(component):
    if component is None:
        return None
    return {"model_name": getattr(component, "model", None) or component.model_name}


@app.post("/v1/embeddings", response_model=EmbeddingsResponse, dependencies=[Depends(require_service_api_key)])
def dense_embeddings(request: EmbeddingsRequest):
    with _inference_errors():
        vectors = _encode(get_dense(), request.input)
        return EmbeddingsResponse(
            data=[EmbeddingData(embedding=vector, index=index) for index, vector in enumerate(vectors)],
            model=request.model,
        )


@app.post("/v1/sparse_embeddings", response_model=SparseEmbeddingsResponse, dependencies=[Depends(require_service_api_key)])
def sparse_embeddings(request: EmbeddingsRequest):
    with _inference_errors():
        vectors = _encode(get_sparse(), request.input)
        return SparseEmbeddingsResponse(
            data=[
                SparseEmbeddingData(
                    indices=[int(index) for index in vector.keys()],
                    values=[float(value) for value in vector.values()],
                    index=row_index,
                )
                for row_index, vector in enumerate(vectors)
            ],
            model=request.model,
        )


def _encode(component, value):
    if isinstance(value, str):
        return [component.embed_query(value)]
    return component.embed_documents(value)


@app.post("/v1/rerank", response_model=RerankResponse, dependencies=[Depends(require_service_api_key)])
def rerank(request: RerankRequest):
    with _inference_errors():
        items = [{"content": document, "_source_index": index} for index, document in enumerate(request.documents)]
        ranked = get_rerank().rerank(request.query, items, request.top_k)
        return RerankResponse(
            results=[
                RerankResult(
                    index=int(item.get("_source_index", index)),
                    document={"text": item["content"]},
                    relevance_score=float(item.get("_score", 0.0)),
                )
                for index, item in enumerate(ranked)
            ],
            model=request.model,
        )


def _stop_components() -> None:
    for name in ("dense", "sparse", "rerank"):
        component = getattr(app.state, name, None)
        if component is not None:
            component.stop()
