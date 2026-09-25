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
    "Write multiple-choice quiz questions using ONLY facts found in the "
    "provided text - never invent facts or use outside knowledge. Every "
    "question must be multiple-choice with exactly 4 answer options and "
    "exactly one correct answer. Do not write true/false questions. Spread "
    "questions across the given subjects as evenly as possible. Respond "
    "with ONLY valid JSON, no markdown fences, no commentary, matching "
    "exactly this shape:\n"
    '{"questions": [\n'
    '  {"type": "mcq", "subject": "Subject name", "question": "...", '
    '"options": ["A", "B", "C", "D"], "correct_index": 0, '
    '"difficulty": "Easy", "tags": ["short-topic-keyword"], '
    '"overall_explanation": "Why the correct option is right.", '
    '"distractor_explanations": {"1": "Why option index 1 is wrong.", '
    '"2": "Why option index 2 is wrong."}}\n'
    "]}\n"
    "Rules: every question must have exactly 4 options. correct_index is "
    "the 0-based index of the correct option. difficulty must be one of "
    "Easy, Medium, Hard. tags is a short list (1-3) of lowercase topic "
    "keywords. distractor_explanations is keyed by the 0-based index of "
    "each WRONG option (never the correct one) and briefly explains why "
    "that option is incorrect - these four fields are optional but include "
    "them whenever you reasonably can, since students use them to review "
    "their mistakes. Produce exactly the requested number of questions if "
    "the material supports it; if the material is too thin, produce as "
    "many good questions as you reasonably can."
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

    per_subject_cap = max(2000, MAX_CHARS // max(1, len(subject_docs)))
    blocks = []
    for doc in subject_docs:
        trimmed = doc["text"].strip()[:per_subject_cap]
        blocks.append(f'Subject: "{doc["subject"]}"\n{trimmed}')
    combined_text = "\n\n---\n\n".join(blocks)

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

        if qtype != "mcq":
            continue
        if not question or not subject:
            continue
        if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
            continue
        if len(options) != 4:
            continue
        if not isinstance(correct_index, int) or not (0 <= correct_index < len(options)):
            continue

        questions.append({
            "type": qtype,
            "subject": subject,
            "question": question,
            "options": [o.strip() for o in options],
            "correct_index": correct_index,
            **_extract_optional_metadata(item, correct_index, len(options)),
        })

    if not questions:
        raise QuizGenerationError("The AI wasn't able to generate valid questions from these notes. Try different subjects.")

    return questions[:num_questions]


_VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}


def _extract_optional_metadata(item, correct_index, num_options):
    """Pull out the extra (optional) quiz-review fields the AI may have
    supplied - difficulty, tags, and per-option explanations. Anything
    missing or malformed is just left out rather than failing the whole
    question, since these fields are a bonus on top of a valid question."""
    metadata = {}

    difficulty = str(item.get("difficulty", "")).strip().title()
    if difficulty in _VALID_DIFFICULTIES:
        metadata["difficulty"] = difficulty

    raw_tags = item.get("tags", [])
    if isinstance(raw_tags, list):
        tags = [str(t).strip().lower() for t in raw_tags if str(t).strip()]
        if tags:
            metadata["tags"] = tags[:5]

    overall = str(item.get("overall_explanation", "")).strip()
    if overall:
        metadata["overall_explanation"] = overall

    raw_distractors = item.get("distractor_explanations", {})
    if isinstance(raw_distractors, dict):
        distractors = {}
        for key, text in raw_distractors.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            # Never accept an explanation attached to the correct answer,
            # and ignore indices outside this question's option list.
            if idx == correct_index or not (0 <= idx < num_options):
                continue
            text = str(text).strip()
            if text:
                distractors[str(idx)] = text
        if distractors:
            metadata["distractor_explanations"] = distractors

    return metadata


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
