"""
Sends extracted document text to Groq's chat completions API and asks for a
structured summary (overview, key topics, key terms) that the templates can
render directly.
"""
import json
import re
import requests
from flask import current_app

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Keep prompts well inside the model's context window. For a secondary
# school course document this is generous; very long textbooks would need
# chunking, which is a good future improvement.
MAX_CHARS = 18000
QUIZ_MAX_CHARS = 10000


SYSTEM_PROMPT = (
    "You are an assistant that helps secondary school students understand "
    "their course material. You will be given the raw text extracted from "
    "a teacher's uploaded document (which may be a course outline, lecture "
    "note, or slide deck). Respond with ONLY valid JSON, no markdown fences, "
    "no extra commentary, matching exactly this shape:\n"
    '{"overview": "2-4 sentence plain-language summary of what this '
    'document covers", '
    '"key_topics": ["short topic 1", "short topic 2", "..."], '
    '"key_terms": [{"term": "term name", "definition": "one sentence '
    'definition a student can understand"}]}\n'
    "Keep overview concise. Include 4-10 key_topics. Include 3-8 key_terms "
    "(only include terms that are genuinely important; if the document has "
    "no clear technical terms, return an empty list for key_terms)."
)


QA_SYSTEM_PROMPT = (
    "You are a study helper for a secondary school student. You will be "
    "given the text of a document their teacher uploaded, plus a question "
    "from the student. Answer using ONLY information found in the document "
    "text. If the document does not contain the answer, say so plainly "
    "instead of guessing or using outside knowledge. Keep answers clear and "
    "appropriately concise for a secondary school student - normally 2 to 5 "
    "sentences, longer only if the question genuinely needs it. Do not "
    "invent facts that are not in the document."
)


class SummarizationError(Exception):
    pass


def _require_api_key():
    api_key = current_app.config.get("GROQ_API_KEY")
    if not api_key:
        raise SummarizationError(
            "GROQ_API_KEY is not configured on the server. Ask whoever set "
            "up the site to add it to the .env file."
        )
    return api_key


def _call_groq(api_key, messages, temperature, max_tokens):
    payload = {
        "model": current_app.config.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SummarizationError(f"Could not reach the AI service: {exc}") from exc

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise SummarizationError("The AI service returned an unexpected response.") from exc


def summarize_document(title, full_text):
    api_key = _require_api_key()

    if not full_text or not full_text.strip():
        raise SummarizationError(
            "No readable text was found in this file, so it can't be "
            "summarized. It may be a scanned image without selectable text."
        )

    trimmed = full_text.strip()[:MAX_CHARS]

    raw_content = _call_groq(
        api_key,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f'Document title: "{title}"\n\nDocument text:\n{trimmed}',
            },
        ],
        temperature=0.3,
        max_tokens=1500,
    )

    return _parse_summary_json(raw_content)


def answer_question(title, full_text, question):
    api_key = _require_api_key()

    if not full_text or not full_text.strip():
        raise SummarizationError(
            "This document has no readable text to answer questions from."
        )
    question = (question or "").strip()
    if not question:
        raise SummarizationError("Please enter a question.")

    trimmed = full_text.strip()[:MAX_CHARS]

    answer = _call_groq(
        api_key,
        messages=[
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f'Document title: "{title}"\n\nDocument text:\n{trimmed}'
                    f"\n\nStudent question: {question}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=600,
    )

    return answer.strip()


QUIZ_SYSTEM_PROMPT = (
    "You are a quiz-writer for a secondary school AI study app. You will be "
    "given text extracted from one or more subjects' course notes, each "
    "labeled with its subject name, plus a target number of questions. "
    "Write quiz questions using ONLY facts found in the provided text - "
    "never invent facts or use outside knowledge. Mix multiple-choice and "
    "true/false questions. Spread questions across the given subjects as "
    "evenly as possible. Respond with ONLY valid JSON, no markdown fences, "
    "no commentary, matching exactly this shape:\n"
    '{"questions": [\n'
    '  {"type": "mcq", "subject": "Subject name", "question": "...", '
    '"options": ["A", "B", "C", "D"], "correct_index": 0},\n'
    '  {"type": "true_false", "subject": "Subject name", "question": "...", '
    '"options": ["True", "False"], "correct_index": 1}\n'
    "]}\n"
    "Rules: mcq questions must have exactly 4 options; true_false questions "
    'must have options exactly ["True", "False"]. correct_index is the '
    "0-based index of the correct option. Produce exactly the requested "
    "number of questions if the material supports it; if the material is "
    "too thin, produce as many good questions as you reasonably can."
)


class QuizGenerationError(SummarizationError):
    pass


def generate_quiz(subject_docs, num_questions):
    """subject_docs: list of {"subject": str, "text": str}. Returns a list of
    validated question dicts."""
    api_key = _require_api_key()

    subject_docs = [d for d in subject_docs if d.get("text") and d["text"].strip()]
    if not subject_docs:
        raise QuizGenerationError(
            "None of the selected subjects have readable notes to build a quiz from yet."
        )

    per_subject_cap = max(1000, QUIZ_MAX_CHARS // max(1, len(subject_docs)))
    blocks = []
    for doc in subject_docs:
        trimmed = doc["text"].strip()[:per_subject_cap]
        blocks.append(f'Subject: "{doc["subject"]}"\n{trimmed}')
    combined_text = "\n\n---\n\n".join(blocks)
    # Hard ceiling regardless of subject count or per-subject math above -
    # guarantees the outgoing request body can never balloon past this size.
    combined_text = combined_text[:QUIZ_MAX_CHARS]

    raw_content = _call_groq(
        api_key,
        messages=[
            {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Number of questions requested: {num_questions}\n\n"
                    f"{combined_text}"
                ),
            },
        ],
        temperature=0.4,
        max_tokens=3000,
    )

    return _parse_quiz_json(raw_content, num_questions)


def _parse_quiz_json(raw_content, num_questions):
    cleaned = raw_content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except ValueError as exc:
        raise QuizGenerationError("The AI response could not be parsed as JSON.") from exc

    raw_questions = parsed.get("questions", [])
    questions = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type", "")).strip()
        subject = str(item.get("subject", "")).strip()
        question = str(item.get("question", "")).strip()
        options = item.get("options", [])
        correct_index = item.get("correct_index")

        if qtype not in ("mcq", "true_false"):
            continue
        if not question or not subject:
            continue
        if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
            continue
        if qtype == "mcq" and len(options) != 4:
            continue
        if qtype == "true_false" and [o.strip().lower() for o in options] != ["true", "false"]:
            continue
        if not isinstance(correct_index, int) or not (0 <= correct_index < len(options)):
            continue

        questions.append({
            "type": qtype,
            "subject": subject,
            "question": question,
            "options": [o.strip() for o in options],
            "correct_index": correct_index,
        })

    if not questions:
        raise QuizGenerationError("The AI wasn't able to generate valid questions from these notes. Try different subjects.")

    return questions[:num_questions]


def _parse_summary_json(raw_content):
    cleaned = raw_content.strip()
    # Strip ```json ... ``` fences if the model added them anyway.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except ValueError as exc:
        raise SummarizationError("The AI response could not be parsed as JSON.") from exc

    overview = str(parsed.get("overview", "")).strip()
    key_topics = [str(t).strip() for t in parsed.get("key_topics", []) if str(t).strip()]
    key_terms_raw = parsed.get("key_terms", [])
    key_terms = []
    for item in key_terms_raw:
        if isinstance(item, dict):
            term = str(item.get("term", "")).strip()
            definition = str(item.get("definition", "")).strip()
            if term:
                key_terms.append({"term": term, "definition": definition})

    if not overview:
        raise SummarizationError("The AI response was missing a summary overview.")

    return overview, key_topics, key_terms
