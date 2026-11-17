import asyncio
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024

ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


class FileTooLargeError(Exception):
    pass


def absolute_path(relative_path: str) -> Path:
    return Path(settings.storage_dir).resolve() / relative_path


async def save_upload(file: UploadFile, relative_path: str) -> int:
    destination = absolute_path(relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with destination.open("wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError
                await asyncio.to_thread(out.write, chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return size


def delete_file(relative_path: str) -> None:
    absolute_path(relative_path).unlink(missing_ok=True)