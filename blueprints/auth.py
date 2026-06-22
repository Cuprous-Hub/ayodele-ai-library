from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "")
        teacher_code = request.form.get("teacher_code", "")
        level = request.form.get("level", "")

        errors = []
        if not full_name:
            errors.append("Please enter your full name.")
        if not email or "@" not in email:
            errors.append("Please enter a valid email address.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if role not in ("teacher", "student"):
            errors.append("Please select whether you are a teacher or a student.")
        if role == "teacher" and teacher_code.strip().upper() != current_app.config["TEACHER_SIGNUP_CODE"].strip().upper():
            errors.append("That teacher sign-up code is incorrect.")
        if role == "student" and level not in current_app.config["LEVELS"]:
            errors.append("Please select your class level.")
        if email and User.query.filter_by(email=email).first():
            errors.append("An account with that email already exists.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "auth/register.html", form=request.form, levels=current_app.config["LEVELS"]
            )

        user = User(
            full_name=full_name, email=email, role=role,
            level=level if role == "student" else None,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f"Welcome, {user.full_name}! Your account has been created.", "success")
        return redirect(url_for("home"))

    return render_template("auth/register.html", form={}, levels=current_app.config["LEVELS"])


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.full_name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("home"))

        flash("Incorrect email or password.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))