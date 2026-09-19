from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl, field_validator
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.api_errors import upstream_exception_handler, http_exception_handler, validation_exception_handler, unhandled_exception_handler

from services.parser.service import ParserService
from services.parser.common.validation import InvalidDocumentError
from services.parser.app.config import load_parser_config
from services.parser.common.schema import FormulaBlock, TableBlock, TextBlock
from shared.contracts import ParseFileResponse, ParserBlock, ParserFormulaBlock, ParserTableBlock, ParserTextBlock
from shared.service_auth import require_service_api_key
from shared.config import LoggingConfig
from shared.logging_config import configure_logging
from shared.tracing import install_trace_middleware
from shared.upstream import UpstreamServiceError, upstream_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(LoggingConfig())
    if not hasattr(app.state, "parser_service"):
        parser_service = ParserService(load_parser_config())
        parser_service.start()
        app.state.parser_service = parser_service
    yield
    parser_service = getattr(app.state, "parser_service", None)
    if parser_service is not None:
        parser_service.stop()


app = FastAPI(title="Brain Parser API", lifespan=lifespan)
install_trace_middleware(app, service_name="parser")

app.add_exception_handler(UpstreamServiceError, upstream_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


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
    parser_service = getattr(app.state, "parser_service", None)
    if parser_service is None or not parser_service.ready:
        raise HTTPException(status_code=503, detail="parser is not ready")
    return {"status": "ready"}


class ParseFileRequest(BaseModel):
    presigned_url: str
    filename: str = Field(min_length=1)

    @field_validator("presigned_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        HttpUrl(value)
        return value


def get_parser_service() -> ParserService:
    if not hasattr(app.state, "parser_service"):
        parser_service = ParserService(load_parser_config())
        parser_service.start()
        app.state.parser_service = parser_service
    return app.state.parser_service


@app.post("/v1/parse/file", response_model=ParseFileResponse, response_model_exclude_none=True, dependencies=[Depends(require_service_api_key)])
def parse_file(req: ParseFileRequest):
    try:
        blocks, file_size = get_parser_service().parse_url(req.presigned_url, filename=req.filename)
        return ParseFileResponse(blocks=[_block_response(block) for block in blocks], file_size=file_size)
    except (UpstreamServiceError, HTTPException):
        raise
    except Exception as exc:
        if isinstance(exc, (InvalidDocumentError, UnicodeDecodeError)):
            raise HTTPException(status_code=400, detail=str(exc) or None) from exc
        raise upstream_error("parser", exc) from exc


def _block_response(block) -> ParserBlock:
    if isinstance(block, TextBlock):
        return ParserTextBlock(text=block.text, page=block.page, kind=block.kind)
    if isinstance(block, TableBlock):
        return ParserTableBlock(rows=block.rows, caption=block.caption.strip() or None, page=block.page)
    if isinstance(block, FormulaBlock):
        return ParserFormulaBlock(text=block.text, format=block.format, page=block.page)
    raise ValueError(f"Unsupported parser block: {type(block).__name__}")
