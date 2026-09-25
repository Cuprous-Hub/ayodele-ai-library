"""
Stores and retrieves uploaded course documents in Supabase Storage instead
of the local filesystem.

Why: on Render's free tier (and most hosts' free/basic tiers), the local
disk is wiped on every redeploy, so anything saved to a local uploads/
folder disappears the next time code is pushed. Supabase Storage is a
persistent, external store - the same Supabase project already used for
the database - so files survive redeploys.

Uses plain HTTP calls (via `requests`, already a dependency) rather than
the `supabase` Python package, to avoid adding a new dependency for what's
a handful of simple REST calls.
"""
import requests
from flask import current_app


class StorageError(Exception):
    pass


def _config():
    url = current_app.config.get("SUPABASE_URL", "").rstrip("/")
    key = current_app.config.get("SUPABASE_SERVICE_KEY", "")
    bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "course-documents")
    if not url or not key:
        raise StorageError(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY are not configured - "
            "set them as environment variables."
        )
    return url, key, bucket


def _headers(key, content_type=None):
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _object_path(course_id, stored_filename):
    return f"{course_id}/{stored_filename}"


def upload_file(course_id, stored_filename, file_bytes, content_type="application/octet-stream"):
    """file_bytes: raw bytes of the file to store."""
    url, key, bucket = _config()
    path = _object_path(course_id, stored_filename)
    resp = requests.post(
        f"{url}/storage/v1/object/{bucket}/{path}",
        headers=_headers(key, content_type or "application/octet-stream"),
        data=file_bytes,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise StorageError(f"Upload failed ({resp.status_code}): {resp.text}")


def download_file(course_id, stored_filename):
    """Returns the raw bytes of a stored file."""
    url, key, bucket = _config()
    path = _object_path(course_id, stored_filename)
    resp = requests.get(
        f"{url}/storage/v1/object/{bucket}/{path}", headers=_headers(key), timeout=30
    )
    if resp.status_code != 200:
        raise StorageError(f"Download failed ({resp.status_code}): {resp.text}")
    return resp.content


def delete_file(course_id, stored_filename):
    """Delete a single stored file. Not treated as fatal if it's already gone."""
    url, key, bucket = _config()
    path = _object_path(course_id, stored_filename)
    resp = requests.delete(
        f"{url}/storage/v1/object/{bucket}/{path}", headers=_headers(key), timeout=30
    )
    if resp.status_code not in (200, 404):
        raise StorageError(f"Delete failed ({resp.status_code}): {resp.text}")


def delete_course_files(course_id):
    """Delete every stored file under a course's folder - used when a whole
    course is deleted. Supabase's bulk-delete endpoint needs exact object
    paths, so the folder is listed first."""
    url, key, bucket = _config()
    prefix = f"{course_id}/"

    list_resp = requests.post(
        f"{url}/storage/v1/object/list/{bucket}",
        headers=_headers(key, "application/json"),
        json={"prefix": prefix},
        timeout=30,
    )
    if list_resp.status_code != 200:
        return  # nothing to clean up, or the listing failed - not fatal

    names = [f"{prefix}{item['name']}" for item in list_resp.json()]
    if not names:
        return

    requests.delete(
        f"{url}/storage/v1/object/{bucket}",
        headers=_headers(key, "application/json"),
        json={"prefixes": names},
        timeout=30,
    )
