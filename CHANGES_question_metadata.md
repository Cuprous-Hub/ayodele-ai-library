# Richer question metadata — what changed

The quiz feature now supports difficulty, topic tags, and per-answer
explanations (why the correct answer is right, and why each wrong option
is wrong), on top of the existing plain multiple-choice format.

## Files touched

- **models.py** — `BankedQuestion` gained optional columns: `difficulty`,
  `core_topic`, `sub_concept`, `question_format`, `tags_json`,
  `overall_explanation`, `distractor_explanations_json`, `external_id`.
  All nullable, so nothing already in the database breaks.
- **utils/question_bank.py** — `save_questions_to_bank` now stores these
  fields when a question (banked or freshly generated) supplies them.
- **utils/ai_summarizer.py** — the AI quiz-writing prompt now *asks* for
  difficulty/tags/explanations too, and the parser accepts them if
  present (silently ignoring them if the AI doesn't supply them, so
  nothing breaks if a response omits them).
- **templates** (`student/quiz_take.html`, `student/quiz_result.html`,
  `teacher/student_quiz_result.html`) — show a difficulty badge and topic
  tags on each question, and on the result/review pages show the overall
  explanation plus, next to whichever wrong option a student picked, why
  that specific option was wrong.
- **static/css/style.css** — a few small classes for the new badges and
  explanation boxes (`.quiz-difficulty-*`, `.quiz-tag-row`,
  `.quiz-explanation`, `.quiz-distractor-note`).
- **import_question_bank.py** (new) — a CLI script for loading a
  question-bank JSON file (like the biology one) straight into a
  course's banked questions. Handles either shape a source file might
  use for `options` (a letter-keyed dict, or a list of `{id, text}`
  objects), maps `correct_answer`/`distractor_explanations` (letter-keyed)
  onto the 0-based option indices the app uses internally, and skips
  anything already banked for that course.
- **migrate_add_question_metadata.py** (new) — one-time ALTER TABLE
  migration for the new `banked_question` columns, in the same style as
  the existing `migrate_add_promotion_fields.py`.

## Deploying this

1. Replace the files in your repo with these versions.
2. Run the migration once against your database:
   ```bash
   python migrate_add_question_metadata.py
   ```
3. Import a question-bank file into a specific course:
   ```bash
   python import_question_bank.py --file biology_question_bank.json --course-code BIO-SS2
   ```
   (Use `--course-id` instead if that's easier — whichever course the
   questions should be banked under.)
4. From there it works automatically: any quiz drawn from that course
   will pull these banked questions first, and the take/result pages
   will show the difficulty badge, tags, and explanations for them.
   Old quizzes and old banked questions with no metadata still display
   fine — they just skip the badge/tag/explanation sections.

## Notes

- `distractor_explanations` in the source JSON is keyed by option letter
  (e.g. `"A"`) and sometimes includes an entry for the *correct* letter
  too (labeled `"Correct answer."` in your sample file) — the import
  script drops that entry, since it's redundant with `overall_explanation`.
- `question_type` in the source JSON (e.g. "Sequential Pathway",
  "Analytical/Assertion") is stored as `question_format` — it's just a
  descriptive label; every question still renders and grades as
  standard multiple-choice.
