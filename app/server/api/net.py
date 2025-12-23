from __future__ import annotations

from fastapi import APIRouter

from app.server.net_table import get_api_list

router = APIRouter()


@router.get("/api_list")
def api_list_nodes():
    return {"items": get_api_list()}
