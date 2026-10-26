"""SQLite setup and seed data for Smart Mess Flow."""

import os
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(os.environ.get("MESS_DATABASE", Path(__file__).with_name("mess.db")))


def get_db():
    """Open a database connection with rows that can be accessed by column name."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(password_hasher):
    """Create tables and insert demo records the first time the app is run."""
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('hostel', 'day')),
                paid INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('staff', 'admin'))
            );

            CREATE TABLE IF NOT EXISTS slots (
                slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal TEXT NOT NULL CHECK (meal IN ('breakfast', 'lunch', 'dinner')),
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK (capacity > 0),
                booked INTEGER NOT NULL DEFAULT 0 CHECK (booked >= 0)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL REFERENCES students(id),
                slot_id INTEGER NOT NULL REFERENCES slots(slot_id),
                status TEXT NOT NULL DEFAULT 'booked'
                    CHECK (status IN ('booked', 'entered', 'exited')),
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS counters (
                counter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                queue_length INTEGER NOT NULL DEFAULT 0 CHECK (queue_length >= 0)
            );

            CREATE TABLE IF NOT EXISTS booking_counters (
                booking_id INTEGER PRIMARY KEY REFERENCES bookings(booking_id),
                counter_id INTEGER NOT NULL REFERENCES counters(counter_id)
            );
            """
        )

        slots_exist = db.execute("SELECT 1 FROM slots LIMIT 1").fetchone()
        if not slots_exist:
            seed_slots = []
            for meal, start_hour in (("breakfast", 7), ("lunch", 12), ("dinner", 18)):
                for index in range(3):
                    start = start_hour * 60 + index * 30
                    end = start + 30
                    seed_slots.append(
                        (
                            meal,
                            f"{start // 60:02d}:{start % 60:02d}",
                            f"{end // 60:02d}:{end % 60:02d}",
                            50,
                        )
                    )
            db.executemany(
                "INSERT INTO slots (meal, start_time, end_time, capacity) VALUES (?, ?, ?, ?)",
                seed_slots,
            )

        if not db.execute("SELECT 1 FROM counters LIMIT 1").fetchone():
            db.executemany(
                "INSERT INTO counters (name) VALUES (?)",
                [("Food Counter 1",), ("Food Counter 2",), ("Food Counter 3",)],
            )

        demo_students = [
            ("hostel01", "Aarav Student", password_hasher("hostel123"), "hostel", 1),
            ("day01", "Mira DayScholar", password_hasher("day123"), "day", 0),
        ]
        db.executemany(
            """
            INSERT OR IGNORE INTO students (id, name, password, type, paid)
            VALUES (?, ?, ?, ?, ?)
            """,
            demo_students,
        )
        demo_users = [
            ("staff01", "Mess Staff", password_hasher("staff123"), "staff"),
            ("admin01", "Mess Admin", password_hasher("admin123"), "admin"),
        ]
        db.executemany(
            """
            INSERT OR IGNORE INTO users (id, name, password_hash, role)
            VALUES (?, ?, ?, ?)
            """,
            demo_users,
        )
