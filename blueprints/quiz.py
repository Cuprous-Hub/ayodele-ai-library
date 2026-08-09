from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import Course, Document, Quiz
from utils.decorators import student_required
from utils.ai_summarizer import generate_quiz, QuizGenerationError

quiz_bp = Blueprint("quiz", __name__, url_prefix="/student/quiz")

NUM_QUESTION_CHOICES = [5, 10, 15, 20]
DURATION_CHOICES = [5, 10, 15, 20, 30, 45]


@quiz_bp.route("/new", methods=["GET", "POST"])
@login_required
@student_required
def new():
    accessible = current_user.accessible_levels
    courses = (
        Course.query.filter(Course.level.in_(accessible))
        .order_by(Course.level, Course.name)
        .all()
    )
    # Only offer courses that actually have summarized/readable material.
    courses_with_notes = [c for c in courses if any(d.full_text for d in c.documents)]

    if request.method == "POST":
        course_ids = [int(cid) for cid in request.form.getlist("course_ids")]
        try:
            num_questions = int(request.form.get("num_questions", 10))
            duration_minutes = int(request.form.get("duration_minutes", 10))
        except ValueError:
            flash("Please choose valid quiz options.", "danger")
            return render_template("student/quiz_new.html", courses=courses_with_notes,
                                    num_choices=NUM_QUESTION_CHOICES, duration_choices=DURATION_CHOICES)

        if not course_ids:
            flash("Pick at least one subject to be quizzed on.", "danger")
            return render_template("student/quiz_new.html", courses=courses_with_notes,
                                    num_choices=NUM_QUESTION_CHOICES, duration_choices=DURATION_CHOICES)

        selected_courses = [c for c in courses_with_notes if c.id in course_ids]
        if not selected_courses:
            flash("Those subjects aren't available to you.", "danger")
            return redirect(url_for("quiz.new"))

        subject_docs = []
        for course in selected_courses:
            texts = [d.full_text for d in course.documents if d.full_text]
            if texts:
                subject_docs.append({"subject": course.name, "text": "\n\n".join(texts)})

        try:
            questions = generate_quiz(subject_docs, num_questions)
        except QuizGenerationError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("quiz.new"))

        quiz = Quiz(
            student_id=current_user.id,
            title="Quiz - " + ", ".join(c.name for c in selected_courses),
            duration_minutes=duration_minutes,
            num_questions=len(questions),
            status="in_progress",
            started_at=datetime.utcnow(),
        )
        quiz.set_course_ids(course_ids)
        quiz.set_questions(questions)
        db.session.add(quiz)
        db.session.commit()

        return redirect(url_for("quiz.take", quiz_id=quiz.id))

    return render_template("student/quiz_new.html", courses=courses_with_notes,
                            num_choices=NUM_QUESTION_CHOICES, duration_choices=DURATION_CHOICES)


def _get_owned_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.student_id != current_user.id:
        abort(403)
    return quiz


@quiz_bp.route("/<int:quiz_id>/take")
@login_required
@student_required
def take(quiz_id):
    quiz = _get_owned_quiz(quiz_id)
    if quiz.status != "in_progress":
        return redirect(url_for("quiz.result", quiz_id=quiz.id))
    questions = quiz.get_questions()
    # Never send correct_index to the client while the quiz is live.
    safe_questions = [
        {"type": q["type"], "subject": q["subject"], "question": q["question"], "options": q["options"]}
        for q in questions
    ]
    remaining_seconds = max(0, int((quiz.expires_at - datetime.utcnow()).total_seconds()))
    return render_template("student/quiz_take.html", quiz=quiz, questions=safe_questions,
                            remaining_seconds=remaining_seconds)


@quiz_bp.route("/<int:quiz_id>/submit", methods=["POST"])
@login_required
@student_required
def submit(quiz_id):
    quiz = _get_owned_quiz(quiz_id)
    if quiz.status != "in_progress":
        return redirect(url_for("quiz.result", quiz_id=quiz.id))

    questions = quiz.get_questions()
    answers = []
    score = 0
    for i in range(len(questions)):
        raw = request.form.get(f"q{i}")
        if raw is None or raw == "":
            answers.append(None)
            continue
        try:
            chosen = int(raw)
        except ValueError:
            chosen = None
        answers.append(chosen)
        if chosen is not None and chosen == questions[i]["correct_index"]:
            score += 1

    quiz.set_answers(answers)
    quiz.score = score
    quiz.total = len(questions)
    quiz.status = "submitted"
    quiz.submitted_at = datetime.utcnow()
    db.session.commit()

    return redirect(url_for("quiz.result", quiz_id=quiz.id))


@quiz_bp.route("/<int:quiz_id>/result")
@login_required
@student_required
def result(quiz_id):
    quiz = _get_owned_quiz(quiz_id)
    if quiz.status != "submitted":
        return redirect(url_for("quiz.take", quiz_id=quiz.id))
    questions = quiz.get_questions()
    answers = quiz.get_answers()
    review = []
    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else None
        review.append({
            **q,
            "chosen_index": chosen,
            "is_correct": chosen is not None and chosen == q["correct_index"],
        })
    return render_template("student/quiz_result.html", quiz=quiz, review=review)


@quiz_bp.route("/history")
@login_required
@student_required
def history():
    quizzes = (
        Quiz.query.filter_by(student_id=current_user.id, status="submitted")
        .order_by(Quiz.submitted_at.desc())
        .all()
    )
    return render_template("student/quiz_history.html", quizzes=quizzes)
