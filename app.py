"""Flask application for hostel mess bookings and crowd management."""

from datetime import datetime
from functools import wraps
import base64
from io import BytesIO
import os
import secrets
import sqlite3
import tempfile

import qrcode
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# Vercel may import this root module directly as a Python function, bypassing
# api/index.py. Use its writable temporary directory before database.py loads.
if os.environ.get("VERCEL") == "1":
    os.environ.setdefault(
        "MESS_DATABASE",
        os.path.join(tempfile.gettempdir(), "smart-mess-flow.db"),
    )

from database import get_db, init_db


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
init_db(generate_password_hash)


def current_student():
    """Return the logged-in student record, or None for another account type."""
    if session.get("role") != "student":
        return None
    with get_db() as db:
        return db.execute("SELECT * FROM students WHERE id = ?", (session["user_id"],)).fetchone()


def require_role(*roles):
    """Protect pages and actions by account role."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                if not session.get("user_id"):
                    flash("Please sign in to continue.", "error")
                    return redirect(url_for("login"))
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def occupancy_summary(db):
    """Build the live occupancy and queue information used by the dashboard."""
    inside_count = db.execute(
        "SELECT COUNT(*) AS total FROM bookings WHERE status = 'entered'"
    ).fetchone()["total"]
    slots = db.execute(
        """
        SELECT slot_id, meal, start_time, end_time, capacity, booked,
               MAX(capacity - booked, 0) AS seats_left
        FROM slots ORDER BY CASE meal
            WHEN 'breakfast' THEN 1 WHEN 'lunch' THEN 2 ELSE 3 END, start_time
        """
    ).fetchall()
    counters = db.execute(
        "SELECT counter_id, name, queue_length FROM counters ORDER BY counter_id"
    ).fetchall()
    if counters:
        students_ahead = sum(counter["queue_length"] for counter in counters)
        waiting_minutes = round((students_ahead / len(counters)) * 2)
    else:
        waiting_minutes = 0
    return inside_count, slots, counters, waiting_minutes


@app.route("/")
def home():
    if session.get("role") == "student":
        return redirect(url_for("dashboard"))
    if session.get("role") == "staff":
        return redirect(url_for("scanner"))
    if session.get("role") == "admin":
        return redirect(url_for("admin"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        student_type = request.form.get("type", "")
        if not student_id or not name or not password or student_type not in ("hostel", "day"):
            flash("Complete every field with a valid student type.", "error")
            return render_template("register.html")
        try:
            with get_db() as db:
                db.execute(
                    """
                    INSERT INTO students (id, name, password, type, paid)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (student_id, name, generate_password_hash(password), student_type),
                )
        except sqlite3.IntegrityError:
            flash("That student ID is already registered.", "error")
            return render_template("register.html")
        flash("Account created. You can now sign in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "")
        with get_db() as db:
            student = db.execute("SELECT * FROM students WHERE id = ?", (user_id,)).fetchone()
            staff_user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if student and check_password_hash(student["password"], password):
            session.clear()
            session.update(user_id=student["id"], name=student["name"], role="student")
            return redirect(url_for("dashboard"))
        if staff_user and check_password_hash(staff_user["password_hash"], password):
            session.clear()
            session.update(
                user_id=staff_user["id"],
                name=staff_user["name"],
                role=staff_user["role"],
            )
            return redirect(url_for("scanner" if staff_user["role"] == "staff" else "admin"))
        flash("ID or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@require_role("student")
def dashboard():
    with get_db() as db:
        inside_count, slots, counters, waiting_minutes = occupancy_summary(db)
        bookings = db.execute(
            """
            SELECT b.booking_id, b.status, s.meal, s.start_time, s.end_time
            FROM bookings b JOIN slots s ON s.slot_id = b.slot_id
            WHERE b.student_id = ? AND date(b.created_at) = date('now', 'localtime')
            ORDER BY b.booking_id DESC
            """,
            (session["user_id"],),
        ).fetchall()
        student = db.execute(
            "SELECT type, paid FROM students WHERE id = ?", (session["user_id"],)
        ).fetchone()
    return render_template(
        "dashboard.html",
        inside_count=inside_count,
        slots=slots,
        counters=counters,
        waiting_minutes=waiting_minutes,
        bookings=bookings,
        student=student,
    )


@app.get("/api/dashboard")
@require_role("student")
def dashboard_data():
    with get_db() as db:
        inside_count, slots, counters, waiting_minutes = occupancy_summary(db)
    return jsonify(
        inside_count=inside_count,
        slots=[dict(slot) for slot in slots],
        counters=[dict(counter) for counter in counters],
        waiting_minutes=waiting_minutes,
    )


@app.route("/book", methods=["GET", "POST"])
@require_role("student")
def book():
    with get_db() as db:
        student = db.execute(
            "SELECT type, paid FROM students WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if request.method == "POST":
            meal = request.form.get("meal", "")
            chosen_slot = request.form.get("slot_id", type=int)
            if student["type"] == "day" and not student["paid"]:
                flash("Pay first before booking a meal.", "error")
                return redirect(url_for("payment"))
            if meal not in ("breakfast", "lunch", "dinner") or not chosen_slot:
                flash("Choose a valid meal and time slot.", "error")
                return redirect(url_for("book"))

            # Lock writes while checking and reserving so simultaneous requests
            # cannot exceed a slot's capacity.
            db.execute("BEGIN IMMEDIATE")
            already_booked = db.execute(
                """
                SELECT 1 FROM bookings b JOIN slots s ON s.slot_id = b.slot_id
                WHERE b.student_id = ? AND s.meal = ?
                  AND date(b.created_at) = date('now', 'localtime')
                """,
                (session["user_id"], meal),
            ).fetchone()
            if already_booked:
                db.rollback()
                flash("You already have a booking for this meal today.", "error")
                return redirect(url_for("book"))
            selected = db.execute(
                "SELECT slot_id, meal, start_time FROM slots WHERE slot_id = ?",
                (chosen_slot,),
            ).fetchone()
            if not selected or selected["meal"] != meal:
                db.rollback()
                flash("That slot does not belong to the selected meal.", "error")
                return redirect(url_for("book"))
            candidates = db.execute(
                """
                SELECT slot_id FROM slots
                WHERE meal = ? AND start_time >= ?
                ORDER BY start_time
                """,
                (meal, selected["start_time"]),
            ).fetchall()
            reserved_slot = None
            for candidate in candidates:
                changed = db.execute(
                    """
                    UPDATE slots SET booked = booked + 1
                    WHERE slot_id = ? AND booked < capacity
                    """,
                    (candidate["slot_id"],),
                ).rowcount
                if changed:
                    reserved_slot = candidate["slot_id"]
                    break
            if reserved_slot is None:
                db.rollback()
                flash("Mess full: no seats are available in this or a later slot.", "error")
                return redirect(url_for("book"))
            cursor = db.execute(
                "INSERT INTO bookings (student_id, slot_id) VALUES (?, ?)",
                (session["user_id"], reserved_slot),
            )
            booking_id = cursor.lastrowid
            db.commit()
            flash(f"Slot booked successfully. Your booking ID is {booking_id}.", "success")
            return redirect(url_for("pass_page", booking_id=booking_id))

        slots = db.execute(
            """
            SELECT *, MAX(capacity - booked, 0) AS seats_left FROM slots
            ORDER BY CASE meal
                WHEN 'breakfast' THEN 1 WHEN 'lunch' THEN 2 ELSE 3 END, start_time
            """
        ).fetchall()
    return render_template("book.html", slots=slots, student=student)


@app.route("/payment", methods=["GET", "POST"])
@require_role("student")
def payment():
    with get_db() as db:
        student = db.execute(
            "SELECT type, paid FROM students WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if student["type"] != "day":
            flash("Online meal payment is only needed for day scholars.", "success")
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            db.execute("UPDATE students SET paid = 1 WHERE id = ?", (session["user_id"],))
            flash("Demo payment successful. You can now book a meal.", "success")
            return redirect(url_for("book"))
    return render_template("payment.html", student=student)


@app.get("/pass/<int:booking_id>")
@require_role("student")
def pass_page(booking_id):
    with get_db() as db:
        booking = db.execute(
            """
            SELECT b.booking_id, b.student_id, b.status, s.meal, s.start_time,
                   s.end_time, st.name
            FROM bookings b JOIN slots s ON s.slot_id = b.slot_id
            JOIN students st ON st.id = b.student_id
            WHERE b.booking_id = ? AND b.student_id = ?
            """,
            (booking_id, session["user_id"]),
        ).fetchone()
    if not booking:
        abort(404)
    image = qrcode.make(str(booking_id))
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    qr_data = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    return render_template("pass.html", booking=booking, qr_data=qr_data)


@app.route("/staff/scanner", methods=["GET", "POST"])
@require_role("staff", "admin")
def scanner():
    if request.method == "POST":
        booking_id = request.form.get("booking_id", type=int)
        action = request.form.get("action", "")
        if not booking_id or action not in ("entry", "exit"):
            flash("Enter a valid booking ID and choose Entry or Exit.", "error")
            return redirect(url_for("scanner"))

        with get_db() as db:
            db.execute("BEGIN IMMEDIATE")
            booking = db.execute(
                """
                SELECT b.booking_id, b.status, s.start_time, s.end_time
                FROM bookings b JOIN slots s ON s.slot_id = b.slot_id
                WHERE b.booking_id = ?
                """,
                (booking_id,),
            ).fetchone()
            if not booking:
                db.rollback()
                flash("Booking not found.", "error")
                return redirect(url_for("scanner"))
            if action == "entry":
                now = datetime.now().strftime("%H:%M")
                if booking["status"] != "booked":
                    db.rollback()
                    flash("Entry requires a booking with status 'booked'.", "error")
                    return redirect(url_for("scanner"))
                if not booking["start_time"] <= now <= booking["end_time"]:
                    db.rollback()
                    flash("Entry is only allowed during the booked slot.", "error")
                    return redirect(url_for("scanner"))
                counter = db.execute(
                    "SELECT counter_id FROM counters ORDER BY queue_length, counter_id LIMIT 1"
                ).fetchone()
                if not counter:
                    db.rollback()
                    flash("No food counters are configured. Ask an admin to add one.", "error")
                    return redirect(url_for("scanner"))
                db.execute("UPDATE bookings SET status = 'entered' WHERE booking_id = ?", (booking_id,))
                db.execute(
                    "UPDATE counters SET queue_length = queue_length + 1 WHERE counter_id = ?",
                    (counter["counter_id"],),
                )
                db.execute(
                    "INSERT INTO booking_counters (booking_id, counter_id) VALUES (?, ?)",
                    (booking_id, counter["counter_id"]),
                )
                db.commit()
                flash(f"Entry approved. Assigned to counter {counter['counter_id']}.", "success")
            else:
                if booking["status"] != "entered":
                    db.rollback()
                    flash("Exit requires a booking with status 'entered'.", "error")
                    return redirect(url_for("scanner"))
                assignment = db.execute(
                    "SELECT counter_id FROM booking_counters WHERE booking_id = ?",
                    (booking_id,),
                ).fetchone()
                if not assignment:
                    db.rollback()
                    flash("No counter assignment is recorded for this booking.", "error")
                    return redirect(url_for("scanner"))
                db.execute("UPDATE bookings SET status = 'exited' WHERE booking_id = ?", (booking_id,))
                db.execute(
                    "UPDATE counters SET queue_length = MAX(queue_length - 1, 0) WHERE counter_id = ?",
                    (assignment["counter_id"],),
                )
                db.execute("DELETE FROM booking_counters WHERE booking_id = ?", (booking_id,))
                db.commit()
                flash("Exit recorded. Thank you!", "success")
        return redirect(url_for("scanner"))

    return render_template("scanner.html")


@app.route("/admin", methods=["GET", "POST"])
@require_role("admin")
def admin():
    with get_db() as db:
        if request.method == "POST":
            action = request.form.get("action")
            if action == "save_slot":
                slot_id = request.form.get("slot_id", type=int)
                meal = request.form.get("meal", "")
                start_time = request.form.get("start_time", "")
                end_time = request.form.get("end_time", "")
                capacity = request.form.get("capacity", type=int)
                try:
                    valid_times = (
                        datetime.strptime(start_time, "%H:%M")
                        < datetime.strptime(end_time, "%H:%M")
                    )
                except ValueError:
                    valid_times = False
                if (
                    meal not in ("breakfast", "lunch", "dinner")
                    or not capacity
                    or capacity < 1
                    or not valid_times
                ):
                    flash("Enter a valid meal, time range, and positive capacity.", "error")
                elif slot_id:
                    booked = db.execute(
                        "SELECT booked FROM slots WHERE slot_id = ?", (slot_id,)
                    ).fetchone()
                    if not booked:
                        flash("Slot not found.", "error")
                    elif capacity < booked["booked"]:
                        flash("Capacity cannot be lower than the number already booked.", "error")
                    else:
                        db.execute(
                            """
                            UPDATE slots SET meal = ?, start_time = ?, end_time = ?, capacity = ?
                            WHERE slot_id = ?
                            """,
                            (meal, start_time, end_time, capacity, slot_id),
                        )
                        flash("Slot updated.", "success")
                else:
                    db.execute(
                        """
                        INSERT INTO slots (meal, start_time, end_time, capacity)
                        VALUES (?, ?, ?, ?)
                        """,
                        (meal, start_time, end_time, capacity),
                    )
                    flash("Slot added.", "success")
                return redirect(url_for("admin"))
            if action == "add_counter":
                name = request.form.get("name", "").strip()
                if name:
                    db.execute("INSERT INTO counters (name) VALUES (?)", (name,))
                    flash("Counter added.", "success")
                else:
                    flash("Counter name cannot be blank.", "error")
                return redirect(url_for("admin"))

        slots = db.execute("SELECT * FROM slots ORDER BY meal, start_time").fetchall()
        counters = db.execute("SELECT * FROM counters ORDER BY counter_id").fetchall()
        bookings = db.execute(
            """
            SELECT b.booking_id, b.student_id, st.name AS student_name, s.meal,
                   s.start_time, s.end_time, b.status, b.created_at
            FROM bookings b JOIN students st ON st.id = b.student_id
            JOIN slots s ON s.slot_id = b.slot_id
            ORDER BY b.created_at DESC, b.booking_id DESC
            """
        ).fetchall()
    return render_template("admin.html", slots=slots, counters=counters, bookings=bookings)


if __name__ == "__main__":
    app.run(debug=False)
