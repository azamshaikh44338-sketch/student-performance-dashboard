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


def admin_redirect(section=None):
    url = url_for("admin_dashboard")
    if section:
        url += "#" + section
    return redirect(url)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if session.get("role") != role:
                flash("You are not allowed to open that page.")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped_view
    return decorator

@app.route("/test")
def test_route():
    return "Flask is responding!"
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


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
            flash("Login successful!")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("student_dashboard"))


@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    with get_db() as conn:
        students = conn.execute("""
            SELECT id, full_name, roll_no, class_division
            FROM users
            WHERE role = 'student'
            ORDER BY roll_no
        """).fetchall()

        subjects = conn.execute("""
            SELECT id, name, max_marks, class_name
            FROM subjects
            ORDER BY class_name, name
        """).fetchall()

    return render_template(
        "admin_dashboard.html",
        students=students,
        subjects=subjects
    )


@app.route("/students/add", methods=["POST"])
@role_required("admin")
def add_student():
    full_name = request.form.get("full_name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    class_division = request.form.get("class_division", "").strip()

    if not full_name or not roll_no or not class_division:
        flash("Please fill all student details.")
        return admin_redirect("register-student")

    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO users
                (username, password_hash, role, full_name,
                 roll_no, class_division)
                VALUES (?, ?, 'student', ?, ?, ?)
            """, (
                roll_no,
                generate_password_hash("Student@123"),
                full_name,
                roll_no,
                class_division
            ))

        flash("Student registered. Default password: Student@123")
    except Exception as error:
        flash(f"Could not register student: {error}")

    return admin_redirect("register-student")


@app.route("/subjects/add", methods=["POST"])
@role_required("admin")
def add_subject():
    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    max_marks_text = request.form.get("max_marks", "100").strip()

    try:
        max_marks = int(max_marks_text)

        if not name or not class_name or max_marks <= 0:
            raise ValueError("Enter a subject, class and valid maximum marks.")

        with get_db() as conn:
            conn.execute("""
                INSERT INTO subjects (name, max_marks, class_name)
                VALUES (?, ?, ?)
            """, (name, max_marks, class_name))

        flash("Subject added successfully.")
    except ValueError as error:
        flash(f"Invalid subject details: {error}")
    except Exception as error:
        flash(f"Could not add subject: {error}")

    return admin_redirect("add-subject")
@app.route("/marks/add", methods=["POST"])
@role_required("admin")
def add_marks():
    student_id = request.form.get("student_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
    marks_text = request.form.get("marks_obtained", "").strip()

    try:
        marks_obtained = float(marks_text)

        with get_db() as conn:
            student = conn.execute("""
                SELECT id, class_division
                FROM users
                WHERE id = ? AND role = 'student'
            """, (student_id,)).fetchone()

            subject = conn.execute("""
                SELECT id, max_marks, class_name
                FROM subjects
                WHERE id = ?
            """, (subject_id,)).fetchone()

            if not student or not subject:
                raise ValueError("Select a valid student and subject.")

            if student["class_division"] != subject["class_name"]:
                raise ValueError("Student and subject classes do not match.")

            if marks_obtained < 0 or marks_obtained > subject["max_marks"]:
                raise ValueError(
                    f"Marks must be between 0 and {subject['max_marks']}."
                )

            existing = conn.execute("""
                SELECT id FROM marks
                WHERE student_id = ? AND subject_id = ?
            """, (student_id, subject_id)).fetchone()

            if existing:
                conn.execute(
                    "UPDATE marks SET marks_obtained = ? WHERE id = ?",
                    (marks_obtained, existing["id"])
                )
            else:
                conn.execute("""
                    INSERT INTO marks
                    (student_id, subject_id, marks_obtained)
                    VALUES (?, ?, ?)
                """, (student_id, subject_id, marks_obtained))

        flash("Student marks saved successfully.")

    except ValueError as error:
        flash(f"Invalid marks: {error}")
    except Exception as error:
        flash(f"Could not save marks: {error}")

    return admin_redirect("enter-marks")


@app.route("/attendance/add", methods=["POST"])
@role_required("admin")
def add_attendance():
    student_id = request.form.get("student_id", "").strip()
    attendance_date = request.form.get("attendance_date", "").strip()
    status = request.form.get("status", "").strip()

    try:
        date.fromisoformat(attendance_date)

        if status not in ("Present", "Absent"):
            raise ValueError("Status must be Present or Absent.")

        with get_db() as conn:
            student = conn.execute("""
                SELECT id FROM users
                WHERE id = ? AND role = 'student'
            """, (student_id,)).fetchone()

            if not student:
                raise ValueError("Select a valid student.")

            existing = conn.execute("""
                SELECT id FROM attendance
                WHERE student_id = ? AND attendance_date = ?
            """, (student_id, attendance_date)).fetchone()

            if existing:
                conn.execute(
                    "UPDATE attendance SET status = ? WHERE id = ?",
                    (status, existing["id"])
                )
            else:
                conn.execute("""
                    INSERT INTO attendance
                    (student_id, attendance_date, status)
                    VALUES (?, ?, ?)
                """, (student_id, attendance_date, status))

        flash("Attendance saved successfully.")

    except ValueError as error:
        flash(f"Invalid attendance details: {error}")
    except Exception as error:
        flash(f"Could not save attendance: {error}")

    return admin_redirect("mark-attendance")


@app.route("/attendance/generate", methods=["POST"])
@role_required("admin")
def generate_attendance():
    student_id = request.form.get("student_id", "").strip()

    try:
        with get_db() as conn:
            student = conn.execute("""
                SELECT id FROM users
                WHERE id = ? AND role = 'student'
            """, (student_id,)).fetchone()

            if not student:
                flash("Please select a valid student.")
                return admin_redirect("mark-attendance")

            count = conn.execute("""
                SELECT COUNT(*) AS total
                FROM attendance WHERE student_id = ?
            """, (student_id,)).fetchone()["total"]

            if count == 0:
                today = date.today()

                for days_ago in range(29, -1, -1):
                    attendance_date = today - timedelta(days=days_ago)
                    status = "Present" if days_ago % 7 != 0 else "Absent"

                    conn.execute("""
                        INSERT OR IGNORE INTO attendance
                        (student_id, attendance_date, status)
                        VALUES (?, ?, ?)
                    """, (
                        student_id,
                        attendance_date.isoformat(),
                        status
                    ))

                flash("Attendance records created for 30 days.")
            else:
                flash("This student already has attendance records.")

    except Exception as error:
        flash(f"Could not generate attendance: {error}")

    return admin_redirect("mark-attendance")


@app.route("/student")
@role_required("student")
def student_dashboard():
    student_id = session["user_id"]

    with get_db() as conn:
        student = conn.execute("""
            SELECT id, full_name, roll_no, class_division
            FROM users WHERE id = ?
        """, (student_id,)).fetchone()

        marks = conn.execute("""
            SELECT subjects.name, marks.marks_obtained,
                   subjects.max_marks
            FROM marks
            JOIN subjects ON subjects.id = marks.subject_id
            WHERE marks.student_id = ?
            ORDER BY subjects.name
        """, (student_id,)).fetchall()

        attendance_records = conn.execute("""
            SELECT attendance_date, status
            FROM attendance
            WHERE student_id = ?
            ORDER BY attendance_date DESC
        """, (student_id,)).fetchall()

    total_obtained = sum(row["marks_obtained"] for row in marks)
    total_maximum = sum(row["max_marks"] for row in marks)

    overall_percentage = (
        round(total_obtained * 100 / total_maximum, 2)
        if total_maximum else 0
    )

    total_days = len(attendance_records)
    present_days = sum(
        1 for row in attendance_records if row["status"] == "Present"
    )

    attendance_percentage = (
        round(present_days * 100 / total_days, 2)
        if total_days else 0
    )

    return render_template(
        "student_dashboard.html",
        student=student,
        marks=marks,
        attendance=attendance_records,
        overall_percentage=overall_percentage,
        attendance_percentage=attendance_percentage,
        total_days=total_days,
        present_days=present_days
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)