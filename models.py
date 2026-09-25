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
    email_verified = db.Column(db.Boolean, default=False)
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


class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    course_ids = db.Column(db.Text, nullable=False)  # JSON list of course ids used
    duration_minutes = db.Column(db.Integer, nullable=False)
    num_questions = db.Column(db.Integer, nullable=False)

    # JSON list of {type, subject, question, options, correct_index}
    questions_json = db.Column(db.Text, nullable=False)
    # JSON list of ints (or null for unanswered), same length/order as questions
    answers_json = db.Column(db.Text, nullable=True)

    score = db.Column(db.Integer, nullable=True)
    total = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default="in_progress")  # in_progress/submitted

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("User", backref="quizzes")

    def get_course_ids(self):
        try:
            return json.loads(self.course_ids)
        except (ValueError, TypeError):
            return []

    def set_course_ids(self, ids):
        self.course_ids = json.dumps(ids)

    def get_questions(self):
        try:
            return json.loads(self.questions_json)
        except (ValueError, TypeError):
            return []

    def set_questions(self, questions):
        self.questions_json = json.dumps(questions)

    def get_answers(self):
        if not self.answers_json:
            return []
        try:
            return json.loads(self.answers_json)
        except (ValueError, TypeError):
            return []

    def set_answers(self, answers):
        self.answers_json = json.dumps(answers)

    @property
    def expires_at(self):
        from datetime import timedelta
        return self.started_at + timedelta(minutes=self.duration_minutes)

    def __repr__(self):
        return f"<Quiz {self.id} for user {self.student_id} ({self.status})>"


class BankedQuestion(db.Model):
    """A reusable multiple-choice question generated from a course's notes.

    Once the AI generates a question for a course, it's saved here so
    future quizzes on the same subject can reuse it instead of always
    calling the AI fresh - a growing "question bank" per subject.
    """
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    subject = db.Column(db.String(150), nullable=False)

    question = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, nullable=False)  # JSON list of 4 option strings
    correct_index = db.Column(db.Integer, nullable=False)

    # --- richer metadata, optional so older rows keep working untouched ---
    difficulty = db.Column(db.String(20), nullable=True)         # Easy / Medium / Hard
    core_topic = db.Column(db.String(120), nullable=True)        # e.g. "Cell Biology"
    sub_concept = db.Column(db.String(150), nullable=True)       # e.g. "Cell Structures"
    question_format = db.Column(db.String(60), nullable=True)    # e.g. "Sequential Pathway"
    tags_json = db.Column(db.Text, nullable=True)                # JSON list of strings
    overall_explanation = db.Column(db.Text, nullable=True)
    # JSON object keyed by the 0-based option index, explaining why that
    # specific wrong option is wrong (only wrong options need an entry).
    distractor_explanations_json = db.Column(db.Text, nullable=True)
    external_id = db.Column(db.String(60), nullable=True)  # id from an imported bank file, for traceability

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship(
        "Course", backref=db.backref("banked_questions", cascade="all, delete-orphan")
    )

    @staticmethod
    def dump_options(options):
        return json.dumps(options)

    @staticmethod
    def dump_json_field(value):
        """Store a list/dict metadata field as JSON text, or None if empty."""
        if not value:
            return None
        return json.dumps(value)

    def get_options(self):
        try:
            return json.loads(self.options_json)
        except (ValueError, TypeError):
            return []

    def get_tags(self):
        if not self.tags_json:
            return []
        try:
            return json.loads(self.tags_json)
        except (ValueError, TypeError):
            return []

    def get_distractor_explanations(self):
        """Return {option_index (int): explanation} for this question's
        wrong options."""
        if not self.distractor_explanations_json:
            return {}
        try:
            raw = json.loads(self.distractor_explanations_json)
        except (ValueError, TypeError):
            return {}
        # Keys are stored as strings in JSON; templates look these up by
        # the stringified loop index, so keep them as strings here too.
        return {str(k): v for k, v in raw.items()}

    def to_question_dict(self):
        """Shape matches what generate_quiz() returns (plus the optional
        metadata keys below), so a banked question can be mixed into the
        same questions list a fresh quiz uses regardless of where it
        came from."""
        return {
            "type": "mcq",
            "subject": self.subject,
            "question": self.question,
            "options": self.get_options(),
            "correct_index": self.correct_index,
            "difficulty": self.difficulty,
            "core_topic": self.core_topic,
            "sub_concept": self.sub_concept,
            "question_format": self.question_format,
            "tags": self.get_tags(),
            "overall_explanation": self.overall_explanation,
            "distractor_explanations": self.get_distractor_explanations(),
        }

    def __repr__(self):
        return f"<BankedQuestion {self.id} course={self.course_id}>"
