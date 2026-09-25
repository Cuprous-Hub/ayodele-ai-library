from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user

from models import Course
from utils.decorators import student_required

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.route("/dashboard")
@login_required
@student_required
def dashboard():
    accessible = current_user.accessible_levels
    courses = (
        Course.query.filter(Course.level.in_(accessible))
        .order_by(Course.level, Course.name)
        .all()
    )
    return render_template(
        "student/dashboard.html",
        courses=courses,
        current_level=current_user.level,
    )


@student_bp.route("/courses/<int:course_id>")
@login_required
@student_required
def course_detail(course_id):
    course = Course.query.get_or_404(course_id)
    if course.level not in current_user.accessible_levels:
        abort(403)
    return render_template("student/course_detail.html", course=course)