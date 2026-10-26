from datetime import date, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash

from models import init_db, get_db, create_user, verify_login

app = Flask(__name__)
app.config["SECRET_KEY"] = "student-dashboard-demo-secret"

init_db()


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            if role and session.get("role") != role:
                flash("You do not have permission to open that page.")
                return redirect(url_for("dashboard"))

            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.route("/")
def home():
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
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/dashboard")
@login_required()
def dashboard():
    if session["role"] == "admin":
        return redirect(url_for("admin_dashboard"))

    return redirect(url_for("student_dashboard"))


@app.route("/admin", methods=["GET", "POST"])
@login_required(role="admin")
def admin_dashboard():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        class_division = request.form.get("class_division", "").strip()

        try:
            maths = float(request.form.get("maths", ""))
            physics = float(request.form.get("physics", ""))
            chemistry = float(request.form.get("chemistry", ""))
            attendance_percent = float(request.form.get("attendance", ""))
        except ValueError:
            flash("Please enter valid marks and attendance.")
            return redirect(url_for("admin_dashboard"))

        if not full_name or not roll_no or not class_division:
            flash("Please fill in all student details.")
            return redirect(url_for("admin_dashboard"))

        if any(
            mark < 0 or mark > 100
            for mark in [maths, physics, chemistry]
        ):
            flash("Marks must be between 0 and 100.")
            return redirect(url_for("admin_dashboard"))

        if not 0 <= attendance_percent <= 100:
            flash("Attendance must be between 0 and 100.")
            return redirect(url_for("admin_dashboard"))

        try:
            with get_db() as conn:
                existing = conn.execute(
                    """SELECT id FROM users
                       WHERE username = ? OR roll_no = ?""",
                    (roll_no, roll_no)
                ).fetchone()

                if existing:
                    flash("This roll number already exists.")
                    return redirect(url_for("admin_dashboard"))

                cursor = conn.execute(
                    """INSERT INTO users
                       (username, password_hash, role, full_name, roll_no)
                       VALUES (?, ?, 'student', ?, ?)""",
                    (
                        roll_no,
                        generate_password_hash("Student@123"),
                        full_name,
                        roll_no
                    )
                )

                student_id = cursor.lastrowid

                for subject_name, mark in [
                    ("Maths", maths),
                    ("Physics", physics),
                    ("Chemistry", chemistry)
                ]:
                    conn.execute(
                        "INSERT OR IGNORE INTO subjects (name) VALUES (?)",
                        (subject_name,)
                    )

                    subject = conn.execute(
                        "SELECT id FROM subjects WHERE name = ?",
                        (subject_name,)
                    ).fetchone()

                    conn.execute(
                        """INSERT INTO marks
                           (student_id, subject_id, marks_obtained)
                           VALUES (?, ?, ?)""",
                        (student_id, subject["id"], mark)
                    )

                # Demo attendance for a newly created student.
                present_days = round(attendance_percent)
                today = date.today()

                for day in range(100):
                    attendance_date = (
                        today - timedelta(days=99 - day)
                    ).isoformat()

                    status = (
                        "Present" if day < present_days else "Absent"
                    )

                    conn.execute(
                        """INSERT INTO attendance
                           (student_id, attendance_date, status)
                           VALUES (?, ?, ?)""",
                        (student_id, attendance_date, status)
                    )

            flash(
                f"Student saved! Username: {roll_no}. "
                "Default password: Student@123"
            )

        except Exception as e:
            print("Student save error:", e)
            flash("Student could not be saved. Check the terminal.")

        return redirect(url_for("admin_dashboard"))

    with get_db() as conn:
        students = conn.execute(
            """SELECT id, full_name, roll_no, username
               FROM users
               WHERE role = 'student'
               ORDER BY full_name"""
        ).fetchall()

        subjects = conn.execute(
            "SELECT * FROM subjects ORDER BY name"
        ).fetchall()

    return render_template(
        "admin_dashboard.html",
        students=students,
        subjects=subjects
    )


@app.route("/attendance/generate", methods=["POST"])
@login_required(role="admin")
def generate_demo_attendance():
    """Create demo attendance only if this student has no records yet."""
    try:
        student_id = int(request.form.get("student_id", ""))
        percentage = float(request.form.get("attendance", ""))

        if not 0 <= percentage <= 100:
            raise ValueError("Invalid percentage")

        with get_db() as conn:
            student = conn.execute(
                """SELECT id, full_name FROM users
                   WHERE id = ? AND role = 'student'""",
                (student_id,)
            ).fetchone()

            if not student:
                flash("Student not found.")
                return redirect(url_for("admin_dashboard"))

            existing = conn.execute(
                "SELECT COUNT(*) AS total FROM attendance WHERE student_id = ?",
                (student_id,)
            ).fetchone()

            if existing["total"] > 0:
                flash(
                    f"{student['full_name']} already has attendance records. "
                    "Existing records were not changed."
                )
                return redirect(url_for("admin_dashboard"))

            present_days = round(percentage)
            today = date.today()

            for day in range(100):
                attendance_date = (
                    today - timedelta(days=99 - day)
                ).isoformat()

                status = (
                    "Present" if day < present_days else "Absent"
                )

                conn.execute(
                    """INSERT INTO attendance
                       (student_id, attendance_date, status)
                       VALUES (?, ?, ?)""",
                    (student_id, attendance_date, status)
                )

        flash(
            f"Demo attendance saved for {student['full_name']}: "
            f"{present_days}% across 100 demo days."
        )

    except (ValueError, TypeError):
        flash("Please enter a valid student and attendance percentage.")

    except Exception as e:
        print("Demo attendance error:", e)
        flash("Attendance could not be saved. Check the terminal.")

    return redirect(url_for("admin_dashboard"))


@app.route("/students/add", methods=["POST"])
@login_required(role="admin")
def add_student():
    name = request.form.get("full_name", "").strip()
    roll_no = request.form.get("roll_no", "").strip()
    password = request.form.get("password", "")

    if not name or not roll_no or not password:
        flash("Please fill in all student details.")
        return redirect(url_for("admin_dashboard"))

    try:
        create_user(
            username=roll_no,
            password=password,
            role="student",
            full_name=name,
            roll_no=roll_no
        )
        flash("Student account created.")

    except Exception as e:
        print("Add student error:", e)
        flash("Could not create student. Roll number may already exist.")

    return redirect(url_for("admin_dashboard"))


@app.route("/subjects/add", methods=["POST"])
@login_required(role="admin")
def add_subject():
    name = request.form.get("name", "").strip()

    try:
        max_marks = int(request.form.get("max_marks", "100"))

        if not name or max_marks <= 0:
            raise ValueError

        with get_db() as conn:
            conn.execute(
                """INSERT INTO subjects (name, max_marks)
                   VALUES (?, ?)""",
                (name, max_marks)
            )

        flash("Subject added.")

    except ValueError:
        flash("Enter a valid subject name and maximum marks.")

    except Exception as e:
        print("Add subject error:", e)
        flash("Subject already exists or could not be added.")

    return redirect(url_for("admin_dashboard"))


@app.route("/marks/add", methods=["POST"])
@login_required(role="admin")
def add_marks():
    try:
        student_id = int(request.form["student_id"])
        subject_id = int(request.form["subject_id"])
        obtained = float(request.form["marks_obtained"])

        with get_db() as conn:
            subject = conn.execute(
                "SELECT max_marks FROM subjects WHERE id = ?",
                (subject_id,)
            ).fetchone()

            student = conn.execute(
                """SELECT id FROM users
                   WHERE id = ? AND role = 'student'""",
                (student_id,)
            ).fetchone()

            if not subject or not student:
                raise ValueError

            if obtained < 0 or obtained > subject["max_marks"]:
                flash("Marks must be within the subject's maximum marks.")
                return redirect(url_for("admin_dashboard"))

            conn.execute(
                """INSERT INTO marks
                   (student_id, subject_id, marks_obtained)
                   VALUES (?, ?, ?)
                   ON CONFLICT(student_id, subject_id)
                   DO UPDATE SET marks_obtained = excluded.marks_obtained""",
                (student_id, subject_id, obtained)
            )

        flash("Marks saved.")

    except (ValueError, KeyError):
        flash("Please enter valid student, subject and marks.")

    except Exception as e:
        print("Save marks error:", e)
        flash("Could not save marks.")

    return redirect(url_for("admin_dashboard"))


@app.route("/attendance/add", methods=["POST"])
@login_required(role="admin")
def add_attendance():
    try:
        student_id = int(request.form["student_id"])
        attendance_date = request.form.get(
            "attendance_date", str(date.today())
        )
        status = request.form["status"]

        if status not in ("Present", "Absent"):
            raise ValueError

        with get_db() as conn:
            student = conn.execute(
                """SELECT id FROM users
                   WHERE id = ? AND role = 'student'""",
                (student_id,)
            ).fetchone()

            if not student:
                raise ValueError

            conn.execute(
                """INSERT INTO attendance
                   (student_id, attendance_date, status)
                   VALUES (?, ?, ?)
                   ON CONFLICT(student_id, attendance_date)
                   DO UPDATE SET status = excluded.status""",
                (student_id, attendance_date, status)
            )

        flash("Attendance saved.")

    except (ValueError, KeyError):
        flash("Please enter valid attendance details.")

    except Exception as e:
        print("Attendance error:", e)
        flash("Could not save attendance.")

    return redirect(url_for("admin_dashboard"))


@app.route("/student")
@login_required(role="student")
def student_dashboard():
    student_id = session["user_id"]

    with get_db() as conn:
        student = conn.execute(
            """SELECT full_name, roll_no
               FROM users
               WHERE id = ? AND role = 'student'""",
            (student_id,)
        ).fetchone()

        marks = conn.execute(
            """SELECT subjects.name,
                      marks.marks_obtained,
                      subjects.max_marks
               FROM marks
               JOIN subjects ON subjects.id = marks.subject_id
               WHERE marks.student_id = ?
               ORDER BY subjects.name""",
            (student_id,)
        ).fetchall()

        attendance = conn.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(
                          SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END),
                          0
                      ) AS present
               FROM attendance
               WHERE student_id = ?""",
            (student_id,)
        ).fetchone()

    total_marks = sum(row["marks_obtained"] for row in marks)
    max_marks = sum(row["max_marks"] for row in marks)

    overall = (
        round(total_marks * 100 / max_marks, 2)
        if max_marks else 0
    )

    total_days = attendance["total"]
    present_days = attendance["present"]

    attendance_percent = (
        round(present_days * 100 / total_days, 2)
        if total_days else 0
    )

    return render_template(
        "student_dashboard.html",
        student_name=(
            student["full_name"]
            if student else session.get("full_name", "Student")
        ),
        roll_no=student["roll_no"] if student else "",
        marks=marks,
        overall=overall,
        total_days=total_days,
        present_days=present_days,
        attendance_percent=attendance_percent
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    print("Starting Flask server...")
    app.run(debug=True)