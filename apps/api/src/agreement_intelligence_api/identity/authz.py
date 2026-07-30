from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException, status


@dataclass(frozen=True)
class Principal:
    """Authenticated application user; authorization attributes live in the database."""

    user_id: UUID


def current_principal() -> NoReturn:
    """Authentication integration seam; OIDC validation is supplied by the API gateway."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required"},
    )


def hide_resource() -> NoReturn:
    """Return a resource-agnostic denial without disclosing its existence."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "resource_not_found"},
    )
