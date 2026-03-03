"""
Documents API — track documents linked to legal matters.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from backend.core.database import get_db
from backend.models.document import Document

router = APIRouter()


class DocumentCreate(BaseModel):
    matter_id: Optional[UUID] = None
    title: str
    doc_type: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    description: Optional[str] = None
    uploaded_by: str = "owner"
    tags: Optional[List[str]] = None


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class DocumentResponse(BaseModel):
    id: UUID
    matter_id: Optional[UUID] = None
    title: str
    doc_type: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    description: Optional[str] = None
    uploaded_by: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_response(d: Document) -> DocumentResponse:
    return DocumentResponse(
        id=d.id,
        matter_id=d.matter_id,
        title=d.title,
        doc_type=d.doc_type,
        file_path=d.file_path,
        file_url=d.file_url,
        description=d.description,
        uploaded_by=d.uploaded_by,
        tags=d.tags,
        created_at=d.created_at,
    )


@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    matter_id: Optional[UUID] = Query(None),
    doc_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document).order_by(desc(Document.created_at))
    if matter_id:
        query = query.where(Document.matter_id == matter_id)
    if doc_type:
        query = query.where(Document.doc_type == doc_type)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return [_to_response(d) for d in result.scalars().all()]


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    d = await db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    return _to_response(d)


@router.post("/", response_model=DocumentResponse, status_code=201)
async def create_document(data: DocumentCreate, db: AsyncSession = Depends(get_db)):
    doc = Document(**data.model_dump(exclude_unset=True))
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return _to_response(doc)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(doc_id: UUID, data: DocumentUpdate, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    await db.flush()
    await db.refresh(doc)
    return _to_response(doc)


@router.delete("/{doc_id}")
async def delete_document(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    await db.delete(doc)
    return {"status": "deleted", "id": str(doc_id)}
