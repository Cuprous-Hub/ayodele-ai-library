import os
from flask import Flask, render_template, redirect, url_for, send_from_directory, abort, jsonify, request
from flask_login import login_required, current_user

from config import Config
from extensions import db, login_manager
from models import User, Document, Course
from utils.ai_summarizer import answer_question, SummarizationError


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    from flask import send_from_directory

    @app.route('/sw.js')
    def service_worker():
        return send_from_directory('static', 'sw.js', mimetype='application/javascript')
    from blueprints.auth import auth_bp
    from blueprints.teacher import teacher_bp
    from blueprints.student import student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)

    with app.app_context():
        db.create_all()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.route("/")
    def home():
        if not current_user.is_authenticated:
            return render_template("landing.html")
        if current_user.is_teacher:
            return redirect(url_for("teacher.dashboard"))
        return redirect(url_for("student.dashboard"))

    def _check_document_access(course):
        if current_user.is_teacher and course.teacher_id != current_user.id:
            abort(403)
        if current_user.is_student and course.level != current_user.level:
            abort(403)

    @app.route("/documents/<int:document_id>")
    @login_required
    def view_document(document_id):
        document = Document.query.get_or_404(document_id)
        course = Course.query.get_or_404(document.course_id)
        _check_document_access(course)
        return render_template("document_view.html", document=document, course=course)

    @app.route("/documents/<int:document_id>/download")
    @login_required
    def download_document(document_id):
        document = Document.query.get_or_404(document_id)
        course = Course.query.get_or_404(document.course_id)
        _check_document_access(course)
        folder = os.path.join(app.config["UPLOAD_FOLDER"], str(course.id))
        return send_from_directory(
            folder, document.stored_filename, as_attachment=True,
            download_name=f"{document.title}.{document.file_type}",
        )

    @app.route("/documents/<int:document_id>/ask", methods=["POST"])
    @login_required
    def ask_document(document_id):
        document = Document.query.get_or_404(document_id)
        course = Course.query.get_or_404(document.course_id)
        _check_document_access(course)

        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            return jsonify({"error": "Please enter a question."}), 400
        if not document.full_text:
            return jsonify({
                "error": "This document has no readable text to answer questions from."
            }), 400

        try:
            answer = answer_question(document.title, document.full_text, question)
            return jsonify({"answer": answer})
        except SummarizationError as exc:
            return jsonify({"error": str(exc)}), 502

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("errors/413.html"), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)