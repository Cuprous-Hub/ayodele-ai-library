from flask import current_app, url_for
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer

from extensions import mail


def _get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_token(email, salt):
    return _get_serializer().dumps(email, salt=salt)


def verify_token(token, salt, max_age_seconds=3600):
    """Returns the email if valid, or None if expired/invalid."""
    try:
        return _get_serializer().loads(token, salt=salt, max_age=max_age_seconds)
    except Exception:
        return None


def send_verification_email(user):
    token = generate_token(user.email, salt="email-verify")
    link = url_for("auth.verify_email", token=token, _external=True)

    msg = Message(
        subject="Verify your Ayodele AI Library account",
        recipients=[user.email],
        body=(
            f"Hi {user.full_name},\n\n"
            f"Please verify your email by clicking the link below:\n{link}\n\n"
            f"This link expires in 1 hour.\n\n"
            f"If you didn't sign up for this, you can ignore this email."
        ),
    )
    mail.send(msg)


def send_password_reset_email(user):
    token = generate_token(user.email, salt="password-reset")
    link = url_for("auth.reset_password", token=token, _external=True)

    msg = Message(
        subject="Reset your Ayodele AI Library password",
        recipients=[user.email],
        body=(
            f"Hi {user.full_name},\n\n"
            f"Click the link below to reset your password:\n{link}\n\n"
            f"This link expires in 1 hour.\n\n"
            f"If you didn't request this, you can ignore this email."
        ),
    )
    mail.send(msg)