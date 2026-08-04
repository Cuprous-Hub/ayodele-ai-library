from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Message

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


def _send_email(to_email, subject, body_text):
    message = Message(
        subject=subject,
        recipients=[to_email],
        body=body_text,
        sender=current_app.config["MAIL_DEFAULT_SENDER"],
    )
    mail.send(message)
    current_app.logger.info(f"Sent email to {to_email} via Gmail SMTP")


def send_verification_email(user):
    token = generate_token(user.email, salt="email-verify")
    link = url_for("auth.verify_email", token=token, _external=True)

    body = (
        f"Hi {user.full_name},\n\n"
        f"Please verify your email by clicking the link below:\n{link}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you didn't sign up for this, you can ignore this email."
    )
    _send_email(user.email, "Verify your Ayodele AI Library account", body)


def send_password_reset_email(user):
    token = generate_token(user.email, salt="password-reset")
    link = url_for("auth.reset_password", token=token, _external=True)

    body = (
        f"Hi {user.full_name},\n\n"
        f"Click the link below to reset your password:\n{link}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you didn't request this, you can ignore this email."
    )
    _send_email(user.email, "Reset your Ayodele AI Library password", body)
