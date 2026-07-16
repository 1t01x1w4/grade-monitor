import aiosqlite
from pathlib import Path

DB_DIR = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH = DB_DIR / "grades.db"


async def get_db() -> aiosqlite.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await _init_tables(db)
    return db


async def _init_tables(db: aiosqlite.Connection):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            course_id TEXT,
            score TEXT,
            credit REAL,
            gpa REAL,
            semester TEXT,
            exam_type TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_name, semester, exam_type)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    await db.commit()


async def insert_grade(db: aiosqlite.Connection, grade: dict) -> bool:
    """Insert a grade record. Returns True if inserted, False if already exists."""
    try:
        before = db.total_changes
        await db.execute(
            """INSERT OR IGNORE INTO grades
               (course_name, course_id, score, credit, gpa, semester, exam_type)
               VALUES (:course_name, :course_id, :score, :credit, :gpa, :semester, :exam_type)""",
            grade,
        )
        await db.commit()
        return db.total_changes > before
    except Exception:
        return False


async def get_all_grades(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT course_name, course_id, score, credit, gpa, semester, exam_type, first_seen FROM grades ORDER BY semester DESC, course_name"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_grade_count(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM grades")
    row = await cursor.fetchone()
    return row[0] if row else 0


async def get_config(db: aiosqlite.Connection, key: str) -> str | None:
    cursor = await db.execute("SELECT value FROM config WHERE key=?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_config(db: aiosqlite.Connection, key: str, value: str):
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)
    )
    await db.commit()
