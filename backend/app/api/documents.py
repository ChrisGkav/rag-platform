import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import settings
from app.db.session import get_session
from app.models import Document, User
from app.schemas.document import DocumentRead
from app.services import storage

router = APIRouter(prefix="/documents", tags=["documents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_owned_document(
    document_id: uuid.UUID, user: User, session: AsyncSession
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == user.id
        )
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile, current_user: CurrentUser, session: SessionDep
) -> Document:
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()
    content_type = storage.ALLOWED_TYPES.get(extension)
    if content_type is None:
        allowed = ", ".join(storage.ALLOWED_TYPES)
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type. Allowed: {allowed}",
        )

    document_id = uuid.uuid4()
    relative_path = f"{current_user.id}/{document_id}{extension}"

    try:
        size = await storage.save_upload(file, relative_path)
    except storage.FileTooLargeError:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File too large (max {settings.max_upload_mb} MB)",
        )

    if size == 0:
        storage.delete_file(relative_path)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    document = Document(
        id=document_id,
        owner_id=current_user.id,
        filename=original_name[:255],
        content_type=content_type,
        size_bytes=size,
        storage_path=relative_path,
    )
    session.add(document)
    try:
        await session.commit()
    except Exception:
        storage.delete_file(relative_path)
        raise
    await session.refresh(document)
    return document


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    current_user: CurrentUser, session: SessionDep
) -> list[Document]:
    result = await session.scalars(
        select(Document)
        .where(Document.owner_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    return list(result)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID, current_user: CurrentUser, session: SessionDep
) -> Document:
    return await get_owned_document(document_id, current_user, session)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, current_user: CurrentUser, session: SessionDep
) -> None:
    document = await get_owned_document(document_id, current_user, session)
    relative_path = document.storage_path
    await session.delete(document)
    await session.commit()
    storage.delete_file(relative_path)