from models import init_db, get_db, create_user


def seed_data():
    init_db()

    with get_db() as conn:
        admin = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("admin",)
        ).fetchone()

    if not admin:
        create_user(
            username="admin",
            password="Admin@123",
            role="admin",
            full_name="Teacher Admin"
        )
        print("Admin account created.")

    sample_student = None

    with get_db() as conn:
        sample_student = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("102",)
        ).fetchone()

    if not sample_student:
        create_user(
            username="102",
            password="Student@123",
            role="student",
            full_name="Ayan",
            roll_no="102"
        )
        print("Sample student created.")

    with get_db() as conn:
        for subject in ["Maths", "Physics", "Chemistry"]:
            conn.execute(
                """INSERT OR IGNORE INTO subjects (name, max_marks)
                   VALUES (?, 100)""",
                (subject,)
            )

        student = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("102",)
        ).fetchone()

        subjects = conn.execute(
            "SELECT id, name FROM subjects"
        ).fetchall()

        sample_marks = {
            "Maths": 90,
            "Physics": 82,
            "Chemistry": 65
        }

        for subject in subjects:
            if subject["name"] in sample_marks:
                conn.execute(
                    """INSERT OR IGNORE INTO marks
                       (student_id, subject_id, marks_obtained)
                       VALUES (?, ?, ?)""",
                    (
                        student["id"],
                        subject["id"],
                        sample_marks[subject["name"]]
                    )
                )

    print("Database setup completed.")


if __name__ == "__main__":
    seed_data()