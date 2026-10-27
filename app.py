import os
from datetime import date, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.security import generate_password_hash

from models import init_db, get_db, verify_login


app = Flask(__name__)
app.secret_key = "student_dashboard_secret_key_change_later"

init_db()


# -------------------- LOGIN HELPERS --------------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "user_id" not in session:
                flash("Please login first.", "error")
                return redirect(url_for("login"))

            if session.get("role") != required_role:
                flash("You are not allowed to access this page.", "error")
                return redirect(url_for("dashboard"))

            return view(*args, **kwargs)
        return wrapped_view
    return decorator


def admin_redirect():
    return redirect(url_for("admin_dashboard"))


def save_mark(conn, student_id, subject_id, marks_obtained):
    conn.execute(
        """
        INSERT INTO marks (student_id, subject_id, marks_obtained)
        VALUES (?, ?, ?)
        ON CONFLICT(student_id, subject_id)
        DO UPDATE SET marks_obtained = excluded.marks_obtained
        """,
        (student_id, subject_id, marks_obtained)
    )


# -------------------- HOME --------------------

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/test")
def test():
    return "Student Performance Dashboard is working!"


# -------------------- LOGIN --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = verify_login(username, password)

        if user:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]
            session["roll_no"] = user["roll_no"]

            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    return redirect(url_for("student_dashboard"))


# -------------------- ADMIN DASHBOARD --------------------

@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    with get_db() as conn:
        students = conn.execute(
            """
            SELECT id, full_name, roll_no, class_division
            FROM users
            WHERE role = 'student'
            ORDER BY class_division, roll_no
            """
        ).fetchall()

        subjects = conn.execute(
            """
            SELECT id, name, max_marks, class_name
            FROM subjects
            ORDER BY class_name, name
            """
        ).fetchall()

        classes = conn.execute(
            """
            SELECT class_division AS class_name
            FROM users
            WHERE role = 'student'
              AND class_division IS NOT NULL
              AND TRIM(class_division) != ''

            UNION

            SELECT class_name
            FROM subjects
            WHERE class_name IS NOT NULL
              AND TRIM(class_name) != ''

            ORDER BY class_name
            """
        ).fetchall()

    return render_template(
        "admin_dashboard.html",
        students=students,
        subjects=subjects,
        classes=classes
    )


# -------------------- ADD STUDENT --------------------

@app.route("/students/add", methods=["POST"])
@role_required("admin")
def add_student():
    full_name = request.form.get("full_name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    class_division = request.form.get("class_division", "").strip()

    if not full_name or not roll_no or not class_division:
        flash("Please fill all student details.", "error")
        return admin_redirect()

    with get_db() as conn:
        print("ADMIN DASHBOARD ROUTE REACHED")
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? OR roll_no = ?",
            (roll_no, roll_no)
        ).fetchone()

        if existing:
            flash("This roll number is already registered.", "error")
            return admin_redirect()

        password_hash = generate_password_hash("Student@123")

        conn.execute(
            """
            INSERT INTO users
            (username, password_hash, role, full_name, roll_no, class_division)
            VALUES (?, ?, 'student', ?, ?, ?)
            """,
            (
                roll_no,
                password_hash,
                full_name,
                roll_no,
                class_division
            )
        )

    flash(
        "Student added successfully. Username: roll number, "
        "default password: Student@123",
        "success"
    )
    return admin_redirect()


# -------------------- ADD SUBJECT --------------------

@app.route("/subjects/add", methods=["POST"])
@role_required("admin")
def add_subject():
    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    max_marks_text = request.form.get("max_marks", "100").strip()

    if not name or not class_name:
        flash("Please enter subject name and class/division.", "error")
        return admin_redirect()

    try:
        max_marks = float(max_marks_text)
        if max_marks <= 0:
            raise ValueError
    except ValueError:
        flash("Maximum marks must be a number greater than zero.", "error")
        return admin_redirect()

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT id FROM subjects
            WHERE LOWER(name) = LOWER(?) AND class_name = ?
            """,
            (name, class_name)
        ).fetchone()

        if existing:
            flash("This subject already exists for this class.", "error")
            return admin_redirect()

        conn.execute(
            """
            INSERT INTO subjects (name, max_marks, class_name)
            VALUES (?, ?, ?)
            """,
            (name, max_marks, class_name)
        )

    flash("Subject added successfully.", "success")
    return admin_redirect()


# -------------------- SINGLE STUDENT: ALL SUBJECT MARKS --------------------

@app.route("/marks/student-bulk", methods=["POST"])
@role_required("admin")
def save_student_marks_bulk():
    student_id_text = request.form.get("student_id", "").strip()

    try:
        student_id = int(student_id_text)
    except ValueError:
        flash("Please select a valid student.", "error")
        return admin_redirect()

    saved_count = 0

    try:
        with get_db() as conn:
            student = conn.execute(
                """
                SELECT id, class_division
                FROM users
                WHERE id = ? AND role = 'student'
                """,
                (student_id,)
            ).fetchone()

            if not student:
                flash("Student not found.", "error")
                return admin_redirect()

            subjects = conn.execute(
                """
                SELECT id, name, max_marks
                FROM subjects
                WHERE class_name = ?
                ORDER BY name
                """,
                (student["class_division"],)
            ).fetchall()

            for subject in subjects:
                field_name = f"mark_{subject['id']}"
                value = request.form.get(field_name, "").strip()

                # Empty fields are skipped; existing marks are not deleted.
                if value == "":
                    continue

                marks = float(value)
                max_marks = float(subject["max_marks"])

                if marks < 0 or marks > max_marks:
                    raise ValueError(
                        f"{subject['name']}: marks must be between 0 and {max_marks}."
                    )

                save_mark(conn, student_id, subject["id"], marks)
                saved_count += 1

    except ValueError as error:
        flash(str(error) or "Please enter valid marks.", "error")
        return admin_redirect()

    if saved_count:
        flash(f"Saved {saved_count} subject mark(s) successfully.", "success")
    else:
        flash("No marks entered. Please enter marks first.", "error")

    return admin_redirect()


# -------------------- WHOLE CLASS: ALL SUBJECT MARKS --------------------

@app.route("/marks/class-bulk", methods=["POST"])
@role_required("admin")
def save_class_marks_bulk():
    class_name = request.form.get("class_name", "").strip()

    if not class_name:
        flash("Please select a class/division.", "error")
        return admin_redirect()

    saved_count = 0

    try:
        with get_db() as conn:
            students = conn.execute(
                """
                SELECT id
                FROM users
                WHERE role = 'student' AND class_division = ?
                ORDER BY roll_no
                """,
                (class_name,)
            ).fetchall()

            subjects = conn.execute(
                """
                SELECT id, name, max_marks
                FROM subjects
                WHERE class_name = ?
                ORDER BY name
                """,
                (class_name,)
            ).fetchall()

            if not students:
                flash("No students found in this class.", "error")
                return admin_redirect()

            if not subjects:
                flash("Add subjects for this class before entering marks.", "error")
                return admin_redirect()

            # Validate all entered marks before saving any of them.
            entries = []

            for student in students:
                for subject in subjects:
                    field_name = f"mark_{student['id']}_{subject['id']}"
                    value = request.form.get(field_name, "").strip()

                    if value == "":
                        continue

                    marks = float(value)
                    max_marks = float(subject["max_marks"])

                    if marks < 0 or marks > max_marks:
                        raise ValueError(
                            f"{subject['name']}: marks must be between 0 and {max_marks}."
                        )

                    entries.append(
                        (student["id"], subject["id"], marks)
                    )

            for student_id, subject_id, marks in entries:
                save_mark(conn, student_id, subject_id, marks)
                saved_count += 1

    except ValueError as error:
        flash(str(error) or "Please enter valid marks.", "error")
        return admin_redirect()

    if saved_count:
        flash(
            f"Saved {saved_count} mark entry/entries for class {class_name}.",
            "success"
        )
    else:
        flash("No marks entered. Please enter marks first.", "error")

    return admin_redirect()


# -------------------- ADD ONE MARK ENTRY --------------------

@app.route("/marks/add", methods=["POST"])
@role_required("admin")
def add_marks():
    try:
        student_id = int(request.form.get("student_id", ""))
        subject_id = int(request.form.get("subject_id", ""))
        marks = float(request.form.get("marks_obtained", ""))

        with get_db() as conn:
            student = conn.execute(
                """
                SELECT id, class_division
                FROM users
                WHERE id = ? AND role = 'student'
                """,
                (student_id,)
            ).fetchone()

            subject = conn.execute(
                """
                SELECT id, max_marks, class_name
                FROM subjects
                WHERE id = ?
                """,
                (subject_id,)
            ).fetchone()

            if not student or not subject:
                flash("Student or subject not found.", "error")
                return admin_redirect()

            if student["class_division"] != subject["class_name"]:
                flash("The subject does not belong to this student's class.", "error")
                return admin_redirect()

            if marks < 0 or marks > float(subject["max_marks"]):
                flash(
                    f"Marks must be between 0 and {subject['max_marks']}.",
                    "error"
                )
                return admin_redirect()

            save_mark(conn, student_id, subject_id, marks)

    except ValueError:
        flash("Please enter valid marks.", "error")
        return admin_redirect()

    flash("Marks saved successfully.", "success")
    return admin_redirect()


# -------------------- ADD ATTENDANCE --------------------

@app.route("/attendance/add", methods=["POST"])
@role_required("admin")
def add_attendance():
    student_id_text = request.form.get("student_id", "").strip()
    attendance_date = request.form.get(
        "attendance_date", date.today().isoformat()
    ).strip()
    status = request.form.get("status", "").strip().title()

    try:
        student_id = int(student_id_text)
        date.fromisoformat(attendance_date)
    except ValueError:
        flash("Please enter a valid student and date.", "error")
        return admin_redirect()

    if status not in ("Present", "Absent"):
        flash("Attendance status must be Present or Absent.", "error")
        return admin_redirect()

    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'student'",
            (student_id,)
        ).fetchone()

        if not student:
            flash("Student not found.", "error")
            return admin_redirect()

        existing = conn.execute(
            """
            SELECT id FROM attendance
            WHERE student_id = ? AND attendance_date = ?
            """,
            (student_id, attendance_date)
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE attendance
                SET status = ?
                WHERE student_id = ? AND attendance_date = ?
                """,
                (status, student_id, attendance_date)
            )
        else:
            conn.execute(
                """
                INSERT INTO attendance (student_id, attendance_date, status)
                VALUES (?, ?, ?)
                """,
                (student_id, attendance_date, status)
            )

    flash("Attendance saved successfully.", "success")
    return admin_redirect()


# -------------------- GENERATE SAMPLE ATTENDANCE --------------------

@app.route("/attendance/generate", methods=["POST"])
@role_required("admin")
def generate_attendance():
    try:
        days = int(request.form.get("days", "30"))
        if days < 1 or days > 366:
            raise ValueError
    except ValueError:
        flash("Days must be between 1 and 366.", "error")
        return admin_redirect()

    with get_db() as conn:
        students = conn.execute(
            "SELECT id FROM users WHERE role = 'student'"
        ).fetchall()

        for student in students:
            for offset in range(days):
                attendance_date = (
                    date.today() - timedelta(days=offset)
                ).isoformat()

                existing = conn.execute(
                    """
                    SELECT id FROM attendance
                    WHERE student_id = ? AND attendance_date = ?
                    """,
                    (student["id"], attendance_date)
                ).fetchone()

                if not existing:
                    conn.execute(
                        """
                        INSERT INTO attendance
                        (student_id, attendance_date, status)
                        VALUES (?, ?, 'Present')
                        """,
                        (student["id"], attendance_date)
                    )

    flash("Attendance records generated successfully.", "success")
    return admin_redirect()


# -------------------- STUDENT DASHBOARD --------------------

@app.route("/student")
@role_required("student")
def student_dashboard():
    student_id = session["user_id"]

    with get_db() as conn:
        student = conn.execute(
            """
            SELECT id, full_name, roll_no, class_division
            FROM users
            WHERE id = ? AND role = 'student'
            """,
            (student_id,)
        ).fetchone()

        marks_rows = conn.execute(
            """
            SELECT
                subjects.id AS subject_id,
                subjects.name AS subject_name,
                subjects.max_marks AS max_marks,
                marks.marks_obtained AS marks_obtained
            FROM marks
            JOIN subjects ON subjects.id = marks.subject_id
            WHERE marks.student_id = ?
            ORDER BY subjects.name
            """,
            (student_id,)
        ).fetchall()

        attendance_rows = conn.execute(
            """
            SELECT attendance_date, status
            FROM attendance
            WHERE student_id = ?
            ORDER BY attendance_date DESC
            """,
            (student_id,)
        ).fetchall()

    if not student:
        session.clear()
        flash("Student account not found. Please login again.", "error")
        return redirect(url_for("login"))

    marks = []
    total_obtained = 0.0
    total_maximum = 0.0

    for row in marks_rows:
        obtained = float(row["marks_obtained"])
        maximum = float(row["max_marks"])
        percentage = (obtained / maximum * 100) if maximum else 0

        marks.append({
            "subject_id": row["subject_id"],
            "subject_name": row["subject_name"],
            "marks_obtained": obtained,
            "max_marks": maximum,
            "percentage": round(percentage, 2)
        })

        total_obtained += obtained
        total_maximum += maximum

    overall_percentage = (
        round(total_obtained / total_maximum * 100, 2)
        if total_maximum else 0
    )

    strong_subjects = [
        item for item in marks if item["percentage"] >= 75
    ]
    weak_subjects = [
        item for item in marks if item["percentage"] < 40
    ]

    present_days = sum(
        1 for row in attendance_rows
        if row["status"] == "Present"
    )
    absent_days = sum(
        1 for row in attendance_rows
        if row["status"] == "Absent"
    )
    total_days = len(attendance_rows)

    attendance_percentage = (
        round(present_days / total_days * 100, 2)
        if total_days else 0
    )

    return render_template(
        "student_dashboard.html",
        student=student,
        marks=marks,
        overall_percentage=overall_percentage,
        strong_subjects=strong_subjects,
        weak_subjects=weak_subjects,
        attendance=attendance_rows,
        present_days=present_days,
        absent_days=absent_days,
        total_days=total_days,
        attendance_percentage=attendance_percentage
    )


# -------------------- LOGOUT --------------------
# -------------------- EDIT STUDENT --------------------

@app.route("/students/<int:student_id>/edit", methods=["POST"])
@role_required("admin")
def edit_student(student_id):
    full_name = request.form.get("full_name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    class_division = request.form.get("class_division", "").strip()

    if not full_name or not roll_no or not class_division:
        flash("Please fill all student details.", "error")
        return redirect(url_for("admin_dashboard"))

    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'student'",
            (student_id,)
        ).fetchone()

        if not student:
            flash("Student not found.", "error")
        else:
            duplicate = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (roll_no, student_id)
            ).fetchone()

            if duplicate:
                flash("This roll number is already in use.", "error")
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET full_name = ?, roll_no = ?,
                        username = ?, class_division = ?
                    WHERE id = ? AND role = 'student'
                    """,
                    (full_name, roll_no, roll_no, class_division, student_id)
                )
                flash("Student details updated.", "success")

    return redirect(url_for("admin_dashboard"))


# -------------------- DELETE STUDENT --------------------

@app.route("/students/<int:student_id>/delete", methods=["POST"])
@role_required("admin")
def delete_student(student_id):
    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'student'",
            (student_id,)
        ).fetchone()

        if student:
            conn.execute("DELETE FROM marks WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
            conn.execute(
                "DELETE FROM users WHERE id = ? AND role = 'student'",
                (student_id,)
            )
            flash("Student and related records deleted.", "success")
        else:
            flash("Student not found.", "error")

    return redirect(url_for("admin_dashboard"))


# -------------------- EDIT SUBJECT --------------------

@app.route("/subjects/<int:subject_id>/edit", methods=["POST"])
@role_required("admin")
def edit_subject(subject_id):
    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()

    try:
        max_marks = float(request.form.get("max_marks", ""))
        if max_marks <= 0:
            raise ValueError
    except (ValueError, TypeError):
        flash("Maximum marks must be a positive number.", "error")
        return redirect(url_for("admin_dashboard"))

    if not name or not class_name:
        flash("Please fill all subject details.", "error")
        return redirect(url_for("admin_dashboard"))

    with get_db() as conn:
        subject = conn.execute(
            "SELECT id FROM subjects WHERE id = ?",
            (subject_id,)
        ).fetchone()

        if not subject:
            flash("Subject not found.", "error")
        else:
            too_high = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM marks
                WHERE subject_id = ? AND marks_obtained > ?
                """,
                (subject_id, max_marks)
            ).fetchone()["total"]

            if too_high:
                flash(
                    "Maximum marks cannot be lower than already recorded marks.",
                    "error"
                )
            else:
                try:
                    conn.execute(
                        """
                        UPDATE subjects
                        SET name = ?, class_name = ?, max_marks = ?
                        WHERE id = ?
                        """,
                        (name, class_name, max_marks, subject_id)
                    )
                    flash("Subject details updated.", "success")
                except Exception:
                    flash(
                        "Could not update subject. Check for duplicate subject names in this class.",
                        "error"
                    )

    return redirect(url_for("admin_dashboard"))


# -------------------- DELETE SUBJECT --------------------

@app.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@role_required("admin")
def delete_subject(subject_id):
    with get_db() as conn:
        subject = conn.execute(
            "SELECT id FROM subjects WHERE id = ?",
            (subject_id,)
        ).fetchone()

        if subject:
            conn.execute("DELETE FROM marks WHERE subject_id = ?", (subject_id,))
            conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
            flash("Subject and its saved marks deleted.", "success")
        else:
            flash("Subject not found.", "error")

    return redirect(url_for("admin_dashboard"))
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# -------------------- RUN APP --------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)