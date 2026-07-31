import base64
import json
from dataclasses import dataclass
from os import environ
from typing import Annotated, Any, NoReturn
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Principal:
    """Authenticated application user; authorization attributes live in the database."""

    user_id: UUID


def current_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Validate a local Keycloak access token and map its verified subject.

    The bridge uses token introspection with the configured confidential client,
    so a caller cannot create a principal by supplying arbitrary headers or JWT
    claims. Any missing configuration, unavailable identity provider, malformed
    response, or claim mismatch fails closed with 401.
    """
    access_token = _bearer_token(authorization)
    claims = _validated_claims(access_token) if access_token else None
    if claims is None:
        _authentication_required()

    session = _new_session()
    try:
        from agreement_intelligence_api.identity.service import IdentityService

        identity = IdentityService(session)
        user = identity.provision_user(
            issuer=claims.issuer,
            subject=claims.subject,
            display_name=claims.display_name,
            email=claims.email,
        )
        session.commit()
        user_id = user.id
    except Exception:
        session.rollback()
        _authentication_required()
    finally:
        session.close()
    return Principal(user_id=user_id)


@dataclass(frozen=True)
class _VerifiedClaims:
    issuer: str
    subject: str
    username: str | None
    display_name: str
    email: str | None


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def _validated_claims(access_token: str) -> _VerifiedClaims | None:
    expected_issuer = environ.get("OIDC_ISSUER")
    expected_client_id = environ.get("OIDC_CLIENT_ID")
    claims = _introspect_access_token(access_token)
    if not expected_issuer or not expected_client_id:
        return None
    if claims is not None and claims.get("active") is True:
        return _verified_claims_from_introspection(
            claims,
            expected_issuer=expected_issuer,
            expected_client_id=expected_client_id,
        )
    return _verified_claims_from_userinfo(
        access_token,
        expected_issuer=expected_issuer,
        expected_client_id=expected_client_id,
    )


def _verified_claims_from_introspection(
    claims: dict[str, Any], *, expected_issuer: str, expected_client_id: str
) -> _VerifiedClaims | None:
    subject = claims.get("sub")
    issuer = claims.get("iss")
    client_id = claims.get("client_id")
    if (
        not isinstance(subject, str)
        or not subject
        or issuer != expected_issuer
        or client_id != expected_client_id
    ):
        return None
    display_name = next(
        (
            value
            for value in (claims.get("name"), claims.get("preferred_username"), claims.get("email"))
            if isinstance(value, str) and value
        ),
        None,
    )
    if display_name is None:
        return None
    email = claims.get("email")
    username = claims.get("preferred_username") or claims.get("username")
    return _VerifiedClaims(
        issuer=issuer,
        subject=subject,
        username=username if isinstance(username, str) else None,
        display_name=display_name,
        email=email if isinstance(email, str) else None,
    )


def _verified_claims_from_userinfo(
    access_token: str, *, expected_issuer: str, expected_client_id: str
) -> _VerifiedClaims | None:
    token_claims = _unverified_token_claims(access_token)
    userinfo = _userinfo_claims(access_token)
    if token_claims is None or userinfo is None:
        return None
    subject = userinfo.get("sub")
    token_subject = token_claims.get("sub")
    issuer = token_claims.get("iss")
    client_id = token_claims.get("client_id") or token_claims.get("azp")
    if (
        not isinstance(subject, str)
        or not subject
        or token_subject != subject
        or issuer != expected_issuer
        or client_id != expected_client_id
    ):
        return None
    display_name = next(
        (
            value
            for value in (
                userinfo.get("name"),
                userinfo.get("preferred_username"),
                userinfo.get("email"),
            )
            if isinstance(value, str) and value
        ),
        None,
    )
    if display_name is None:
        return None
    email = userinfo.get("email")
    username = userinfo.get("preferred_username")
    return _VerifiedClaims(
        issuer=issuer,
        subject=subject,
        username=username if isinstance(username, str) else None,
        display_name=display_name,
        email=email if isinstance(email, str) else None,
    )


def _introspect_access_token(access_token: str) -> dict[str, Any] | None:
    internal_issuer = environ.get("OIDC_INTERNAL_ISSUER")
    client_id = environ.get("OIDC_CLIENT_ID")
    client_secret = environ.get("OIDC_CLIENT_SECRET")
    if not internal_issuer or not client_id or not client_secret:
        return None
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = Request(
        f"{internal_issuer.rstrip('/')}/protocol/openid-connect/token/introspect",
        data=urlencode({"token": access_token}).encode(),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310 - configured OIDC endpoint
            payload = json.load(response)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _userinfo_claims(access_token: str) -> dict[str, Any] | None:
    internal_issuer = environ.get("OIDC_INTERNAL_ISSUER")
    if not internal_issuer:
        return None
    request = Request(
        f"{internal_issuer.rstrip('/')}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310 - configured OIDC endpoint
            payload = json.load(response)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _unverified_token_claims(access_token: str) -> dict[str, Any] | None:
    parts = access_token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode())
        claims = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def _authentication_required() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required"},
    )


def _new_session() -> Session:
    from sqlalchemy.orm import sessionmaker

    from agreement_intelligence_api.db import engine

    return sessionmaker(bind=engine())()


def hide_resource() -> NoReturn:
    """Return a resource-agnostic denial without disclosing its existence."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "resource_not_found"},
    )
