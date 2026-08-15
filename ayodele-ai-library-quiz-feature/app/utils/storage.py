"""
Wraps Supabase Storage's REST API for uploading, downloading, and deleting
course documents, so uploaded files survive Render restarts/redeploys
(Render's local disk is ephemeral on the free tier; Supabase Storage isn't).
"""
import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "documents")

_TIMEOUT = 30


class StorageError(Exception):
    pass


def _require_config():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise StorageError(
            "Supabase storage is not configured on the server "
            "(missing SUPABASE_URL or SUPABASE_SERVICE_KEY)."
        )


def upload_file(path, file_bytes, content_type="application/octet-stream"):
    """Upload (or overwrite) a file at `path` inside the configured bucket."""
    _require_config()
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }
    resp = requests.post(url, headers=headers, data=file_bytes, timeout=_TIMEOUT)
    if resp.status_code not in (200, 201):
        raise StorageError(f"Upload failed ({resp.status_code}): {resp.text}")


def download_file(path):
    """Return the raw bytes of a file stored at `path`."""
    _require_config()
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}"
    headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"}
    resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise StorageError(f"Download failed ({resp.status_code}): {resp.text}")
    return resp.content


def delete_file(path):
    """Delete a single file. Silently no-ops if storage isn't configured."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}"
    headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"}
    requests.delete(url, headers=headers, timeout=_TIMEOUT)


def delete_folder(prefix):
    """Delete every file under a folder prefix (e.g. all of a course's documents)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    list_url = f"{SUPABASE_URL}/storage/v1/object/list/{SUPABASE_BUCKET}"
    resp = requests.post(list_url, headers=headers, json={"prefix": prefix}, timeout=_TIMEOUT)
    if resp.status_code != 200:
        return

    files = resp.json()
    paths = [f"{prefix}/{f['name']}" for f in files if isinstance(f, dict) and f.get("name")]
    if not paths:
        return

    delete_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}"
    requests.delete(delete_url, headers=headers, json={"prefixes": paths}, timeout=_TIMEOUT)
