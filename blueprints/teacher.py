import os
import uuid

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    current_app, send_from_directory, abort
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Course, Document, User
from utils.decorators import teacher_required, class_teacher_required
from utils.file_parser import extract_text, ExtractionError
from utils.ai_summarizer import summarize_document, SummarizationError

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"], ext


@teacher_bp.route("/dashboard")
@login_required
@teacher_required
def dashboard():
    courses = (
        Course.query.filter_by(teacher_id=current_user.id)
        .order_by(Course.created_at.desc())
        .all()
    )
    return render_template("teacher/dashboard.html", courses=courses)


@teacher_bp.route("/courses/new", methods=["GET", "POST"])
@login_required
@teacher_required
def course_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        level = request.form.get("level", "")
        description = request.form.get("description", "").strip()

        errors = []
        if not name:
            errors.append("Please enter a course name.")
        if not code:
            errors.append("Please enter a course code.")
        if level not in current_app.config["LEVELS"]:
            errors.append("Please select a valid class level.")
        if code and Course.query.filter_by(code=code).first():
            errors.append(f"Course code '{code}' is already in use.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "teacher/course_new.html", form=request.form, levels=current_app.config["LEVELS"]
            )

        course = Course(
            name=name, code=code, level=level, description=description,
            teacher_id=current_user.id,
        )
        db.session.add(course)
        db.session.commit()
        flash(f"Course '{course.name}' created.", "success")
        return redirect(url_for("teacher.course_detail", course_id=course.id))

    return render_template("teacher/course_new.html", form={}, levels=current_app.config["LEVELS"])


def _get_owned_course(course_id):
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id:
        abort(403)
    return course


@teacher_bp.route("/courses/<int:course_id>")
@login_required
@teacher_required
def course_detail(course_id):
    course = _get_owned_course(course_id)
    return render_template("teacher/course_detail.html", course=course)


@teacher_bp.route("/courses/<int:course_id>/upload", methods=["POST"])
@login_required
@teacher_required
def upload_document(course_id):
    course = _get_owned_course(course_id)

    uploaded_file = request.files.get("document")
    title = request.form.get("title", "").strip()

    if not uploaded_file or uploaded_file.filename == "":
        flash("Please choose a file to upload.", "danger")
        return redirect(url_for("teacher.course_detail", course_id=course.id))

    is_allowed, ext = _allowed_file(uploaded_file.filename)
    if not is_allowed:
        flash("Only PDF, DOCX, and PPTX files are allowed.", "danger")
        return redirect(url_for("teacher.course_detail", course_id=course.id))

    if not title:
        title = os.path.splitext(secure_filename(uploaded_file.filename))[0]

    course_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], str(course.id))
    os.makedirs(course_folder, exist_ok=True)

    stored_filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(course_folder, stored_filename)
    uploaded_file.save(filepath)

    document = Document(
        course_id=course.id,
        title=title,
        original_filename=secure_filename(uploaded_file.filename),
        stored_filename=stored_filename,
        file_type=ext,
        status="pending",
    )
    db.session.add(document)
    db.session.commit()

    _process_document(document, filepath)

    return redirect(url_for("teacher.course_detail", course_id=course.id))


def _process_document(document, filepath):
    """Extract text and request an AI summary, recording success or failure."""
    try:
        text = extract_text(filepath, document.file_type)
        document.full_text = text
        db.session.commit()

        overview, key_topics, key_terms = summarize_document(document.title, text)
        document.set_summary(overview, key_topics, key_terms)
        document.status = "done"
        document.error_message = None
    except (ExtractionError, SummarizationError) as exc:
        document.status = "failed"
        document.error_message = str(exc)
    except Exception as exc:  # noqa: BLE001 - last-resort safety net
        document.status = "failed"
        document.error_message = f"Unexpected error: {exc}"

    db.session.commit()


@teacher_bp.route("/documents/<int:document_id>/resummarize", methods=["POST"])
@login_required
@teacher_required
def resummarize(document_id):
    document = Document.query.get_or_404(document_id)
    course = _get_owned_course(document.course_id)

    filepath = os.path.join(
        current_app.config["UPLOAD_FOLDER"], str(course.id), document.stored_filename
    )
    if not os.path.exists(filepath):
        flash("The original file is missing from the server.", "danger")
        return redirect(url_for("teacher.course_detail", course_id=course.id))

    document.status = "pending"
    db.session.commit()
    _process_document(document, filepath)

    if document.status == "done":
        flash("Summary regenerated.", "success")
    else:
        flash(f"Summary failed: {document.error_message}", "danger")
    return redirect(url_for("teacher.course_detail", course_id=course.id))


@teacher_bp.route("/documents/<int:document_id>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_document(document_id):
    document = Document.query.get_or_404(document_id)
    course = _get_owned_course(document.course_id)

    filepath = os.path.join(
        current_app.config["UPLOAD_FOLDER"], str(course.id), document.stored_filename
    )
    if os.path.exists(filepath):
        os.remove(filepath)

    db.session.delete(document)
    db.session.commit()
    flash("Document deleted.", "info")
    return redirect(url_for("teacher.course_detail", course_id=course.id))


@teacher_bp.route("/courses/<int:course_id>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_course(course_id):
    course = _get_owned_course(course_id)
    course_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], str(course.id))

    db.session.delete(course)
    db.session.commit()

    if os.path.isdir(course_folder):
        import shutil
        shutil.rmtree(course_folder, ignore_errors=True)

    flash(f"Course '{course.name}' deleted.", "info")
    return redirect(url_for("teacher.dashboard"))


@teacher_bp.route("/settings/class", methods=["GET", "POST"])
@login_required
@teacher_required
def class_settings():
    if request.method == "POST":
        wants_class = request.form.get("is_class_teacher") == "yes"
        chosen_level = request.form.get("assigned_level", "")

        if wants_class:
            if chosen_level not in current_app.config["LEVELS"]:
                flash("Please select a valid class level.", "danger")
                return redirect(url_for("teacher.class_settings"))
            current_user.is_class_teacher = True
            current_user.assigned_level = chosen_level
            flash(f"You're now set as the class teacher for {chosen_level}.", "success")
        else:
            current_user.is_class_teacher = False
            current_user.assigned_level = None
            flash("You're no longer marked as a class teacher.", "info")

        db.session.commit()
        return redirect(url_for("teacher.dashboard"))

    counts = {}
    for lvl in current_app.config["LEVELS"]:
        counts[lvl] = User.query.filter_by(
            role="teacher", is_class_teacher=True, assigned_level=lvl
        ).filter(User.id != current_user.id).count()

    return render_template(
        "teacher/class_settings.html",
        levels=current_app.config["LEVELS"],
        counts=counts,
    )


@teacher_bp.route("/promote", methods=["GET"])
@login_required
@class_teacher_required
def promote_view():
    target_level = current_user.assigned_level
    if not target_level:
        flash("You are not currently assigned to a class.", "warning")
        return redirect(url_for("teacher.dashboard"))

    students = (
        User.query.filter_by(role="student", level=target_level)
        .order_by(User.full_name)
        .all()
    )
    return render_template(
        "teacher/promote.html",
        students=students,
        current_level=target_level,
        levels=current_app.config["LEVELS"],
    )


@teacher_bp.route("/promote/toggle-repeat/<int:student_id>", methods=["POST"])
@login_required
@class_teacher_required
def toggle_repeat(student_id):
    student = User.query.get_or_404(student_id)
    if student.level != current_user.assigned_level:
        abort(403)

    student.is_repeating = not student.is_repeating
    db.session.commit()
    return redirect(url_for("teacher.promote_view"))


@teacher_bp.route("/promote/confirm", methods=["POST"])
@login_required
@class_teacher_required
def promote_confirm():
    current_level = current_user.assigned_level
    new_level = request.form.get("new_level", "")

    if not current_level:
        flash("You are not currently assigned to a class.", "warning")
        return redirect(url_for("teacher.dashboard"))

    if new_level not in current_app.config["LEVELS"]:
        flash("Please select a valid target level.", "danger")
        return redirect(url_for("teacher.promote_view"))

    students_to_promote = User.query.filter_by(
        role="student", level=current_level, is_repeating=False
    ).all()

    count = len(students_to_promote)
    for student in students_to_promote:
        student.promote_to(new_level)

    db.session.commit()

    flash(
        f"Promoted {count} student(s) from {current_level} to {new_level}.",
        "success",
    )
    return redirect(url_for("teacher.dashboard"))