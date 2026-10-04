import os
import random
import sqlite3
import uuid
from datetime import datetime, timedelta

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "replace-with-a-long-random-secret-key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

WARDS = [
    "Ward 1",
    "Ward 2",
    "Ward 3",
    "Ward 4",
    "Ward 5",
    "Ward 6",
    "Ward 7",
    "Ward 8",
    "Ward 9",
    "Ward 10",
    "Ward 11",
    "Ward 12",
    "Ward 13",
    "Ward 14",
    "Ward 15",
    "Ward 16",
    "Ward 17",
    "Ward 18",
    "Ward 19",
    "Ward 20",
]

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def get_db():
    conn = sqlite3.connect("complaint_portal.db")
    conn.row_factory = sqlite3.Row
    return conn


def add_activity(complaint_id, action, actor, details):
    conn = get_db()
    conn.execute(
        "INSERT INTO activity_log (complaint_id, action, actor, details) VALUES (?, ?, ?, ?)",
        (complaint_id, action, actor, details),
    )
    conn.commit()
    conn.close()


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            ward_id INTEGER,
            name TEXT NOT NULL,
            language TEXT DEFAULT 'en'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ward_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            issue TEXT NOT NULL,
            details TEXT NOT NULL,
            photo TEXT,
            language TEXT DEFAULT 'en',
            otp TEXT NOT NULL,
            otp_verified INTEGER DEFAULT 0,
            status TEXT DEFAULT 'otp_pending',
            assigned_to INTEGER,
            verified_by INTEGER,
            verification_comment TEXT,
            resolution TEXT,
            resolved_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            due_date TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    create_default_users()
    conn.close()


def create_default_users():
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        conn.close()
        return

    default_users = [
        {
            "username": "chairperson",
            "password": generate_password_hash("chair123"),
            "role": "chairperson",
            "ward_id": None,
            "name": "Chairperson",
            "language": "en",
        }
    ]

    for ward_num in range(1, 21):
        default_users.append(
            {
                "username": f"ward{ward_num}",
                "password": generate_password_hash("ward123"),
                "role": "ward_head",
                "ward_id": ward_num,
                "name": f"Ward {ward_num} Head",
                "language": "en",
            }
        )
        default_users.append(
            {
                "username": f"v{ward_num}",
                "password": generate_password_hash("verify123"),
                "role": "verification_member",
                "ward_id": ward_num,
                "name": f"Verification Member {ward_num}",
                "language": "en",
            }
        )

    for user in default_users:
        conn.execute(
            "INSERT INTO users (username, password, role, ward_id, name, language) VALUES (?, ?, ?, ?, ?, ?)",
            (
                user["username"],
                user["password"],
                user["role"],
                user["ward_id"],
                user["name"],
                user["language"],
            ),
        )

    conn.commit()
    conn.close()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def ward_label(ward_id):
    return WARDS[ward_id - 1] if 1 <= ward_id <= 20 else "All Wards"


def send_sms(phone, otp):
    try:
        from twilio.rest import Client
    except Exception:
        print(f"[SMS STUB] OTP for {phone}: {otp}")
        return True

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")

    if not (account_sid and auth_token and from_number):
        print(f"[SMS STUB] OTP for {phone}: {otp}")
        return True

    client = Client(account_sid, auth_token)
    try:
        message = client.messages.create(
            body=f"Your OTP for the Mumbai complaint portal is {otp}.",
            from_=from_number,
            to=phone,
        )
        return bool(message.sid)
    except Exception:
        print(f"[SMS STUB] OTP for {phone}: {otp}")
        return True


@app.route("/")
def index():
    return render_template("index.html", wards=WARDS)


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/submit_complaint", methods=["POST"])
def submit_complaint():
    ward_id = int(request.form["ward_id"])
    name = request.form["name"].strip()
    phone = request.form["phone"].strip()
    issue = request.form["issue"].strip()
    details = request.form["details"].strip()
    language = request.form.get("language", "en")

    if not (name and phone and issue and details):
        flash("Please complete all required complaint details.", "error")
        return redirect(url_for("index"))

    photo_name = None
    photo_file = request.files.get("photo")
    if photo_file and photo_file.filename:
        if not allowed_file(photo_file.filename):
            flash("Only PNG, JPG, JPEG, and WEBP images are allowed.", "error")
            return redirect(url_for("index"))
        filename = secure_filename(photo_file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_name))
        photo_name = unique_name

    otp = str(random.randint(100000, 999999))
    due_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO complaints (
            ward_id, name, phone, issue, details, photo, language, otp,
            otp_verified, status, due_date, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'otp_pending', ?, CURRENT_TIMESTAMP)
        """,
        (ward_id, name, phone, issue, details, photo_name, language, otp, due_date),
    )
    complaint_id = cursor.lastrowid
    conn.commit()
    conn.close()

    send_sms(phone, otp)
    add_activity(complaint_id, "Complaint created", "citizen", f"Complaint submitted for {ward_label(ward_id)}")

    return redirect(url_for("otp_page", complaint_id=complaint_id))


@app.route("/otp/<int:complaint_id>")
def otp_page(complaint_id):
    return render_template("otp.html", complaint_id=complaint_id)


@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    complaint_id = int(request.form["complaint_id"])
    entered_otp = request.form["otp"].strip()

    conn = get_db()
    complaint = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    conn.close()

    if not complaint:
        flash("Complaint not found.", "error")
        return redirect(url_for("index"))

    if complaint["otp"] != entered_otp:
        flash("Invalid OTP. Please try again.", "error")
        return redirect(url_for("otp_page", complaint_id=complaint_id))

    conn = get_db()
    conn.execute(
        "UPDATE complaints SET otp_verified = 1, status = 'ward_pending' WHERE id = ?",
        (complaint_id,),
    )
    conn.commit()
    conn.close()

    add_activity(complaint_id, "OTP verified", "system", "Citizen mobile number verified")
    flash("OTP verified successfully. Your complaint is sent to the ward head for review.", "success")
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")
        return render_template("login.html")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    conn = get_db()

    if user["role"] == "chairperson":
        complaints = conn.execute(
            """
            SELECT c.*, u.name AS assigned_name, v.name AS verifier_name
            FROM complaints c
            LEFT JOIN users u ON u.id = c.assigned_to
            LEFT JOIN users v ON v.id = c.verified_by
            ORDER BY c.id DESC
            """
        ).fetchall()
        verifier_list = conn.execute(
            "SELECT * FROM users WHERE role = 'verification_member' ORDER BY ward_id, name"
        ).fetchall()
    elif user["role"] == "ward_head":
        complaints = conn.execute(
            """
            SELECT c.*, u.name AS assigned_name, v.name AS verifier_name
            FROM complaints c
            LEFT JOIN users u ON u.id = c.assigned_to
            LEFT JOIN users v ON v.id = c.verified_by
            WHERE c.ward_id = ?
            ORDER BY c.id DESC
            """,
            (user["ward_id"],),
        ).fetchall()
        verifier_list = conn.execute(
            "SELECT * FROM users WHERE role = 'verification_member' AND ward_id = ? ORDER BY name",
            (user["ward_id"],),
        ).fetchall()
    elif user["role"] == "verification_member":
        complaints = conn.execute(
            """
            SELECT c.*, u.name AS assigned_name, v.name AS verifier_name
            FROM complaints c
            LEFT JOIN users u ON u.id = c.assigned_to
            LEFT JOIN users v ON v.id = c.verified_by
            WHERE c.assigned_to = ?
            ORDER BY c.id DESC
            """,
            (user["id"],),
        ).fetchall()
        verifier_list = []
    else:
        complaints = []
        verifier_list = []

    conn.close()

    return render_template(
        "dashboard.html",
        user=user,
        complaints=complaints,
        wards=WARDS,
        verifier_list=verifier_list,
    )


@app.route("/assign_verifier", methods=["POST"])
def assign_verifier():
    user = current_user()
    if not user or user["role"] != "ward_head":
        flash("Only ward heads can assign verification members.", "error")
        return redirect(url_for("login"))

    complaint_id = int(request.form["complaint_id"])
    verifier_id = int(request.form["verifier_id"])

    conn = get_db()
    complaint = conn.execute(
        "SELECT * FROM complaints WHERE id = ? AND ward_id = ?",
        (complaint_id, user["ward_id"]),
    ).fetchone()

    if not complaint:
        conn.close()
        flash("Complaint not found in your ward.", "error")
        return redirect(url_for("dashboard"))

    conn.execute(
        "UPDATE complaints SET assigned_to = ?, status = 'verification_pending' WHERE id = ?",
        (verifier_id, complaint_id),
    )
    conn.commit()
    conn.close()

    add_activity(complaint_id, "Verification assigned", user["name"], f"Assigned to verifier ID {verifier_id}")
    flash("Verification member assigned successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/verify_decision", methods=["POST"])
def verify_decision():
    user = current_user()
    if not user or user["role"] != "verification_member":
        flash("Only verification members can approve or reject complaints.", "error")
        return redirect(url_for("login"))

    complaint_id = int(request.form["complaint_id"])
    decision = request.form["decision"]
    comment = request.form.get("comment", "").strip()

    conn = get_db()
    complaint = conn.execute(
        "SELECT * FROM complaints WHERE id = ? AND assigned_to = ?",
        (complaint_id, user["id"]),
    ).fetchone()
    if not complaint:
        conn.close()
        flash("Complaint is not assigned to you.", "error")
        return redirect(url_for("dashboard"))

    if decision == "approve":
        status = "verified"
        action = "Complaint approved"
    else:
        status = "rejected"
        action = "Complaint rejected"

    conn.execute(
        "UPDATE complaints SET status = ?, verified_by = ?, verification_comment = ? WHERE id = ?",
        (status, user["id"], comment, complaint_id),
    )
    conn.commit()
    conn.close()

    add_activity(complaint_id, action, user["name"], comment or "No comment provided")
    flash(f"Complaint {decision}d successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/resolve_complaint", methods=["POST"])
def resolve_complaint():
    user = current_user()
    if not user or user["role"] != "ward_head":
        flash("Only ward heads can resolve complaints.", "error")
        return redirect(url_for("login"))

    complaint_id = int(request.form["complaint_id"])
    resolution = request.form.get("resolution", "").strip()

    conn = get_db()
    complaint = conn.execute(
        "SELECT * FROM complaints WHERE id = ? AND ward_id = ?",
        (complaint_id, user["ward_id"]),
    ).fetchone()
    if not complaint:
        conn.close()
        flash("Complaint not found in your ward.", "error")
        return redirect(url_for("dashboard"))

    if complaint["status"] != "verified":
        conn.close()
        flash("Complaint must be approved by verification member before resolution.", "error")
        return redirect(url_for("dashboard"))

    conn.execute(
        "UPDATE complaints SET status = 'resolved', resolution = ?, resolved_by = ? WHERE id = ?",
        (resolution, user["id"], complaint_id),
    )
    conn.commit()
    conn.close()

    add_activity(complaint_id, "Complaint resolved", user["name"], resolution or "Resolved without comments")
    flash("Complaint marked resolved successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/activity")
def activity():
    user = current_user()
    if not user:
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    conn = get_db()
    if user["role"] == "chairperson":
        logs = conn.execute(
            """
            SELECT a.*, c.name AS complaint_name, c.issue
            FROM activity_log a
            LEFT JOIN complaints c ON c.id = a.complaint_id
            ORDER BY a.id DESC
            """
        ).fetchall()
    elif user["role"] == "ward_head":
        logs = conn.execute(
            """
            SELECT a.*, c.name AS complaint_name, c.issue
            FROM activity_log a
            LEFT JOIN complaints c ON c.id = a.complaint_id
            WHERE c.ward_id = ?
            ORDER BY a.id DESC
            """,
            (user["ward_id"],),
        ).fetchall()
    elif user["role"] == "verification_member":
        logs = conn.execute(
            """
            SELECT a.*, c.name AS complaint_name, c.issue
            FROM activity_log a
            LEFT JOIN complaints c ON c.id = a.complaint_id
            WHERE c.assigned_to = ? OR c.ward_id = ?
            ORDER BY a.id DESC
            """,
            (user["id"], user["ward_id"]),
        ).fetchall()
    else:
        logs = []

    conn.close()
    return render_template("activity.html", user=user, logs=logs)


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
