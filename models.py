import sqlite3
from pathlib import Path
from contextlib import contextmanager
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "students.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
            full_name TEXT NOT NULL,
            roll_no TEXT UNIQUE,
            class_division TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            max_marks INTEGER NOT NULL DEFAULT 100,
            class_name TEXT NOT NULL DEFAULT 'General',
            UNIQUE(name, class_name)
        );

        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            marks_obtained REAL NOT NULL,
            UNIQUE(student_id, subject_id),
            FOREIGN KEY(student_id) REFERENCES users(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Present', 'Absent')),
            UNIQUE(student_id, attendance_date),
            FOREIGN KEY(student_id) REFERENCES users(id)
        );
        """)

        # Add the class column to an existing users table.
        user_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }

        if "class_division" not in user_columns:
            conn.execute("""
                ALTER TABLE users
                ADD COLUMN class_division TEXT NOT NULL DEFAULT ''
            """)

        # Migrate the old subjects table safely if needed.
        subject_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(subjects)").fetchall()
        }

        if "class_name" not in subject_columns:
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")

            try:
                conn.executescript("""
                    BEGIN;

                    CREATE TABLE subjects_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        max_marks INTEGER NOT NULL DEFAULT 100,
                        class_name TEXT NOT NULL DEFAULT 'General',
                        UNIQUE(name, class_name)
                    );

                    INSERT INTO subjects_new
                        (id, name, max_marks, class_name)
                    SELECT id, name, max_marks, 'General'
                    FROM subjects;

                    DROP TABLE subjects;

                    ALTER TABLE subjects_new RENAME TO subjects;

                    COMMIT;
                """)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")


def create_user(username, password, role, full_name, roll_no=None):
    password_hash = generate_password_hash(password)

    with get_db() as conn:
        conn.execute(
            """INSERT INTO users
               (username, password_hash, role, full_name, roll_no)
               VALUES (?, ?, ?, ?, ?)""",
            (username, password_hash, role, full_name, roll_no)
        )


def verify_login(username, password):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

    if user and check_password_hash(user["password_hash"], password):
        return user

    return None