"""
A lightweight per-subject question bank.

Every time the AI generates fresh quiz questions for a course, they're
saved here. Future quizzes on that course draw from the bank first
(instant, free, no AI call) and only ask the AI to generate the shortfall,
so subjects that have already been quizzed on a lot need less and less
fresh AI generation over time.
"""
import random

from extensions import db
from models import BankedQuestion


def get_banked_questions(course_ids, limit):
    """Return up to `limit` banked questions for the given courses, in
    random order so repeat quizzes don't feel identical."""
    if not course_ids or limit <= 0:
        return []

    rows = (
        BankedQuestion.query.filter(BankedQuestion.course_id.in_(course_ids))
        .order_by(db.func.random())
        .limit(limit)
        .all()
    )
    return [row.to_question_dict() for row in rows]


def save_questions_to_bank(selected_courses, questions):
    """Save freshly AI-generated questions into the bank, tied to whichever
    selected course they were written for (matched by subject name).
    Skips anything that's an exact duplicate of a question already banked
    for that course.
    """
    if not questions:
        return

    course_by_name = {c.name: c for c in selected_courses}
    added = False

    for q in questions:
        course = course_by_name.get(q.get("subject"))
        if not course:
            continue

        already_banked = BankedQuestion.query.filter_by(
            course_id=course.id, question=q["question"]
        ).first()
        if already_banked:
            continue

        db.session.add(BankedQuestion(
            course_id=course.id,
            subject=q["subject"],
            question=q["question"],
            options_json=BankedQuestion.dump_options(q["options"]),
            correct_index=q["correct_index"],
            # Optional richer metadata - present when the AI (or an import)
            # supplied it, absent (None) otherwise.
            difficulty=q.get("difficulty"),
            core_topic=q.get("core_topic"),
            sub_concept=q.get("sub_concept"),
            question_format=q.get("question_format"),
            tags_json=BankedQuestion.dump_json_field(q.get("tags")),
            overall_explanation=q.get("overall_explanation"),
            distractor_explanations_json=BankedQuestion.dump_json_field(q.get("distractor_explanations")),
            external_id=q.get("external_id"),
        ))
        added = True

    if added:
        db.session.commit()


def dedupe_questions(questions):
    """Drop any question whose text repeats one already earlier in the
    list - guards against the bank and a fresh AI call happening to
    overlap in the same quiz."""
    seen = set()
    unique = []
    for q in questions:
        key = q["question"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique
