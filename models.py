import json
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # "teacher" or "student"
    level = db.Column(db.String(10), nullable=True)  # student's class level, e.g. "SS2"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- new fields for class promotion feature ---
    level_history = db.Column(db.Text, nullable=True)      # JSON list of past levels
    is_repeating = db.Column(db.Boolean, default=False)    # skip on next promotion
    is_class_teacher = db.Column(db.Boolean, default=False)
    assigned_level = db.Column(db.String(10), nullable=True)  # which class they can promote

    courses = db.relationship(
        "Course", backref="teacher", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_teacher(self):
        return self.role == "teacher"

    @property
    def is_student(self):
        return self.role == "student"

    def get_level_history(self):
        """Return list of past levels this student has been through."""
        if not self.level_history:
            return []
        try:
            return json.loads(self.level_history)
        except (ValueError, TypeError):
            return []

    def add_to_level_history(self, old_level):
        history = self.get_level_history()
        if old_level and old_level not in history:
            history.append(old_level)
        self.level_history = json.dumps(history)

    @property
    def accessible_levels(self):
        """All levels this student can see course material for: current + past."""
        return set(self.get_level_history() + ([self.level] if self.level else []))

    def promote_to(self, new_level):
        """Move this student to a new level, preserving history."""
        if self.level:
            self.add_to_level_history(self.level)
        self.level = new_level

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False)
    level = db.Column(db.String(10), nullable=False)
    description = db.Column(db.Text, nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    documents = db.relationship(
        "Document",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Document.uploaded_at.desc()",
    )

    def __repr__(self):
        return f"<Course {self.code} {self.name}>"
    

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(10), nullable=False)  # pdf / docx / pptx

    full_text = db.Column(db.Text, nullable=True)

    # AI summary, stored as JSON text with keys: overview, key_topics, key_terms
    summary_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending")  # pending/done/failed
    error_message = db.Column(db.Text, nullable=True)

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_summary(self):
        """Return the parsed summary dict, or None if not available yet."""
        if not self.summary_json:
            return None
        try:
            return json.loads(self.summary_json)
        except (ValueError, TypeError):
            return None

    def set_summary(self, overview, key_topics, key_terms):
        self.summary_json = json.dumps(
            {
                "overview": overview,
                "key_topics": key_topics,
                "key_terms": key_terms,
            }
        )

    def __repr__(self):
        return f"<Document {self.title} ({self.status})>"
