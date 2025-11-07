import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PHOTOS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "data", "photos"))
STUDENTS_DIR = os.path.join(PHOTOS_DIR, "students")
TEACHERS_DIR = os.path.join(PHOTOS_DIR, "teachers")

os.makedirs(STUDENTS_DIR, exist_ok=True)
os.makedirs(TEACHERS_DIR, exist_ok=True)


def _safe_id(doc_id: str) -> str:
    # allow alnum, dash and underscore only
    return "".join(c for c in (doc_id or "") if (c.isalnum() or c in "-_"))


def save_profile_photo(doc_id: str, role: str, img_bytes: bytes) -> str:
    """Save image bytes to local photos folder and return a local URL path.

    role: "students" or "teachers"
    returns path like: /images/{role}/{docid}.jpg (or empty string on failure)
    """
    if not doc_id or not img_bytes:
        return ""
    safe = _safe_id(doc_id)
    if not safe:
        return ""
    folder = TEACHERS_DIR if role == "teachers" else STUDENTS_DIR
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{safe}.jpg")
        # If the file already exists, preserve it and do not overwrite.
        if os.path.exists(path):
            return f"/photos/{role}/{safe}.jpg"
        # write bytes atomically for new files
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(img_bytes)
        os.replace(tmp, path)
        return f"/photos/{role}/{safe}.jpg"
    except Exception:
        return ""


@router.get("/images/{role}/{docid}.jpg")
def get_image(role: str, docid: str):
    safe = _safe_id(docid)
    if not safe:
        raise HTTPException(status_code=404)
    path = os.path.join(TEACHERS_DIR if role == "teachers" else STUDENTS_DIR, f"{safe}.jpg")
    path = os.path.abspath(path)
    # ensure path is inside PHOTOS_DIR
    if not path.startswith(os.path.abspath(PHOTOS_DIR)):
        raise HTTPException(status_code=404)
    if os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    # not found
    raise HTTPException(status_code=404)


@router.get("/photos/{role}/{docid}.jpg")
def get_photo(role: str, docid: str):
    safe = _safe_id(docid)
    if not safe:
        raise HTTPException(status_code=404)
    path = os.path.join(TEACHERS_DIR if role == "teachers" else STUDENTS_DIR, f"{safe}.jpg")
    path = os.path.abspath(path)
    # ensure path is inside PHOTOS_DIR
    if not path.startswith(os.path.abspath(PHOTOS_DIR)):
        raise HTTPException(status_code=404)
    if os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    # not found
    raise HTTPException(status_code=404)
