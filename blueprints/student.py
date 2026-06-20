from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user

from models import Course
from utils.decorators import student_required

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.route("/dashboard")
@login_required
@student_required
def dashboard():
    courses = (
        Course.query.filter_by(level=current_user.level)
        .order_by(Course.name)
        .all()
    )
    return render_template("student/dashboard.html", courses=courses)


@student_bp.route("/courses/<int:course_id>")
@login_required
@student_required
def course_detail(course_id):
    course = Course.query.get_or_404(course_id)
    if course.level != current_user.level:
        abort(403)
    return render_template("student/course_detail.html", course=course)