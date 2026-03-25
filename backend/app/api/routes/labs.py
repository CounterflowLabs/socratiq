"""API routes for code labs."""

import io
import json
import uuid
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.db.models.lab import Lab
from app.db.models.user import User
from app.models.lab import LabResponse

router = APIRouter(prefix="/api/v1/labs", tags=["labs"])


@router.get("/section/{section_id}", response_model=LabResponse | None)
async def get_section_lab(
    section_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
):
    result = await db.execute(select(Lab).where(Lab.section_id == section_id))
    lab = result.scalar_one_or_none()
    if not lab:
        return None
    return LabResponse(
        id=str(lab.id), section_id=str(lab.section_id),
        title=lab.title, description=lab.description,
        language=lab.language, starter_code=lab.starter_code,
        test_code=lab.test_code, run_instructions=lab.run_instructions,
        confidence=float(lab.confidence),
    )


@router.get("/{lab_id}/download")
async def download_lab(
    lab_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
):
    lab = await db.get(Lab, lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    # Create zip in memory
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Starter code
        for filename, content in lab.starter_code.items():
            zf.writestr(filename, content)
        # Tests
        for filename, content in lab.test_code.items():
            zf.writestr(filename, content)
        # README with run instructions
        readme = f"# {lab.title}\n\n{lab.description}\n\n## How to Run\n\n{lab.run_instructions}\n"
        zf.writestr("README.md", readme)

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=lab_{lab.title.replace(' ', '_')}.zip"},
    )
