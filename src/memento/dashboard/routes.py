"""Dashboard API routes."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memento.api import LocalAPI

router = APIRouter(prefix="/api")


def _get_api() -> LocalAPI:
    """Create a LocalAPI instance for the request."""
    return LocalAPI()


def _parse_tags(tags_raw) -> list:
    """Parse tags from various formats."""
    if isinstance(tags_raw, list):
        return tags_raw
    if isinstance(tags_raw, str):
        try:
            import json as _json
            parsed = _json.loads(tags_raw)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError):
            pass
        return [t.strip() for t in tags_raw.split(",") if t.strip()]
    return []


class PinRequest(BaseModel):
    rigidity: float


class EpochRunRequest(BaseModel):
    mode: str = "full"


# ── Status ──

@router.get("/status")
def get_status():
    """System status (equivalent to `memento status`)."""
    api = _get_api()
    stats = api.status()
    api.close()
    return {
        "total": stats.total,
        "active": stats.active,
        "forgotten": stats.forgotten,
        "unverified_agent": stats.unverified_agent,
        "with_embedding": stats.with_embedding,
        "pending_embedding": stats.pending_embedding,
        "total_sessions": stats.total_sessions,
        "active_sessions": stats.active_sessions,
        "completed_sessions": stats.completed_sessions,
        "total_observations": stats.total_observations,
        "by_state": stats.by_state,
        "pending_capture": stats.pending_capture,
        "pending_delta": stats.pending_delta,
        "cognitive_debt_count": stats.cognitive_debt_count,
        "last_epoch_committed_at": stats.last_epoch_committed_at,
    }


# ── Engrams ──

@router.get("/engrams")
def list_engrams(
    q: str = "",
    type: str = "",
    origin: str = "",
    importance: str = "",
    verified: str = "",
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    """List engrams with filtering, sorting, and pagination."""
    api = _get_api()
    try:
        if q:
            # Recall for relevance-ranked search, then apply filters on results
            results = api.recall(q, max_results=limit * 3)  # fetch extra to allow post-filtering
            api.close()
            normalized = []
            for r in results:
                if isinstance(r, dict):
                    item = {
                        "id": r.get("id"),
                        "content": r.get("content"),
                        "type": r.get("type"),
                        "origin": r.get("origin"),
                        "importance": r.get("importance"),
                        "strength": r.get("score", 0),
                        "rigidity": 0.0,
                        "verified": bool(r.get("verified", False)),
                        "provisional": r.get("provisional", False),
                        "tags": _parse_tags(r.get("tags")),
                        "access_count": 0,
                        "created_at": r.get("created_at", ""),
                        "last_accessed": r.get("last_accessed", ""),
                    }
                    # Apply post-filters on search results
                    if type and item["type"] not in [t.strip() for t in type.split(",")]:
                        continue
                    if origin and item["origin"] != origin:
                        continue
                    if importance and item["importance"] != importance:
                        continue
                    normalized.append(item)
            return normalized[:limit]

        verified_bool = None
        if verified == "true":
            verified_bool = True
        elif verified == "false":
            verified_bool = False

        results = api.list_engrams(
            type=type or None,
            origin=origin or None,
            importance=importance or None,
            verified=verified_bool,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        api.close()
        return results
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})


@router.get("/engrams/{engram_id}")
def get_engram_detail(engram_id: str):
    """Get detailed engram info including nexus connections."""
    api = _get_api()
    result = api.inspect(engram_id)
    api.close()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ENGRAM_NOT_FOUND", "message": f"Engram {engram_id} not found"},
        )
    result["tags"] = _parse_tags(result.get("tags"))
    result["verified"] = bool(result.get("verified"))
    # Remove binary fields that can't be JSON-serialized
    result.pop("embedding", None)
    return result


@router.delete("/engrams/{engram_id}")
def forget_engram(engram_id: str):
    """Mark a memory for deletion (takes effect after next epoch)."""
    api = _get_api()
    try:
        result = api.forget(engram_id)
        api.close()
        if isinstance(result, dict):
            result["ok"] = True
            return result
        return {"ok": result, "id": engram_id, "action": "marked_for_forget"}
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "FORGET_FAILED", "message": str(e)})


@router.post("/engrams/{engram_id}/verify")
def verify_engram(engram_id: str):
    """Verify an agent memory as trustworthy."""
    api = _get_api()
    try:
        result = api.verify(engram_id)
        api.close()
        if isinstance(result, dict):
            return result
        return {"ok": result, "id": engram_id}
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "VERIFY_FAILED", "message": str(e)})


@router.post("/engrams/{engram_id}/pin")
def pin_engram(engram_id: str, body: PinRequest):
    """Set rigidity for an engram (0.0-1.0)."""
    if not (0.0 <= body.rigidity <= 1.0):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_RIGIDITY", "message": "rigidity must be between 0.0 and 1.0"},
        )
    api = _get_api()
    try:
        result = api.pin(engram_id, body.rigidity)
        api.close()
        return result
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "PIN_FAILED", "message": str(e)})


# ── Sessions ──

@router.get("/sessions")
def list_sessions(project: str = "", status: str = "", limit: int = 20):
    """List sessions, optionally filtered by project."""
    api = _get_api()
    sessions = api.session_list(project=project or None, limit=limit)
    api.close()
    return [
        {
            "id": s.id,
            "project": s.project,
            "task": s.task,
            "status": s.status,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "summary": s.summary,
            "event_counts": s.event_counts if s.event_counts else {},
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str):
    """Get session detail with event counts."""
    api = _get_api()
    info = api.session_status(session_id)
    api.close()

    if not info:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found"},
        )
    return {
        "id": info.id,
        "project": info.project,
        "task": info.task,
        "status": info.status,
        "started_at": info.started_at,
        "ended_at": info.ended_at,
        "summary": info.summary,
        "event_counts": info.event_counts if info.event_counts else {},
    }


# ── Epoch ──

@router.get("/epoch/history")
def get_epoch_history():
    """Get recent epoch run records."""
    api = _get_api()
    records = api.epoch_status()
    api.close()
    return records


@router.get("/epoch/debt")
def get_epoch_debt():
    """Get unresolved cognitive debt by type."""
    api = _get_api()
    debt = api.epoch_debt()
    api.close()
    return debt


@router.post("/epoch/run")
def run_epoch(body: EpochRunRequest):
    """Trigger an epoch consolidation run."""
    api = _get_api()
    try:
        result = api.epoch_run(mode=body.mode, trigger="manual")
        api.close()
        return result
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "EPOCH_FAILED", "message": str(e)})


# ── Captures ──

@router.get("/captures/pending")
def get_pending_captures(limit: int = 50):
    """List pending captures in L2 buffer."""
    api = _get_api()
    results = api.list_pending_captures(limit=limit)
    api.close()
    return results
