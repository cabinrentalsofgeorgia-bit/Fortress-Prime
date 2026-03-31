from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.core.security import get_current_user, load_staff_user_from_token_string


@pytest.mark.asyncio
async def test_get_current_user_rejects_owner_style_subject() -> None:
    db = AsyncMock()
    creds = type("Creds", (), {"credentials": "owner-token"})()

    with patch("backend.core.security.decode_token", return_value={"sub": "146514", "role": "owner"}):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(creds=creds, db=db)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_load_staff_user_from_token_string_returns_none_for_owner_subject() -> None:
    db = AsyncMock()

    with patch("backend.core.security.decode_token", return_value={"sub": "146514", "role": "owner"}):
        user = await load_staff_user_from_token_string(db, "owner-token")

    assert user is None
