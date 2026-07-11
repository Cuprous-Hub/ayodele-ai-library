from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User
from utils.mail import send_verification_email, send_password_reset_email, verify_token

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

        if email and User.query.filter_by(email=email).first():
            flash("An account with this email already exists. Please log in instead.", "warning")
            return redirect(url_for("auth.login", email=email))

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

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "auth/register.html", form=request.form, levels=current_app.config["LEVELS"]
            )

        user = User(
            full_name=full_name, email=email, role=role,
            level=level if role == "student" else None,
            email_verified=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        try:
            send_verification_email(user)
            flash(
                f"Welcome, {user.full_name}! We've sent a verification link to {user.email}. "
                "Please check your inbox before logging in.",
                "success",
            )
        except Exception as e:
            current_app.logger.error(f"MAIL ERROR (verification): {e}")
            flash(
                "Account created, but we couldn't send a verification email right now. "
                "Please contact support.",
                "warning",
            )

        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form={}, levels=current_app.config["LEVELS"])


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    email = verify_token(token, salt="email-verify", max_age_seconds=3600)
    if not email:
        flash("That verification link is invalid or has expired.", "danger")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Account not found.", "danger")
        return redirect(url_for("auth.login"))

    if user.email_verified:
        flash("Your email is already verified. Please log in.", "info")
    else:
        user.email_verified = True
        db.session.commit()
        flash("Your email has been verified! You can now log in.", "success")

    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    prefill_email = request.args.get("email", "")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.email_verified:
                flash(
                    "Please verify your email before logging in. Check your inbox for the link.",
                    "warning",
                )
                return redirect(url_for("auth.login"))

            login_user(user)
            flash(f"Welcome back, {user.full_name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("home"))

        flash("Incorrect email or password.", "danger")
        prefill_email = email

    return render_template("auth/login.html", prefill_email=prefill_email)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()

        if user:
            try:
                send_password_reset_email(user)
            except Exception as e:
                current_app.logger.error(f"MAIL ERROR (reset): {e}")

        flash(
            "If an account with that email exists, a password reset link has been sent.",
            "info",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    email = verify_token(token, salt="password-reset", max_age_seconds=3600)
    if not email:
        flash("That reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Account not found.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("auth/reset_password.html", token=token)
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/reset_password.html", token=token)

        user.set_password(password)
        db.session.commit()
        flash("Your password has been reset. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))