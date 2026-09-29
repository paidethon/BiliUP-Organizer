from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import AdminUser

DbSession = Annotated[Session, Depends(get_db)]
CurrentAdmin = Annotated[AdminUser, Depends(require_admin)]
