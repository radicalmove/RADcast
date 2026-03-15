"""FastAPI service exposing RADcast endpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request as URLRequest, urlopen

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import PlainTextResponse

from radcast.constants import DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS, DEFAULT_WORKER_ONLINE_WINDOW_SECONDS
from radcast.exceptions import EnhancementRuntimeError, JobCancelledError
from radcast.manifests import ManifestStore
from radcast.models import (
    CaptionFormat,
    CaptionQualityMode,
    EnhancementModel,
    FillerRemovalMode,
    JobRecord,
    JobStatus,
    OutputFormat,
    OutputMetadata,
    ProjectAccessGrantRequest,
    ProjectAccessRevokeRequest,
    ProjectCreateRequest,
    ProjectSourceAudioDeleteRequest,
    ProjectSourceAudioUploadRequest,
    ProjectUiSettings,
    SimpleEnhanceRequest,
    WorkerEnhanceEnqueueRequest,
    WorkerInviteRequest,
    WorkerInviteResponse,
    WorkerJobCompleteRequest,
    WorkerJobFailRequest,
    WorkerJobProgressRequest,
    WorkerPullRequest,
    WorkerPullResponse,
    WorkerRegisterRequest,
    now_utc_iso,
    touch_job_update,
)
from radcast.project import ProjectManager
from radcast.progress import (
    estimate_speech_cleanup_seconds,
    extend_eta_with_postprocess,
    map_local_stage_progress,
    map_postprocess_stage_progress,
)
from radcast.services.enhance import EnhanceService
from radcast.services.speech_cleanup import SpeechCleanupService
from radcast.utils.audio import probe_duration_seconds
from radcast.worker_manager import WorkerManager

try:
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from starlette.middleware.sessions import SessionMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("FastAPI is not installed. Install with 'pip install -e .'.") from exc


PROJECTS_ROOT = Path(os.environ.get("RADCAST_PROJECTS_ROOT", "projects"))
MODULE_ROOT = Path(__file__).resolve().parent
AUTH_REQUIRED = str(os.environ.get("RADCAST_AUTH_REQUIRED", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSION_SECRET = os.environ.get("RADCAST_SESSION_SECRET", "radcast-dev-session-secret")
SESSION_SECURE = str(os.environ.get("RADCAST_SESSION_SECURE", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PSYCHEK_LOGIN_URL = os.environ.get("PSYCHEK_LOGIN_URL", "http://127.0.0.1:8000/login")
BRIDGE_SECRET = os.environ.get("RADCAST_BRIDGE_SECRET", SESSION_SECRET)
BRIDGE_MAX_AGE_SECONDS = int(os.environ.get("RADCAST_BRIDGE_MAX_AGE_SECONDS", "120"))
SCOPE_PROJECTS_BY_USER = str(os.environ.get("RADCAST_SCOPE_PROJECTS_BY_USER", "true")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SCOPED_PROJECT_RE = re.compile(r"^u[0-9a-f]{12}__.+$")
WORKER_SECRET = os.environ.get("RADCAST_WORKER_SECRET", SESSION_SECRET)
WORKER_FALLBACK_ENABLED = str(os.environ.get("RADCAST_WORKER_FALLBACK_ENABLED", "true")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WORKER_FALLBACK_TIMEOUT_SECONDS = max(
    5, int(os.environ.get("RADCAST_WORKER_FALLBACK_TIMEOUT_SECONDS", str(DEFAULT_WORKER_FALLBACK_TIMEOUT_SECONDS)))
)
WORKER_ONLINE_WINDOW_SECONDS = max(
    5, int(os.environ.get("RADCAST_WORKER_ONLINE_WINDOW_SECONDS", str(DEFAULT_WORKER_ONLINE_WINDOW_SECONDS)))
)
WORKER_INSTALL_SPEC = (
    os.environ.get("RADCAST_WORKER_INSTALL_SPEC", "git+https://github.com/radicalmove/RADcast.git").strip()
    or "git+https://github.com/radicalmove/RADcast.git"
)


app = FastAPI(title="RADcast API", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=SESSION_SECURE,
)
app.mount("/static", StaticFiles(directory=MODULE_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(MODULE_ROOT / "templates"))

project_manager = ProjectManager(PROJECTS_ROOT)
enhance_service = EnhanceService()
speech_cleanup_service = SpeechCleanupService()
worker_manager = WorkerManager(projects_root=PROJECTS_ROOT, worker_secret=WORKER_SECRET)

_job_update_lock = threading.Lock()
_cancelled_jobs: set[str] = set()
_UNSET = object()


def _infer_psychek_admin_url(login_url: str) -> str:
    cleaned = login_url.strip()
    if cleaned.endswith("/login"):
        return f"{cleaned[:-len('/login')]}/admin"
    return f"{cleaned.rstrip('/')}/admin"


def _infer_psychek_app_url(login_url: str) -> str:
    cleaned = login_url.strip()
    if cleaned.endswith("/login"):
        return cleaned[:-len("/login")] or "/"
    return cleaned.rstrip("/")


PSYCHEK_ADMIN_URL = os.environ.get("PSYCHEK_ADMIN_URL", "").strip() or _infer_psychek_admin_url(PSYCHEK_LOGIN_URL)
PSYCHEK_APP_URL = os.environ.get("PSYCHEK_APP_URL", "").strip() or _infer_psychek_app_url(PSYCHEK_LOGIN_URL)
PSYCHEK_SHAREABLE_USERS_URL = (
    os.environ.get("PSYCHEK_SHAREABLE_USERS_URL", "").strip()
    or f"{PSYCHEK_APP_URL.rstrip('/')}/api/v1/integrations/shareable-users"
)
PSYCHEK_INTEGRATION_API_KEY = os.environ.get("PSYCHEK_INTEGRATION_API_KEY", "").strip() or BRIDGE_SECRET
RADTTS_APP_URL = os.environ.get("RADTTS_APP_URL", "").strip()


def _bridge_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(BRIDGE_SECRET, salt="app-bridge-radcast-v1")


def _current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def _require_auth(request: Request) -> None:
    if AUTH_REQUIRED and _current_user(request) is None:
        raise HTTPException(status_code=401, detail="authentication required")


def _login_redirect() -> RedirectResponse:
    query = urlencode({"target_app": "radcast"})
    separator = "&" if "?" in PSYCHEK_LOGIN_URL else "?"
    return RedirectResponse(f"{PSYCHEK_LOGIN_URL}{separator}{query}", status_code=302)


def _scope_prefix(request: Request) -> str | None:
    user = _current_user(request)
    if not user:
        return None
    sub = str(user.get("sub") or "").strip()
    email = str(user.get("email") or "").strip().lower()
    identity = f"{sub}|{email}".strip("|")
    if not identity:
        return None
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"u{digest}"


def _current_user_key_and_label(request: Request) -> tuple[str | None, str | None]:
    user = _current_user(request)
    if not user:
        return None, None

    user_key = _scope_prefix(request)
    if not user_key:
        return None, None

    label = str(user.get("display_name") or user.get("email") or user.get("sub") or user_key).strip()
    return user_key, label or user_key


def _scope_project_id(request: Request, project_id: str) -> str:
    if not SCOPE_PROJECTS_BY_USER:
        return project_id
    prefix = _scope_prefix(request)
    if not prefix:
        return project_id
    if project_id.startswith(f"{prefix}__"):
        return project_id
    return f"{prefix}__{project_id}"


def _looks_scoped_project_id(project_id: str) -> bool:
    return bool(SCOPED_PROJECT_RE.match(project_id.strip()))


def _display_project_id(project_id: str) -> str:
    value = project_id.strip()
    if _looks_scoped_project_id(value) and "__" in value:
        return value.split("__", 1)[1]
    return value


def _path_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return None


def _project_last_activity_at(scoped_project_id: str) -> datetime:
    paths = project_manager.get_paths(scoped_project_id)
    timestamps: list[datetime] = []

    root_mtime = _path_mtime(paths.root)
    if root_mtime is not None:
        timestamps.append(root_mtime)

    for manifest_path in paths.manifests.glob("*.json"):
        manifest_mtime = _path_mtime(manifest_path)
        if manifest_mtime is not None:
            timestamps.append(manifest_mtime)

    if not timestamps:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return max(timestamps)


def _coerce_project_settings(payload: object) -> ProjectUiSettings:
    data = payload if isinstance(payload, dict) else {}

    selected_audio_hash = str(data.get("selected_audio_hash") or "").strip() or None
    if selected_audio_hash and len(selected_audio_hash) < 16:
        selected_audio_hash = None

    output_format_raw = str(data.get("output_format") or OutputFormat.MP3.value).strip().lower()
    try:
        output_format = OutputFormat(output_format_raw)
    except ValueError:
        output_format = OutputFormat.MP3

    caption_format_raw = str(data.get("caption_format") or "").strip().lower()
    try:
        caption_format = CaptionFormat(caption_format_raw) if caption_format_raw else None
    except ValueError:
        caption_format = None

    caption_quality_mode_raw = str(data.get("caption_quality_mode") or CaptionQualityMode.ACCURATE.value).strip().lower()
    try:
        caption_quality_mode = CaptionQualityMode(caption_quality_mode_raw)
    except ValueError:
        caption_quality_mode = CaptionQualityMode.ACCURATE
    caption_glossary = str(data.get("caption_glossary") or "").strip() or None

    enhancement_model_raw = str(data.get("enhancement_model") or EnhancementModel.RESEMBLE.value).strip().lower()
    try:
        enhancement_model = EnhancementModel(enhancement_model_raw)
    except ValueError:
        enhancement_model = EnhancementModel.RESEMBLE

    try:
        max_silence_seconds = float(data.get("max_silence_seconds", 1.0))
    except (TypeError, ValueError):
        max_silence_seconds = 1.0
    max_silence_seconds = max(0.0, min(4.0, max_silence_seconds))

    filler_removal_mode_raw = str(data.get("filler_removal_mode") or FillerRemovalMode.AGGRESSIVE.value).strip().lower()
    try:
        filler_removal_mode = FillerRemovalMode(filler_removal_mode_raw)
    except ValueError:
        filler_removal_mode = FillerRemovalMode.AGGRESSIVE

    return ProjectUiSettings(
        selected_audio_hash=selected_audio_hash,
        output_format=output_format,
        caption_format=caption_format,
        caption_quality_mode=caption_quality_mode,
        caption_glossary=caption_glossary,
        enhancement_model=enhancement_model,
        reduce_silence_enabled=bool(data.get("reduce_silence_enabled", False)),
        max_silence_seconds=max_silence_seconds,
        remove_filler_words=bool(data.get("remove_filler_words", False)),
        filler_removal_mode=filler_removal_mode,
    )


def _load_project_settings(scoped_project_id: str) -> ProjectUiSettings:
    metadata = project_manager.load_project_metadata(scoped_project_id)
    return _coerce_project_settings(metadata.get("ui_settings"))


def _write_project_settings(scoped_project_id: str, settings: ProjectUiSettings) -> ProjectUiSettings:
    project_manager.update_project_metadata(
        scoped_project_id,
        {"ui_settings": settings.model_dump(mode="json")},
    )
    return settings


def _inferred_owner_key_from_project_id(scoped_project_id: str) -> str:
    if "__" not in scoped_project_id:
        return ""
    prefix, _ = scoped_project_id.split("__", 1)
    return prefix if prefix.startswith("u") and len(prefix) == 13 else ""


def _project_access_file(scoped_project_id: str) -> Path:
    return project_manager.get_paths(scoped_project_id).manifests / "access.json"


def _load_project_access(scoped_project_id: str) -> dict[str, object]:
    access_path = _project_access_file(scoped_project_id)
    try:
        payload = json.loads(access_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    owner = payload.get("owner") if isinstance(payload.get("owner"), dict) else {}
    owner_key = str(owner.get("user_key") or "").strip()
    owner_email = str(owner.get("email") or "").strip().lower()
    owner_label = str(owner.get("display_name") or owner.get("email") or owner.get("sub") or owner_key).strip()

    inferred_owner_key = _inferred_owner_key_from_project_id(scoped_project_id)
    if not owner_key and inferred_owner_key:
        owner_key = inferred_owner_key
        if not owner_label:
            owner_label = owner_key

    collaborators_raw = payload.get("collaborators") if isinstance(payload.get("collaborators"), list) else []
    collaborators: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in collaborators_raw:
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        collaborators.append(
            {
                "email": email,
                "granted_at": str(row.get("granted_at") or ""),
                "granted_by": str(row.get("granted_by") or ""),
            }
        )

    return {
        "owner": {
            "user_key": owner_key,
            "email": owner_email,
            "display_name": owner_label,
        },
        "collaborators": collaborators,
        "updated_at": str(payload.get("updated_at") or ""),
    }


def _write_project_access(scoped_project_id: str, access: dict[str, object]) -> None:
    access_path = _project_access_file(scoped_project_id)
    access_path.parent.mkdir(parents=True, exist_ok=True)
    access_path.write_text(json.dumps(access, indent=2), encoding="utf-8")


def _bootstrap_owner_access_if_missing(request: Request, scoped_project_id: str) -> None:
    access_path = _project_access_file(scoped_project_id)
    if access_path.exists():
        return

    user = _current_user(request) or {}
    user_key, user_label = _current_user_key_and_label(request)
    access = {
        "owner": {
            "user_key": user_key or _inferred_owner_key_from_project_id(scoped_project_id),
            "email": str(user.get("email") or "").strip().lower(),
            "display_name": user_label or "",
        },
        "collaborators": [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_project_access(scoped_project_id, access)


def _resolve_access_for_user(request: Request, scoped_project_id: str) -> dict[str, object]:
    access = _load_project_access(scoped_project_id)
    session_user = _current_user(request)
    user = session_user or {}
    has_user = session_user is not None
    user_key, _ = _current_user_key_and_label(request)
    user_email = str(user.get("email") or "").strip().lower()
    is_admin = bool(user.get("is_admin", False)) if has_user else False

    owner = access.get("owner") if isinstance(access.get("owner"), dict) else {}
    owner_key = str(owner.get("user_key") or "")
    owner_email = str(owner.get("email") or "").strip().lower()

    collaborator_emails: set[str] = set()
    for row in access.get("collaborators", []):
        if isinstance(row, dict):
            email = str(row.get("email") or "").strip().lower()
            if email:
                collaborator_emails.add(email)

    is_owner = bool(
        (user_key and owner_key and user_key == owner_key)
        or (user_email and owner_email and user_email == owner_email)
    )
    is_collaborator = bool(user_email and user_email in collaborator_emails)
    if has_user:
        can_access = is_admin or is_owner or is_collaborator
    else:
        can_access = not AUTH_REQUIRED
    can_manage = is_admin or is_owner

    return {
        "can_access": can_access,
        "can_manage": can_manage,
        "is_owner": is_owner,
        "is_collaborator": is_collaborator,
        "is_admin": is_admin,
        "owner": owner,
        "collaborators": access.get("collaborators", []),
    }


def _resolve_project_id_for_request(request: Request, project_id: str) -> str:
    requested = project_id.strip()
    if not requested:
        raise HTTPException(status_code=404, detail="project not found")

    candidate_ids: list[str] = []
    if not SCOPE_PROJECTS_BY_USER:
        candidate_ids.append(requested)
    else:
        if _looks_scoped_project_id(requested):
            candidate_ids.append(requested)
        else:
            candidate_ids.append(_scope_project_id(request, requested))
            for candidate in project_manager.list_projects():
                if _display_project_id(candidate) == requested:
                    candidate_ids.append(candidate)

    seen: set[str] = set()
    existing: list[str] = []
    for candidate in candidate_ids:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            project_manager.ensure_project(candidate)
        except FileNotFoundError:
            continue
        existing.append(candidate)

    if not existing:
        raise HTTPException(status_code=404, detail="project not found")

    for candidate in existing:
        access = _resolve_access_for_user(request, candidate)
        if bool(access.get("can_access")):
            return candidate

    raise HTTPException(status_code=403, detail="project access denied")


def _shareable_users_lookup_url(*, exclude_email: str = "") -> str:
    base_url = str(PSYCHEK_SHAREABLE_USERS_URL or "").strip()
    if not base_url:
        raise HTTPException(status_code=503, detail="shareable users are not configured")
    if not exclude_email:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'exclude_email': exclude_email})}"


def _extract_integration_error(exc: HTTPError) -> str:
    detail = f"HTTP {exc.code}"
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return detail
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("detail") or detail)
    return detail


def _fetch_shareable_users(*, exclude_email: str = "") -> list[dict[str, object]]:
    headers = {"Accept": "application/json"}
    if PSYCHEK_INTEGRATION_API_KEY:
        headers["Authorization"] = f"Bearer {PSYCHEK_INTEGRATION_API_KEY}"
    request = URLRequest(_shareable_users_lookup_url(exclude_email=exclude_email), headers=headers, method="GET")

    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _extract_integration_error(exc)
        if exc.code in {401, 403}:
            raise HTTPException(status_code=503, detail="shareable users authentication failed") from exc
        if exc.code == 404:
            raise HTTPException(status_code=503, detail="shareable users are unavailable") from exc
        raise HTTPException(status_code=502, detail=f"could not load shareable users: {detail}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"could not load shareable users: {exc.reason}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="invalid shareable users response") from exc

    rows = payload.get("users") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="invalid shareable users response")

    users: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or "").strip().lower()
        if not email:
            continue
        users.append(
            {
                "id": row.get("id"),
                "username": str(row.get("username") or "").strip(),
                "display_name": str(row.get("display_name") or "").strip(),
                "email": email,
            }
        )
    return users


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "audio.wav"


def _safe_audio_extension(filename: str) -> str:
    suffix = Path(_safe_filename(filename)).suffix.lower()
    if suffix in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}:
        return suffix
    return ".wav"


def _slug_text(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def _build_output_name(input_filename: str, override: str | None) -> str:
    if override and override.strip():
        cleaned = _slug_text(override)
        if cleaned:
            return cleaned
    stem = Path(_safe_filename(input_filename)).stem
    base = _slug_text(stem)[:36] or "enhanced-audio"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{base}-{stamp}"


def _cancel_requested(job_id: str) -> bool:
    return job_id in _cancelled_jobs


def _read_job(paths: Path, job_id: str) -> JobRecord | None:
    store = ManifestStore(paths)
    payload = store.get_job(job_id)
    if not payload:
        return None
    return JobRecord(**payload)


def _upsert_job(paths: Path, job: JobRecord) -> None:
    store = ManifestStore(paths)
    touch_job_update(job)
    store.upsert_job(job)


def _append_output(paths: Path, metadata: OutputMetadata) -> Path:
    store = ManifestStore(paths)
    metadata_path = paths / f"{metadata.output_file.stem}.metadata.json"
    store.write_output_file(metadata_path, metadata)
    store.append_output(metadata)
    return metadata_path


def _source_audio_manifest_path(paths) -> Path:
    return paths.manifests / "source_audio.json"


def _load_source_audio_index(paths) -> list[dict[str, object]]:
    try:
        payload = json.loads(_source_audio_manifest_path(paths).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _write_source_audio_index(paths, items: list[dict[str, object]]) -> None:
    _source_audio_manifest_path(paths).write_text(json.dumps(items, indent=2), encoding="utf-8")


def _upsert_source_audio(
    *,
    paths,
    audio_hash: str,
    audio_path: Path,
    source_filename: str,
) -> dict[str, object]:
    items = _load_source_audio_index(paths)
    now = datetime.now(timezone.utc).isoformat()
    duration_seconds = None
    try:
        duration_seconds = round(probe_duration_seconds(audio_path), 3)
    except Exception:
        duration_seconds = None

    next_entry = {
        "audio_hash": audio_hash,
        "audio_path": str(audio_path),
        "source_filename": _safe_filename(source_filename),
        "updated_at": now,
        "duration_seconds": duration_seconds,
    }

    updated = False
    next_items: list[dict[str, object]] = []
    for item in items:
        if str(item.get("audio_hash") or "") == audio_hash:
            next_items.append(next_entry)
            updated = True
        else:
            next_items.append(item)
    if not updated:
        next_items.append(next_entry)

    next_items.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    _write_source_audio_index(paths, next_items)
    return next_entry


def _list_source_audio_entries(request: Request, *, scoped_project_id: str) -> list[dict[str, object]]:
    paths = project_manager.get_paths(scoped_project_id)
    project_root = paths.root.resolve()
    if not project_root.exists():
        return []

    visible_project_id = _display_project_id(scoped_project_id)
    items: list[dict[str, object]] = []
    for entry in _load_source_audio_index(paths):
        audio_hash = str(entry.get("audio_hash") or "")
        saved_path = str(entry.get("audio_path") or "")
        if not audio_hash or not saved_path:
            continue
        audio_path = Path(saved_path)
        try:
            resolved = audio_path.resolve()
        except FileNotFoundError:
            continue
        if not resolved.exists():
            continue
        try:
            resolved.relative_to(project_root)
        except ValueError:
            continue

        duration_seconds = entry.get("duration_seconds")
        if duration_seconds is not None:
            try:
                duration_seconds = float(duration_seconds)
            except (TypeError, ValueError):
                duration_seconds = None

        items.append(
            {
                "audio_hash": audio_hash,
                "source_filename": str(entry.get("source_filename") or resolved.name),
                "saved_path": str(resolved),
                "updated_at": str(entry.get("updated_at") or ""),
                "duration_seconds": duration_seconds,
                "artifact_url": f"/projects/{visible_project_id}/artifact?path={quote(str(resolved), safe='')}&download=false",
                "project_id": visible_project_id,
            }
        )

    items.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return items


def _resolve_saved_source_audio(paths, audio_hash: str) -> tuple[Path, str]:
    for entry in _load_source_audio_index(paths):
        if str(entry.get("audio_hash") or "") != audio_hash:
            continue
        audio_path = Path(str(entry.get("audio_path") or ""))
        if audio_path.exists():
            return audio_path, str(entry.get("source_filename") or audio_path.name)
    raise HTTPException(status_code=404, detail="saved source audio not found")


def _worker_availability_snapshot() -> dict[str, int | str | None]:
    workers = worker_manager.list_workers()
    online = 0
    latest_live_seen_at: datetime | None = None
    now = datetime.now(timezone.utc)
    for worker in workers:
        raw_seen = worker.last_seen_at
        if not raw_seen:
            continue
        try:
            seen_at = datetime.fromisoformat(raw_seen)
        except ValueError:
            continue
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (now - seen_at).total_seconds())
        if age_seconds <= WORKER_ONLINE_WINDOW_SECONDS:
            online += 1
            if latest_live_seen_at is None or seen_at > latest_live_seen_at:
                latest_live_seen_at = seen_at
    stale = max(0, len(workers) - online)
    return {
        "worker_total_count": len(workers),
        "worker_online_count": online,
        "worker_live_count": online,
        "worker_registered_count": len(workers),
        "worker_stale_count": stale,
        "worker_online_window_seconds": WORKER_ONLINE_WINDOW_SECONDS,
        "worker_last_live_seen_at": latest_live_seen_at.isoformat() if latest_live_seen_at else None,
    }


def _update_job(
    paths: Path,
    *,
    job_id: str,
    status: JobStatus | None = None,
    stage: str | None = None,
    progress: float | None = None,
    eta_seconds: int | None | object = _UNSET,
    log: str | None = None,
    error: str | None = None,
    outputs: dict[str, str] | None = None,
) -> None:
    with _job_update_lock:
        job = _read_job(paths, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if eta_seconds is not _UNSET:
            job.eta_seconds = None if eta_seconds is None else max(0, int(eta_seconds))
        if log:
            previous = ""
            if job.logs:
                previous = job.logs[-1].split(" ", 1)[1] if " " in job.logs[-1] else job.logs[-1]
            if log != previous:
                job.logs.append(f"{now_utc_iso()} {log}")
        if error is not None:
            job.error = error
        if outputs is not None:
            job.outputs = outputs
        _upsert_job(paths, job)


def _run_enhancement_job(
    *,
    scoped_project_id: str,
    visible_project_id: str,
    job_id: str,
    input_audio_path: Path,
    input_audio_filename: str,
    output_name: str,
    output_format: OutputFormat,
    enhancement_model: EnhancementModel,
    caption_format: CaptionFormat | None = None,
    caption_quality_mode: CaptionQualityMode = CaptionQualityMode.ACCURATE,
    caption_glossary: str | None = None,
    max_silence_seconds: float | None = None,
    remove_filler_words: bool = False,
    filler_removal_mode: FillerRemovalMode = FillerRemovalMode.AGGRESSIVE,
) -> None:
    paths = project_manager.ensure_project(scoped_project_id)
    manifests_dir = paths.manifests
    cleanup_requested = speech_cleanup_service.cleanup_requested(max_silence_seconds, remove_filler_words)
    caption_requested = caption_format is not None
    postprocess_requested = cleanup_requested or caption_requested
    cleanup_eta_seconds = None
    if cleanup_requested:
        try:
            cleanup_eta_seconds = estimate_speech_cleanup_seconds(
                probe_duration_seconds(input_audio_path),
                remove_filler_words=remove_filler_words,
                filler_removal_mode=filler_removal_mode,
            )
        except Exception:
            cleanup_eta_seconds = None
    caption_eta_seconds = None
    if caption_requested:
        try:
            caption_eta_seconds = speech_cleanup_service.estimate_caption_runtime_seconds(
                probe_duration_seconds(input_audio_path),
                quality_mode=caption_quality_mode,
            )
        except Exception:
            caption_eta_seconds = None

    def on_stage(stage: str, progress: float, detail: str, eta_seconds: int | None = None) -> None:
        _update_job(
            manifests_dir,
            job_id=job_id,
            status=JobStatus.RUNNING,
            stage=stage,
            progress=map_local_stage_progress(stage, progress, reserve_cleanup_band=postprocess_requested),
            eta_seconds=extend_eta_with_postprocess(
                eta_seconds,
                cleanup_eta_seconds,
                caption_eta_seconds,
                reserve_postprocess_band=postprocess_requested and stage in {"prepare", "enhance", "finalize"},
            ),
            log=detail,
        )

    try:
        prepare_detail = (
            "Preparing source audio without enhancement."
            if enhancement_model == EnhancementModel.NONE
            else f"Preparing enhancement with {enhancement_model.value}"
        )
        on_stage("prepare", 0.08, prepare_detail)
        output_base = paths.assets_enhanced_audio / output_name
        final_path = enhance_service.enhance(
            job_id=job_id,
            enhancement_model=enhancement_model,
            input_audio_path=input_audio_path,
            output_format=output_format,
            output_base_path=output_base,
            on_stage=on_stage,
            cancel_check=lambda: _cancel_requested(job_id),
        )

        if _cancel_requested(job_id):
            raise JobCancelledError("job cancelled")

        cleanup_result = None
        cleanup_result = speech_cleanup_service.cleanup_audio_file(
            audio_path=final_path,
            output_format=output_format,
            max_silence_seconds=max_silence_seconds,
            remove_filler_words=remove_filler_words,
            filler_removal_mode=filler_removal_mode,
            on_stage=lambda progress, detail, eta_seconds: _update_job(
                manifests_dir,
                job_id=job_id,
                status=JobStatus.RUNNING,
                stage="cleanup",
                progress=map_postprocess_stage_progress(
                    progress,
                    stage="cleanup",
                    cleanup_requested=cleanup_requested,
                    caption_requested=caption_requested,
                ),
                eta_seconds=extend_eta_with_postprocess(
                    eta_seconds,
                    None,
                    caption_eta_seconds,
                    reserve_postprocess_band=caption_requested,
                ),
                log=detail,
            ),
            cancel_check=lambda: _cancel_requested(job_id),
        )

        caption_result = None
        if caption_requested and caption_format is not None:
            caption_result = speech_cleanup_service.generate_caption_file(
                audio_path=final_path,
                caption_format=caption_format,
                caption_quality_mode=caption_quality_mode,
                caption_glossary=(str(caption_glossary or "").strip() or None),
                on_stage=lambda progress, detail, eta_seconds: _update_job(
                    manifests_dir,
                    job_id=job_id,
                    status=JobStatus.RUNNING,
                    stage="captions",
                    progress=map_postprocess_stage_progress(
                        progress,
                        stage="captions",
                        cleanup_requested=cleanup_requested,
                        caption_requested=caption_requested,
                    ),
                    eta_seconds=eta_seconds,
                    log=detail,
                ),
                cancel_check=lambda: _cancel_requested(job_id),
            )

        duration_seconds = cleanup_result.duration_seconds
        metadata = OutputMetadata(
            output_file=final_path,
            input_file=input_audio_path,
            duration_seconds=duration_seconds,
            output_format=output_format,
            caption_file=caption_result.caption_path if caption_result else None,
            caption_review_file=getattr(caption_result, "review_path", None) if caption_result else None,
            caption_format=caption_format,
            caption_quality_mode=caption_quality_mode,
            caption_glossary=(str(caption_glossary or "").strip() or None),
            caption_review_required=bool(
                caption_result
                and getattr(caption_result, "quality_report", None)
                and getattr(caption_result.quality_report, "review_recommended", False)
            ),
            caption_average_probability=(
                getattr(caption_result.quality_report, "average_probability", None)
                if caption_result and getattr(caption_result, "quality_report", None)
                else None
            ),
            caption_low_confidence_segments=(
                getattr(caption_result.quality_report, "low_confidence_segment_count", 0)
                if caption_result and getattr(caption_result, "quality_report", None)
                else 0
            ),
            caption_total_segments=(
                getattr(caption_result.quality_report, "total_segment_count", 0)
                if caption_result and getattr(caption_result, "quality_report", None)
                else 0
            ),
            enhancement_model=enhancement_model,
            audio_tuning_label=enhance_service.output_tuning_label_for_model(enhancement_model),
            max_silence_seconds=max_silence_seconds,
            remove_filler_words=remove_filler_words,
            filler_removal_mode=filler_removal_mode,
            project_id=scoped_project_id,
            job_id=job_id,
        )
        metadata_path = _append_output(manifests_dir, metadata)

        encoded_audio = quote(str(final_path), safe="")
        outputs = {
            "audio_path": str(final_path),
            "metadata_path": str(metadata_path),
            "audio_download_url": f"/projects/{visible_project_id}/artifact?path={encoded_audio}&download=true",
            "audio_play_url": f"/projects/{visible_project_id}/artifact?path={encoded_audio}&download=false",
        }
        if caption_result is not None:
            encoded_caption = quote(str(caption_result.caption_path), safe="")
            outputs["caption_path"] = str(caption_result.caption_path)
            outputs["caption_download_url"] = (
                f"/projects/{visible_project_id}/artifact?path={encoded_caption}&download=true"
            )
            outputs["caption_format"] = caption_result.caption_format.value
            review_path = getattr(caption_result, "review_path", None)
            if review_path is not None:
                encoded_review = quote(str(review_path), safe="")
                outputs["caption_review_path"] = str(review_path)
                outputs["caption_review_download_url"] = (
                    f"/projects/{visible_project_id}/artifact?path={encoded_review}&download=true"
                )
        _update_job(
            manifests_dir,
            job_id=job_id,
            status=JobStatus.COMPLETED,
            stage="completed",
            progress=1.0,
            eta_seconds=None,
            log=_completed_output_log(
                enhancement_model=enhancement_model,
                cleanup_result=cleanup_result,
                caption_format=caption_result.caption_format if caption_result else None,
            ),
            outputs=outputs,
        )
    except JobCancelledError as exc:
        _update_job(
            manifests_dir,
            job_id=job_id,
            status=JobStatus.CANCELLED,
            stage="cancelled",
            progress=0.0,
            eta_seconds=None,
            error=str(exc),
            log="Job cancelled",
        )
    except EnhancementRuntimeError as exc:
        _update_job(
            manifests_dir,
            job_id=job_id,
            status=JobStatus.FAILED,
            stage="failed",
            progress=1.0,
            eta_seconds=None,
            error=str(exc),
            log="Enhancement failed",
        )
    except Exception as exc:  # noqa: BLE001
        _update_job(
            manifests_dir,
            job_id=job_id,
            status=JobStatus.FAILED,
            stage="failed",
            progress=1.0,
            eta_seconds=None,
            error=str(exc),
            log="Unexpected enhancement failure",
        )
    finally:
        _cancelled_jobs.discard(job_id)


def _run_local_enhancement_from_worker_payload(
    *,
    worker_payload: WorkerEnhanceEnqueueRequest,
    job_id: str,
) -> None:
    paths = project_manager.ensure_project(worker_payload.project_id)
    source_filename = _safe_filename(worker_payload.input_audio_filename)
    source_ext = _safe_audio_extension(source_filename)
    input_hash = hashlib.sha256(worker_payload.input_audio_b64.encode("utf-8")).hexdigest()
    input_audio_path = paths.assets_source_audio / f"source-{input_hash[:16]}{source_ext}"
    input_audio_path.parent.mkdir(parents=True, exist_ok=True)
    if not input_audio_path.exists():
        input_audio_path.write_bytes(base64.b64decode(worker_payload.input_audio_b64.encode("utf-8")))
    _upsert_source_audio(
        paths=paths,
        audio_hash=input_hash,
        audio_path=input_audio_path,
        source_filename=source_filename,
    )
    _run_enhancement_job(
        scoped_project_id=worker_payload.project_id,
        visible_project_id=_display_project_id(worker_payload.project_id),
        job_id=job_id,
        input_audio_path=input_audio_path,
        input_audio_filename=source_filename,
        output_name=str(worker_payload.output_name or _build_output_name(source_filename, None)),
        output_format=worker_payload.output_format,
        caption_format=worker_payload.caption_format,
        caption_quality_mode=worker_payload.caption_quality_mode,
        caption_glossary=worker_payload.caption_glossary,
        enhancement_model=worker_payload.enhancement_model,
        max_silence_seconds=worker_payload.max_silence_seconds,
        remove_filler_words=worker_payload.remove_filler_words,
        filler_removal_mode=worker_payload.filler_removal_mode,
    )


def _run_claimed_fallback_job(job_id: str, *, reason: str, allowed_statuses: set[str] | None = None) -> bool:
    worker_payload = worker_manager.claim_job_for_local_fallback(
        job_id,
        reason=reason,
        allowed_statuses=allowed_statuses,
    )
    if worker_payload is None:
        return False
    thread = threading.Thread(
        target=lambda: _run_local_enhancement_from_worker_payload(worker_payload=worker_payload, job_id=job_id),
        name=f"radcast-fallback-{job_id}",
        daemon=True,
    )
    thread.start()
    return True


def _schedule_worker_fallback_watch(job_id: str) -> None:
    if not WORKER_FALLBACK_ENABLED:
        return

    def watcher() -> None:
        time.sleep(WORKER_FALLBACK_TIMEOUT_SECONDS)
        _run_claimed_fallback_job(
            job_id,
            reason=f"No worker accepted this job after {WORKER_FALLBACK_TIMEOUT_SECONDS}s. Switching to local server fallback.",
            allowed_statuses={"queued"},
        )

    import time

    threading.Thread(target=watcher, name=f"radcast-worker-watch-{job_id}", daemon=True).start()


def _maybe_trigger_worker_fallback(job: dict[str, object]) -> bool:
    if not WORKER_FALLBACK_ENABLED:
        return False
    job_id = str(job.get("id") or "")
    status = str(job.get("status") or "").lower()
    stage = str(job.get("stage") or "").lower()
    if not job_id:
        return False
    if status == "queued" and stage == "queued_remote":
        created_raw = str(job.get("created_at") or "")
        try:
            created_at = datetime.fromisoformat(created_raw)
        except ValueError:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())
        if age_seconds >= WORKER_FALLBACK_TIMEOUT_SECONDS:
            return _run_claimed_fallback_job(
                job_id,
                reason=f"No worker accepted this job after {WORKER_FALLBACK_TIMEOUT_SECONDS}s. Switching to local server fallback.",
                allowed_statuses={"queued"},
            )
    return False


@app.get("/auth/bridge")
def auth_bridge(request: Request, token: str):
    try:
        payload = _bridge_serializer().loads(token, max_age=BRIDGE_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(status_code=401, detail="bridge token expired") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="invalid bridge token") from exc

    request.session["user"] = {
        "sub": payload.get("sub"),
        "email": payload.get("email"),
        "display_name": payload.get("display_name"),
        "is_admin": bool(payload.get("is_admin", False)),
        "issuer": payload.get("issuer"),
    }
    return RedirectResponse(url="/", status_code=302)


@app.get("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return _login_redirect()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if AUTH_REQUIRED and _current_user(request) is None:
        return _login_redirect()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "auth_required": AUTH_REQUIRED,
            "current_user": _current_user(request),
            "psychek_app_url": PSYCHEK_APP_URL,
            "psychek_admin_url": PSYCHEK_ADMIN_URL,
            "radtts_app_url": RADTTS_APP_URL,
        },
    )


@app.post("/projects")
def create_project(request: Request, req: ProjectCreateRequest):
    _require_auth(request)
    scoped_project_id = _scope_project_id(request, req.project_id)
    paths = project_manager.create_project(
        scoped_project_id,
        course=req.course,
        module=req.module,
        lesson=req.lesson,
    )
    _bootstrap_owner_access_if_missing(request, scoped_project_id)
    return {
        "project_root": str(paths.root),
        "project_id": req.project_id,
        "project_ref": scoped_project_id,
    }


@app.post("/projects/{project_id}/source-audio")
def upload_source_audio(request: Request, project_id: str, req: ProjectSourceAudioUploadRequest):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    paths = project_manager.ensure_project(scoped_project_id)

    try:
        audio_bytes = base64.b64decode(req.audio_b64.encode("utf-8"), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="invalid audio_b64 payload") from exc

    audio_hash = hashlib.sha256(audio_bytes).hexdigest()
    ext = _safe_audio_extension(req.filename)
    output_path = paths.assets_source_audio / f"source-{audio_hash[:16]}{ext}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_bytes(audio_bytes)

    entry = _upsert_source_audio(
        paths=paths,
        audio_hash=audio_hash,
        audio_path=output_path,
        source_filename=req.filename,
    )

    return {
        "project_id": _display_project_id(scoped_project_id),
        "audio_hash": audio_hash,
        "filename": output_path.name,
        "saved_path": str(output_path),
        "duration_seconds": entry.get("duration_seconds"),
        "artifact_url": f"/projects/{_display_project_id(scoped_project_id)}/artifact?path={quote(str(output_path), safe='')}&download=false",
    }


@app.get("/projects/{project_id}/source-audio")
def list_source_audio(request: Request, project_id: str):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    project_manager.ensure_project(scoped_project_id)
    return {
        "project_id": _display_project_id(scoped_project_id),
        "samples": _list_source_audio_entries(request, scoped_project_id=scoped_project_id),
    }


@app.post("/projects/{project_id}/source-audio/delete")
def delete_source_audio(request: Request, project_id: str, req: ProjectSourceAudioDeleteRequest):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    paths = project_manager.ensure_project(scoped_project_id)

    audio_hash = req.audio_hash.strip().lower()
    items = _load_source_audio_index(paths)
    entry = next((item for item in items if str(item.get("audio_hash") or "").strip().lower() == audio_hash), None)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="saved audio file not found")

    saved_path = str(entry.get("audio_path") or "")
    next_items = [item for item in items if str(item.get("audio_hash") or "").strip().lower() != audio_hash]
    _write_source_audio_index(paths, next_items)

    removed_file = False
    if saved_path:
        candidate_path = Path(saved_path)
        try:
            resolved = candidate_path.resolve()
            resolved.relative_to(paths.root.resolve())
        except (FileNotFoundError, ValueError):
            resolved = None
        if resolved is not None and resolved.exists():
            resolved.unlink(missing_ok=True)
            removed_file = True

    return {
        "project_id": _display_project_id(scoped_project_id),
        "deleted": True,
        "audio_hash": audio_hash,
        "removed_file": removed_file,
    }


@app.get("/projects/{project_id}/settings")
def get_project_settings(request: Request, project_id: str):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    project_manager.ensure_project(scoped_project_id)
    settings = _load_project_settings(scoped_project_id)
    return {
        "project_id": _display_project_id(scoped_project_id),
        "project_ref": scoped_project_id,
        "settings": settings.model_dump(mode="json"),
    }


@app.put("/projects/{project_id}/settings")
def update_project_settings(request: Request, project_id: str, req: ProjectUiSettings):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    project_manager.ensure_project(scoped_project_id)
    settings = _write_project_settings(scoped_project_id, req)
    return {
        "project_id": _display_project_id(scoped_project_id),
        "project_ref": scoped_project_id,
        "settings": settings.model_dump(mode="json"),
    }


@app.get("/projects")
def list_projects(request: Request):
    _require_auth(request)
    projects: list[tuple[datetime, dict[str, object]]] = []
    for scoped_project_id in project_manager.list_projects():
        access = _resolve_access_for_user(request, scoped_project_id)
        if not bool(access.get("can_access")):
            continue

        visible_project_id = _display_project_id(scoped_project_id)
        owner = access.get("owner") if isinstance(access.get("owner"), dict) else {}
        owner_label = str(owner.get("display_name") or owner.get("email") or owner.get("user_key") or "")
        last_activity_at = _project_last_activity_at(scoped_project_id)
        projects.append(
            (
                last_activity_at,
                {
                    "project_id": visible_project_id,
                    "project_ref": scoped_project_id,
                    "shared": not bool(access.get("is_owner")),
                    "owner_label": owner_label,
                    "updated_at": last_activity_at.isoformat(),
                },
            )
        )

    projects.sort(key=lambda item: (item[0], str(item[1].get("project_id") or "")), reverse=True)
    return {"projects": [payload for _, payload in projects]}


@app.get("/projects/{project_id}/access")
def get_project_access(request: Request, project_id: str):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    access = _resolve_access_for_user(request, scoped_project_id)
    owner = access.get("owner") if isinstance(access.get("owner"), dict) else {}
    collaborators = access.get("collaborators") if isinstance(access.get("collaborators"), list) else []
    return {
        "project_id": _display_project_id(scoped_project_id),
        "project_ref": scoped_project_id,
        "can_manage": bool(access.get("can_manage")),
        "owner": {
            "display_name": str(owner.get("display_name") or ""),
            "email": str(owner.get("email") or ""),
        },
        "collaborators": collaborators,
    }


@app.get("/projects/{project_id}/shareable-users")
def get_project_shareable_users(request: Request, project_id: str):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    access = _resolve_access_for_user(request, scoped_project_id)
    if not bool(access.get("can_manage")):
        raise HTTPException(status_code=403, detail="project access denied")

    current_user = _current_user(request) or {}
    exclude_email = str(current_user.get("email") or "").strip().lower()
    return {
        "project_id": _display_project_id(scoped_project_id),
        "project_ref": scoped_project_id,
        "users": _fetch_shareable_users(exclude_email=exclude_email),
    }


@app.post("/projects/{project_id}/access/grant")
def grant_project_access(request: Request, project_id: str, req: ProjectAccessGrantRequest):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    access = _resolve_access_for_user(request, scoped_project_id)
    if not bool(access.get("can_manage")):
        raise HTTPException(status_code=403, detail="project access denied")

    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="valid email is required")

    access_doc = _load_project_access(scoped_project_id)
    owner = access_doc.get("owner") if isinstance(access_doc.get("owner"), dict) else {}
    owner_email = str(owner.get("email") or "").strip().lower()
    if owner_email and email == owner_email:
        return {
            "project_id": _display_project_id(scoped_project_id),
            "project_ref": scoped_project_id,
            "collaborators": access_doc.get("collaborators", []),
            "updated": False,
        }

    collaborators_raw = access_doc.get("collaborators") if isinstance(access_doc.get("collaborators"), list) else []
    collaborators: list[dict[str, str]] = []
    found = False
    current_user = _current_user(request) or {}
    granted_by = str(current_user.get("email") or current_user.get("sub") or "").strip()
    for row in collaborators_raw:
        if not isinstance(row, dict):
            continue
        existing_email = str(row.get("email") or "").strip().lower()
        if not existing_email:
            continue
        if existing_email == email:
            found = True
            collaborators.append(
                {
                    "email": existing_email,
                    "granted_at": str(row.get("granted_at") or datetime.now(timezone.utc).isoformat()),
                    "granted_by": str(row.get("granted_by") or granted_by),
                }
            )
        else:
            collaborators.append(
                {
                    "email": existing_email,
                    "granted_at": str(row.get("granted_at") or ""),
                    "granted_by": str(row.get("granted_by") or ""),
                }
            )

    if not found:
        collaborators.append(
            {
                "email": email,
                "granted_at": datetime.now(timezone.utc).isoformat(),
                "granted_by": granted_by,
            }
        )

    access_doc["collaborators"] = collaborators
    access_doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_project_access(scoped_project_id, access_doc)

    return {
        "project_id": _display_project_id(scoped_project_id),
        "project_ref": scoped_project_id,
        "collaborators": collaborators,
        "updated": not found,
    }


@app.post("/projects/{project_id}/access/revoke")
def revoke_project_access(request: Request, project_id: str, req: ProjectAccessRevokeRequest):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    access = _resolve_access_for_user(request, scoped_project_id)
    if not bool(access.get("can_manage")):
        raise HTTPException(status_code=403, detail="project access denied")

    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="valid email is required")

    access_doc = _load_project_access(scoped_project_id)
    collaborators_raw = access_doc.get("collaborators") if isinstance(access_doc.get("collaborators"), list) else []
    collaborators = [
        {
            "email": str(row.get("email") or "").strip().lower(),
            "granted_at": str(row.get("granted_at") or ""),
            "granted_by": str(row.get("granted_by") or ""),
        }
        for row in collaborators_raw
        if isinstance(row, dict)
        and str(row.get("email") or "").strip().lower()
        and str(row.get("email") or "").strip().lower() != email
    ]

    access_doc["collaborators"] = collaborators
    access_doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_project_access(scoped_project_id, access_doc)

    return {
        "project_id": _display_project_id(scoped_project_id),
        "project_ref": scoped_project_id,
        "collaborators": collaborators,
        "updated": True,
    }


@app.post("/enhance/simple")
def enhance_simple(request: Request, req: SimpleEnhanceRequest):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, req.project_id)
    paths = project_manager.ensure_project(scoped_project_id)
    selected_model = EnhancementModel(req.enhancement_model)
    if not enhance_service.is_model_available(selected_model):
        raise HTTPException(status_code=503, detail=f"{selected_model.value} is not available on this machine")
    if req.speech_cleanup_requested() or req.caption_requested():
        cleanup_available, cleanup_detail = speech_cleanup_service.capability_status()
        if not cleanup_available:
            raise HTTPException(status_code=503, detail=cleanup_detail)
    input_audio_path: Path
    input_audio_filename: str
    input_audio_bytes: bytes

    if req.input_audio_hash:
        input_audio_path, input_audio_filename = _resolve_saved_source_audio(paths, req.input_audio_hash)
        input_audio_bytes = input_audio_path.read_bytes()
    else:
        try:
            input_audio_bytes = base64.b64decode((req.input_audio_b64 or "").encode("utf-8"), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="invalid input_audio_b64 payload") from exc
        input_audio_filename = str(req.input_audio_filename or "audio.wav")
        input_hash = hashlib.sha256(input_audio_bytes).hexdigest()
        input_ext = _safe_audio_extension(input_audio_filename)
        input_audio_path = paths.assets_source_audio / f"source-{input_hash[:16]}{input_ext}"
        input_audio_path.parent.mkdir(parents=True, exist_ok=True)
        if not input_audio_path.exists():
            input_audio_path.write_bytes(input_audio_bytes)
        _upsert_source_audio(
            paths=paths,
            audio_hash=input_hash,
            audio_path=input_audio_path,
            source_filename=input_audio_filename,
        )

    output_name = _build_output_name(input_audio_filename, req.output_name)
    worker_manager.cancel_project_jobs(scoped_project_id, reason="superseded by a newer request")
    worker_req = WorkerEnhanceEnqueueRequest(
        project_id=scoped_project_id,
        input_audio_b64=base64.b64encode(input_audio_bytes).decode("utf-8"),
        input_audio_filename=input_audio_filename,
        output_name=output_name,
        output_format=req.output_format,
        caption_format=req.caption_format,
        caption_quality_mode=req.caption_quality_mode,
        caption_glossary=(str(req.caption_glossary or "").strip() or None),
        enhancement_model=selected_model,
        max_silence_seconds=req.max_silence_seconds,
        remove_filler_words=req.remove_filler_words,
        filler_removal_mode=req.filler_removal_mode,
    )
    job_id = worker_manager.enqueue_enhance_job(worker_req)
    worker_snapshot = _worker_availability_snapshot()
    if WORKER_FALLBACK_ENABLED:
        _schedule_worker_fallback_watch(job_id)
    return {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued_remote",
        "progress": 0.0,
        "project_id": _display_project_id(scoped_project_id),
        "output_name": output_name,
        "enhancement_model": selected_model.value,
        "worker_mode": True,
        "worker_fallback_timeout_seconds": WORKER_FALLBACK_TIMEOUT_SECONDS if WORKER_FALLBACK_ENABLED else 0,
        **worker_snapshot,
    }


@app.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str, project_id: str = Query(..., min_length=2)):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    paths = project_manager.ensure_project(scoped_project_id)
    store = ManifestStore(paths.manifests)
    payload = store.get_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="job not found")
    if str(payload.get("project_id") or "") != scoped_project_id:
        raise HTTPException(status_code=404, detail="job not found")
    if isinstance(payload, dict):
        _maybe_trigger_worker_fallback(payload)
        payload = store.get_job(job_id) or payload
    return payload


@app.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str, project_id: str = Query(..., min_length=2)):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    paths = project_manager.ensure_project(scoped_project_id)

    _cancelled_jobs.add(job_id)
    enhance_service.cancel(job_id)
    worker_manager.cancel_job(job_id, reason="Cancellation requested.")

    _update_job(
        paths.manifests,
        job_id=job_id,
        status=JobStatus.CANCELLED,
        stage="cancelled",
        progress=0.0,
        log="Cancellation requested",
        error="job cancelled",
    )

    return {
        "job_id": job_id,
        "project_id": _display_project_id(scoped_project_id),
        "status": "cancel_requested",
        "requested_at": now_utc_iso(),
    }


@app.get("/projects/{project_id}/outputs")
def list_project_outputs(request: Request, project_id: str):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    paths = project_manager.ensure_project(scoped_project_id)
    store = ManifestStore(paths.manifests)

    outputs: list[dict[str, object]] = []
    rows = store.list_outputs()
    total_outputs = len(rows)
    for reverse_index, item in enumerate(reversed(rows)):
        try:
            output_path = str(item.get("output_file") or "")
            if not output_path:
                continue
            encoded_path = quote(output_path, safe="")
            suffix = Path(output_path).suffix.lower().replace(".", "") or "wav"
            folder_path = str(Path(output_path).parent)
            outputs.append(
                {
                    "output_name": Path(output_path).name,
                    "output_format": suffix,
                    "output_path": output_path,
                    "folder_path": folder_path,
                    "created_at": str(item.get("created_at") or ""),
                    "duration_seconds": float(item.get("duration_seconds") or 0.0),
                    "caption_format": str(item.get("caption_format") or ""),
                    "caption_review_required": bool(item.get("caption_review_required")),
                    "caption_average_probability": item.get("caption_average_probability"),
                    "caption_low_confidence_segments": int(item.get("caption_low_confidence_segments") or 0),
                    "caption_total_segments": int(item.get("caption_total_segments") or 0),
                    "enhancement_model": str(item.get("enhancement_model") or ""),
                    "audio_tuning_label": str(item.get("audio_tuning_label") or ""),
                    "version_number": total_outputs - reverse_index,
                    "download_url": f"/projects/{project_id}/artifact?path={encoded_path}&download=true",
                    "play_url": f"/projects/{project_id}/artifact?path={encoded_path}&download=false",
                    "caption_download_url": _artifact_download_url(project_id, item.get("caption_file")),
                    "caption_review_download_url": _artifact_download_url(project_id, item.get("caption_review_file")),
                }
            )
        except Exception:  # noqa: BLE001
            continue

    return {
        "project_id": _display_project_id(scoped_project_id),
        "outputs": outputs,
    }


@app.get("/projects/{project_id}/artifact")
def project_artifact(request: Request, project_id: str, path: str = Query(...), download: bool = Query(False)):
    _require_auth(request)
    scoped_project_id = _resolve_project_id_for_request(request, project_id)
    paths = project_manager.ensure_project(scoped_project_id)

    try:
        requested = Path(unquote(path)).resolve()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid path") from exc

    project_root = paths.root.resolve()
    if project_root != requested and project_root not in requested.parents:
        raise HTTPException(status_code=403, detail="artifact path outside project")
    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")

    media_type = _media_type_for_suffix(requested.suffix.lower())
    filename = requested.name if download else None
    return FileResponse(path=requested, media_type=media_type, filename=filename)


@app.get("/workers")
def list_workers(request: Request):
    _require_auth(request)
    workers = worker_manager.list_workers()
    return {"workers": [worker.model_dump(mode="json") for worker in workers]}


@app.get("/workers/status")
def workers_status(request: Request):
    _require_auth(request)
    return _worker_availability_snapshot()


@app.get("/enhancement/models")
def enhancement_models(request: Request):
    _require_auth(request)
    cleanup_available, cleanup_detail = speech_cleanup_service.capability_status()
    return {
        "default_model": enhance_service.default_model.value,
        "models": enhance_service.available_models(),
        "speech_cleanup": {
            "available": cleanup_available,
            "detail": cleanup_detail,
        },
    }


@app.post("/workers/invite", response_model=WorkerInviteResponse)
def worker_invite(request: Request, req: WorkerInviteRequest):
    _require_auth(request)
    token = worker_manager.issue_invite_token(req.capabilities)
    base_url = str(request.base_url).rstrip("/")
    install_command = (
        f'python3 -m pip install --upgrade "{WORKER_INSTALL_SPEC}" deepfilternet && '
        f"python3 -m radcast.worker_setup --server-url {base_url} --invite-token {token}"
    )
    install_command_windows = (
        f"py -m pip install --upgrade {WORKER_INSTALL_SPEC} deepfilternet && "
        f"py -m radcast.worker_setup --server-url {base_url} --invite-token {token} --platform windows"
    )
    install_command_macos = _macos_worker_install_command(base_url, token)
    install_command_linux = (
        'sh -lc \'if [ ! -x "$HOME/.cargo/bin/cargo" ]; then curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal; fi; '
        '. "$HOME/.cargo/env"; '
        f'python3 -m pip install --upgrade "{WORKER_INSTALL_SPEC}" deepfilternet && '
        f"python3 -m radcast.worker_setup --server-url {base_url} --invite-token {token} --platform linux"
        "'"
    )
    windows_installer_url = f"{base_url}/workers/bootstrap/windows.cmd?invite_token={quote(token)}"
    macos_installer_url = f"{base_url}/workers/bootstrap/macos.command?invite_token={quote(token)}"
    return WorkerInviteResponse(
        invite_token=token,
        expires_in_seconds=86400,
        install_command=install_command,
        install_command_windows=install_command_windows,
        install_command_macos=install_command_macos,
        install_command_linux=install_command_linux,
        windows_installer_url=windows_installer_url,
        macos_installer_url=macos_installer_url,
    )


@app.post("/workers/register")
def worker_register(req: WorkerRegisterRequest):
    return worker_manager.register_worker(req).model_dump(mode="json")


@app.post("/workers/pull", response_model=WorkerPullResponse)
def worker_pull(req: WorkerPullRequest):
    job = worker_manager.pull_job(req)
    return {"job": job.model_dump(mode="json") if job else None}


@app.post("/workers/jobs/{job_id}/complete")
def worker_complete(job_id: str, req: WorkerJobCompleteRequest):
    return {"status": worker_manager.complete_job(job_id, req)}


@app.post("/workers/jobs/{job_id}/progress")
def worker_progress(job_id: str, req: WorkerJobProgressRequest):
    return {"status": worker_manager.progress_job(job_id, req)}


@app.post("/workers/jobs/{job_id}/fail")
def worker_fail(job_id: str, req: WorkerJobFailRequest):
    return {"status": worker_manager.fail_job(job_id, req)}


@app.get("/workers/bootstrap/windows.cmd")
def worker_bootstrap_windows_cmd(request: Request, invite_token: str = Query(..., min_length=10)):
    base_url = str(request.base_url).rstrip("/")
    safe_token = quote(invite_token, safe="")
    body = (
        "@echo off\r\n"
        "echo Installing RADcast worker on this Windows device...\r\n"
        "py -m pip install --upgrade pip\r\n"
        f"py -m pip install --upgrade {WORKER_INSTALL_SPEC} deepfilternet\r\n"
        f"py -m radcast.worker_setup --server-url {base_url} --invite-token {safe_token} --platform windows\r\n"
        "echo Setup complete. You can close this window.\r\n"
    )
    response = PlainTextResponse(body, media_type="text/plain; charset=utf-8")
    response.headers["Content-Disposition"] = 'attachment; filename="radcast-worker-setup.cmd"'
    return response


@app.get("/workers/bootstrap/macos.command")
def worker_bootstrap_macos_command(request: Request, invite_token: str = Query(..., min_length=10)):
    base_url = str(request.base_url).rstrip("/")
    install_spec = WORKER_INSTALL_SPEC.replace('"', '\\"')
    body = (
        "#!/bin/bash\n"
        "set -e\n"
        "echo \"Installing RADcast worker on this Mac...\"\n"
        "BREW_PREFIX=\"$(brew --prefix)\"\n"
        "brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg\n"
        "brew list git-lfs >/dev/null 2>&1 || brew install git-lfs\n"
        "brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11\n"
        "brew list rust >/dev/null 2>&1 || brew install rust\n"
        "git lfs install\n"
        "\"$BREW_PREFIX/bin/python3.11\" -m venv \"$HOME/.radcast/venv\"\n"
        "\"$HOME/.radcast/venv/bin/python\" -m pip install --upgrade pip\n"
        f"\"$HOME/.radcast/venv/bin/python\" -m pip install --upgrade \"{install_spec}\" resemble-enhance deepfilternet\n"
        f"\"$HOME/.radcast/venv/bin/python\" -m radcast.worker_setup --server-url {base_url} --invite-token {quote(invite_token, safe='')} --platform macos\n"
        "echo \"Setup complete. You can close this window.\"\n"
    )
    response = PlainTextResponse(body, media_type="text/plain; charset=utf-8")
    response.headers["Content-Disposition"] = 'attachment; filename="radcast-worker-setup.command"'
    return response


def _media_type_for_suffix(suffix: str) -> str:
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".srt":
        return "application/x-subrip"
    if suffix == ".vtt":
        return "text/vtt"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".flac":
        return "audio/flac"
    return "application/octet-stream"


def _artifact_download_url(project_id: str, path_value: object) -> str | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    return f"/projects/{project_id}/artifact?path={quote(raw, safe='')}&download=true"


def _completed_output_log(
    *,
    enhancement_model: EnhancementModel,
    cleanup_result,
    caption_format: CaptionFormat | None,
) -> str:
    if cleanup_result and getattr(cleanup_result, "applied", False):
        base = str(cleanup_result.summary_text()).rstrip(".")
        if caption_format is not None:
            return f"{base}. Generated {caption_format.value.upper()} captions."
        return f"{base}."
    if caption_format is not None:
        prefix = "Audio processing completed" if enhancement_model == EnhancementModel.NONE else "Enhancement completed"
        return f"{prefix} and generated {caption_format.value.upper()} captions."
    return "Audio processing completed" if enhancement_model == EnhancementModel.NONE else "Enhancement completed"


def _macos_worker_install_command(base_url: str, token: str) -> str:
    safe_base_url = base_url.rstrip("/")
    safe_token = quote(token, safe="")
    install_spec = WORKER_INSTALL_SPEC.replace('"', '\\"')
    return (
        "/bin/bash -lc 'set -e; "
        'BREW_PREFIX="$(brew --prefix)"; '
        'brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg; '
        'brew list git-lfs >/dev/null 2>&1 || brew install git-lfs; '
        'brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11; '
        'brew list rust >/dev/null 2>&1 || brew install rust; '
        'git lfs install; '
        '"$BREW_PREFIX/bin/python3.11" -m venv "$HOME/.radcast/venv"; '
        '"$HOME/.radcast/venv/bin/python" -m pip install --upgrade pip; '
        f'"$HOME/.radcast/venv/bin/python" -m pip install --upgrade "{install_spec}" resemble-enhance deepfilternet; '
        f'"$HOME/.radcast/venv/bin/python" -m radcast.worker_setup --server-url {safe_base_url} --invite-token {safe_token} --platform macos'
        "'"
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("RADCAST_HOST", "127.0.0.1")
    port = int(os.environ.get("RADCAST_PORT", "8012"))
    uvicorn.run("radcast.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
