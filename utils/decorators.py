from functools import wraps
from flask import abort
from flask_login import current_user


def teacher_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_teacher:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def student_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped
