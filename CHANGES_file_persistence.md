# Fixing erased documents/notes on every push

## Root cause (two separate problems)

1. **The whole database could be resetting.** The app falls back to a
   local SQLite file if `DATABASE_URL` isn't set. That file lives on
   Render's disk, which is wiped on every redeploy — so without
   `DATABASE_URL` set, *everything* (users, courses, document text,
   summaries) resets on every push, not just files.
2. **Uploaded files (PDF/DOCX/PPTX) were saved to local disk.** Even with
   the database fixed, the actual uploaded files lived in an `uploads/`
   folder on Render's disk — also wiped on every redeploy.

## What to do about #1 (do this regardless)

In Render → your service → Environment, add `DATABASE_URL` set to your
Supabase Postgres connection string (Supabase → Project Settings →
Database → Connection string → "Connection pooling" URI is usually the
right one for Render). Redeploy once. This alone stops the database from
resetting. It does **not** recover data already lost from past resets.

## What was changed for #2 (Supabase Storage)

Since you're on Render's free tier, a persistent disk isn't an option, so
files are now stored in Supabase Storage instead of locally:

- **utils/file_storage.py** (new) — upload/download/delete calls to
  Supabase Storage's REST API, using `requests` (no new dependency).
- **config.py** — added `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
  `SUPABASE_STORAGE_BUCKET` (see `.env.example` for where to get these).
- **blueprints/teacher.py** — upload, resummarize, delete-document, and
  delete-course now read/write/delete through `file_storage.py` instead
  of the local disk. Text extraction (`extract_text`) works unchanged,
  since pypdf/python-docx/python-pptx all accept an in-memory stream just
  as well as a file path.
- **app.py** — the document download route now fetches bytes from
  Supabase Storage and serves them with `send_file`, instead of
  `send_from_directory` off local disk.

## Setup steps (do this before your next deploy)

1. In your Supabase project: **Storage → New bucket**. Any name works —
   just set `SUPABASE_STORAGE_BUCKET` to match (defaults to
   `course-documents` if you don't set it).
2. In Supabase: **Project Settings → API → service_role key** (not the
   anon key — the service role key is needed since there's no logged-in
   Supabase user here).
3. In Render → Environment, add:
   - `SUPABASE_URL` = your Supabase project URL
   - `SUPABASE_SERVICE_KEY` = the service_role key from step 2
   - `SUPABASE_STORAGE_BUCKET` = the bucket name from step 1
4. Push and redeploy. New uploads will go to Supabase Storage and survive
   every future push.

Note: any documents uploaded *before* this change are already gone from
Render's disk (per the root cause above) — their extracted text/summary
may still be in the database if `DATABASE_URL` was set at the time, but
the original files themselves can't be recovered. Teachers will need to
re-upload existing course documents once after this change goes live.
