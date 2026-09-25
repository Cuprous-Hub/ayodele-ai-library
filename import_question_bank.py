"""
Bulk-import a question-bank JSON file into a course's banked questions.

Handles the richer question format (difficulty, core_topic, tags,
per-wrong-option explanations) and normalizes either shape the source file
might use for options:

  - a dict keyed by letter:      "options": {"A": "...", "B": "..."}
  - a list of {id, text} objects: "options": [{"id": "A", "text": "..."}]

Usage:
    python import_question_bank.py --file biology_question_bank.json --course-code BIO-SS2

Run this whenever a new question-bank file needs to be loaded in; it's
safe to re-run on the same file, since questions already banked for that
course (matched on exact question text) are skipped rather than duplicated.
"""
import argparse
import json
import sys

from app import create_app
from extensions import db
from models import Course, BankedQuestion


def _normalize_options(raw_options):
    """Return (ordered_option_texts, letter_to_index) regardless of which
    of the two source shapes was used."""
    letter_to_index = {}
    texts = []

    if isinstance(raw_options, dict):
        for i, letter in enumerate(sorted(raw_options.keys())):
            texts.append(str(raw_options[letter]).strip())
            letter_to_index[letter] = i
    elif isinstance(raw_options, list):
        for i, opt in enumerate(raw_options):
            if isinstance(opt, dict):
                texts.append(str(opt.get("text", "")).strip())
                letter_to_index[str(opt.get("id", "")).strip()] = i
            else:
                # plain string option, no letter id supplied
                texts.append(str(opt).strip())
    else:
        return [], {}

    return texts, letter_to_index


def _normalize_distractors(raw_distractors, letter_to_index, correct_index):
    if not isinstance(raw_distractors, dict):
        return {}
    out = {}
    for letter, text in raw_distractors.items():
        idx = letter_to_index.get(letter)
        if idx is None or idx == correct_index:
            continue
        text = str(text).strip()
        if text:
            out[str(idx)] = text
    return out


def _build_row(course_id, item):
    options, letter_to_index = _normalize_options(item.get("options"))
    if len(options) < 2:
        return None, "no usable options"

    correct_letter = str(item.get("correct_answer", "")).strip()
    correct_index = letter_to_index.get(correct_letter)
    if correct_index is None:
        return None, f"correct_answer '{correct_letter}' not found in options"

    question = str(item.get("question_stem", "")).strip()
    if not question:
        return None, "missing question_stem"

    tags = item.get("tags", [])
    tags = [str(t).strip() for t in tags] if isinstance(tags, list) else []

    row = BankedQuestion(
        course_id=course_id,
        subject="",  # filled in by caller once the course is known
        question=question,
        options_json=BankedQuestion.dump_options(options),
        correct_index=correct_index,
        difficulty=str(item.get("difficulty", "")).strip() or None,
        core_topic=str(item.get("core_topic", "")).strip() or None,
        sub_concept=str(item.get("sub_concept", "")).strip() or None,
        question_format=str(item.get("question_type", "")).strip() or None,
        tags_json=BankedQuestion.dump_json_field(tags),
        overall_explanation=str(item.get("overall_explanation", "")).strip() or None,
        distractor_explanations_json=BankedQuestion.dump_json_field(
            _normalize_distractors(item.get("distractor_explanations"), letter_to_index, correct_index)
        ),
        external_id=str(item.get("id", "")).strip() or None,
    )
    return row, None


def import_file(path, course):
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list):
        print(f"Expected a JSON list of questions in {path}.")
        return

    existing_questions = {
        q.question for q in BankedQuestion.query.filter_by(course_id=course.id).all()
    }

    imported, skipped_duplicate, skipped_invalid = 0, 0, 0

    for item in items:
        row, error = _build_row(course.id, item)
        if error:
            skipped_invalid += 1
            print(f"  skipped ({error}): {item.get('id', '?')}")
            continue

        if row.question in existing_questions:
            skipped_duplicate += 1
            continue

        row.subject = course.name
        db.session.add(row)
        existing_questions.add(row.question)
        imported += 1

    db.session.commit()
    print(
        f"Done: {imported} imported, {skipped_duplicate} already banked, "
        f"{skipped_invalid} skipped as invalid."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Path to the question-bank JSON file")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--course-id", type=int, help="Numeric id of the course to attach questions to")
    target.add_argument("--course-code", help="Course code (e.g. BIO-SS2) to attach questions to")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.course_id is not None:
            course = Course.query.get(args.course_id)
        else:
            course = Course.query.filter_by(code=args.course_code).first()

        if not course:
            print("Couldn't find that course. Check --course-id / --course-code and try again.")
            sys.exit(1)

        print(f"Importing into course: {course.name} ({course.code})")
        import_file(args.file, course)


if __name__ == "__main__":
    main()
