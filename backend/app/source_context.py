"""Safe, bounded ZIP indexing for explicitly supplied source context."""

import io
import re
import stat
import zlib
import uuid
import zipfile
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import SourceContextChunk, UploadedDataset

router = APIRouter(prefix="/api/uploads", tags=["source context"])
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 15 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 256 * 1024
MAX_ARCHIVE_ITEMS = 5000
MAX_SOURCE_FILES = 200
MAX_INDEXED_CHUNKS = 3000
CHUNK_CHARS = 1400
ALLOWED_EXTENSIONS = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".go", ".rs", ".cs", ".c", ".h", ".cpp", ".hpp", ".rb", ".php", ".swift", ".scala"}
EXCLUDED_PARTS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "coverage", "vendor", "__pycache__"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials", "secrets.json", "secrets.yaml", "secrets.yml"}
_SENSITIVE_NAME = re.compile(r"(?:^|[._-])(?:secrets?|credentials?|tokens?|api[_-]?keys?|private[_-]?keys?)(?:[._-]|$)")
_PEM_BLOCK = re.compile(r"-----BEGIN [^-\r\n]*(?:PRIVATE KEY|CERTIFICATE)[^-\r\n]*-----.*?-----END [^-\r\n]*(?:PRIVATE KEY|CERTIFICATE)[^-\r\n]*-----", re.I | re.S)
_ASSIGNMENT_SECRET = re.compile(r"(?im)(?<![a-z0-9])((?:aws[_-]?secret[_-]?access[_-]?key|secret[_-]?access[_-]?key|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret|token|credential)(?![a-z0-9])\s*[:=]\s*).+$")
_TOKEN = re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_WORD = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")


class SourceContextSummary(BaseModel):
    files: int
    chunks: int


def _safe_archive_path(name: str) -> tuple[str, PurePosixPath]:
    if "\\" in name or name.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:", name):
        raise ValueError("Archive contains an unsafe absolute path.")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts) or not path.parts:
        raise ValueError("Archive contains an unsafe path.")
    normalized = path.as_posix()
    if len(normalized) > 500:
        raise ValueError("Archive contains a path that is too long.")
    return normalized, path


def _excluded(path: PurePosixPath) -> bool:
    parts = [part.casefold() for part in path.parts]
    name = parts[-1]
    return (
        any(part in EXCLUDED_PARTS for part in parts)
        or name in EXCLUDED_NAMES
        or bool(_SENSITIVE_NAME.match(name))
        or name.startswith(".env.")
        or name.endswith((".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".der", ".lock"))
        or path.suffix.lower() not in ALLOWED_EXTENSIONS
    )


def _redact(content: str) -> str:
    content = _PEM_BLOCK.sub("[REDACTED PRIVATE MATERIAL]", content)
    content = _ASSIGNMENT_SECRET.sub(lambda match: f"{match.group(1)}[REDACTED]", content)
    content = _TOKEN.sub("[REDACTED TOKEN]", content)
    return _JWT.sub("[REDACTED TOKEN]", content)


def _split_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            newline = text.rfind("\n", start, end)
            if newline > start + CHUNK_CHARS // 2:
                end = newline + 1
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        start = end
        if len(chunks) > MAX_INDEXED_CHUNKS:
            raise ValueError("Source archive produces too many index chunks.")
    return chunks


def index_source_archive(dataset_id: uuid.UUID, archive: bytes) -> list[SourceContextChunk]:
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP upload exceeds the 5 MiB limit.")
    if not zipfile.is_zipfile(io.BytesIO(archive)):
        raise ValueError("Upload a valid ZIP archive.")
    chunks: list[SourceContextChunk] = []
    extracted_total = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        members = zipped.infolist()
        if not members or len(members) > MAX_ARCHIVE_ITEMS:
            raise ValueError(f"ZIP archives must contain between 1 and {MAX_ARCHIVE_ITEMS} entries.")
        declared_total = 0
        eligible_paths: set[str] = set()
        for info in members:
            path_text, path = _safe_archive_path(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("ZIP symbolic links are not accepted.")
            if info.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP entries are not accepted.")
            if not info.is_dir():
                if not _excluded(path):
                    folded_path = path_text.casefold()
                    if folded_path in eligible_paths:
                        raise ValueError("ZIP archive contains duplicate source paths.")
                    eligible_paths.add(folded_path)
                    if len(eligible_paths) > MAX_SOURCE_FILES:
                        raise ValueError(f"ZIP archive contains more than {MAX_SOURCE_FILES} eligible source files.")
                    if info.file_size < 0 or info.file_size > MAX_SOURCE_FILE_BYTES:
                        raise ValueError("A source file exceeds the 256 KiB per-file limit.")
                    declared_total += info.file_size
                    if declared_total > MAX_TOTAL_SOURCE_BYTES:
                        raise ValueError("The ZIP archive exceeds the 15 MiB extracted-content limit.")
        eligible_members = [info for info in members if not info.is_dir() and not _excluded(_safe_archive_path(info.filename)[1])]
        actual_total = 0
        for info in eligible_members:
            path_text, path = _safe_archive_path(info.filename)
            if info.file_size < 0 or info.file_size > MAX_SOURCE_FILE_BYTES:
                raise ValueError("A source file exceeds the 256 KiB per-file limit.")
            extracted_total += info.file_size
            if extracted_total > MAX_TOTAL_SOURCE_BYTES:
                raise ValueError("The ZIP archive exceeds the 15 MiB extracted-content limit.")
            if info.compress_size and info.file_size / info.compress_size > 200:
                raise ValueError("ZIP entry compression ratio is too high.")
            with zipped.open(info) as source_file:
                content_bytes = source_file.read(MAX_SOURCE_FILE_BYTES + 1)
            if len(content_bytes) > MAX_SOURCE_FILE_BYTES:
                raise ValueError("A source file exceeds the 256 KiB per-file limit.")
            actual_total += len(content_bytes)
            if actual_total > MAX_TOTAL_SOURCE_BYTES:
                raise ValueError("The ZIP archive exceeds the 15 MiB extracted-content limit.")
            try:
                content = content_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                continue
            safe_content = _redact(content)
            for chunk_index, chunk in enumerate(_split_chunks(safe_content)):
                chunks.append(SourceContextChunk(
                    dataset_id=dataset_id, file_path=path_text,
                    chunk_index=chunk_index, content=chunk,
                ))
                if len(chunks) > MAX_INDEXED_CHUNKS:
                    raise ValueError("Source archive produces too many index chunks.")
    if not chunks:
        raise ValueError("The ZIP archive contains no eligible UTF-8 source files.")
    return chunks


async def _read_bounded(upload: UploadFile) -> bytes:
    data = bytearray()
    while True:
        chunk = await upload.read(min(64 * 1024, MAX_ARCHIVE_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="ZIP upload exceeds the 5 MiB limit.")
    if not data:
        raise HTTPException(status_code=400, detail="The ZIP upload is empty.")
    return bytes(data)


@router.put("/{upload_id}/source-context", response_model=SourceContextSummary)
async def replace_source_context(upload_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)) -> SourceContextSummary:
    try:
        dataset_id = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="upload_id must be a valid UUID.") from exc
    if db.get(UploadedDataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Source context must be uploaded as a .zip archive.")
    archive = await _read_bounded(file)
    try:
        indexed = index_source_archive(dataset_id, archive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise HTTPException(status_code=400, detail="The ZIP archive is malformed or uses unsupported compression.") from exc
    file_count = len({chunk.file_path for chunk in indexed})
    db.execute(delete(SourceContextChunk).where(SourceContextChunk.dataset_id == dataset_id))
    db.add_all(indexed)
    db.commit()
    return SourceContextSummary(files=file_count, chunks=len(indexed))


@router.get("/{upload_id}/source-context", response_model=SourceContextSummary)
def source_context_status(upload_id: str, db: Session = Depends(get_db)) -> SourceContextSummary:
    dataset_id = _dataset_id(upload_id, db)
    files, chunks = db.execute(select(func.count(func.distinct(SourceContextChunk.file_path)), func.count(SourceContextChunk.id)).where(SourceContextChunk.dataset_id == dataset_id)).one()
    return SourceContextSummary(files=files or 0, chunks=chunks or 0)


@router.delete("/{upload_id}/source-context", status_code=204)
def delete_source_context(upload_id: str, db: Session = Depends(get_db)) -> None:
    dataset_id = _dataset_id(upload_id, db)
    db.execute(delete(SourceContextChunk).where(SourceContextChunk.dataset_id == dataset_id))
    db.commit()


def _dataset_id(upload_id: str, db: Session) -> uuid.UUID:
    try:
        dataset_id = uuid.UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="upload_id must be a valid UUID.") from exc
    if db.get(UploadedDataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return dataset_id


def retrieve_source_chunks(db: Session, dataset_id: uuid.UUID, query: str, limit: int = 5) -> list[SourceContextChunk]:
    """Return a few dataset-local chunks ranked by filename and token overlap."""
    terms = {token.casefold() for token in _WORD.findall(query) if len(token) >= 3}
    rows = list(db.scalars(select(SourceContextChunk).where(SourceContextChunk.dataset_id == dataset_id).order_by(SourceContextChunk.file_path, SourceContextChunk.chunk_index).limit(MAX_INDEXED_CHUNKS)).all())
    ranked: list[tuple[int, SourceContextChunk]] = []
    for row in rows:
        text = f"{row.file_path} {row.content}".casefold()
        words = set(_WORD.findall(text))
        score = len(words & terms)
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1].file_path, item[1].chunk_index))
    selected: list[SourceContextChunk] = []
    size = 0
    for _, row in ranked:
        if len(selected) >= limit or size + len(row.content) > 6000:
            continue
        selected.append(row)
        size += len(row.content)
    return selected
