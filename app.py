from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "library_secret_enhanced"

# ---------- MYSQL CONFIGURATION ----------
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'madhavG2003',
    'database': 'library'
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# ---------- ADMIN USER CREATION ----------
@app.before_request
def create_admin():
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", ("admin",))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password, is_admin) VALUES (%s, %s, %s)",
                    ("admin", generate_password_hash("admin"), 1))
        con.commit()
    cur.close()
    con.close()

# ---------- ROUTES ----------
@app.route("/")
def home():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if password != confirm:
            flash("Passwords do not match!", "danger")
        else:
            con = get_db()
            cur = con.cursor()
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                flash("Username already taken!", "danger")
            else:
                cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)",
                            (username, generate_password_hash(password)))
                con.commit()
                flash("Registration successful! Please login.", "success")
                return redirect(url_for("login"))
            cur.close()
            con.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")

        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT id, password, is_admin FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        con.close()

        if user and check_password_hash(user[1], password):
            session["user_id"] = user[0]
            session["username"] = username
            session["is_admin"] = bool(user[2])
            flash(f"Welcome {username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    q = request.args.get("q", "")
    con = get_db()
    cur = con.cursor(dictionary=True)
    if q:
        cur.execute("SELECT * FROM books WHERE title LIKE %s OR author LIKE %s", (f"%{q}%", f"%{q}%"))
    else:
        cur.execute("SELECT * FROM books")
    books = cur.fetchall()
    cur.close()
    con.close()
    return render_template("dashboard.html", books=books, is_admin=session["is_admin"], search_query=q)

@app.route("/borrow_return", methods=["POST"])
def borrow_return():
    if "user_id" not in session:
        return redirect(url_for("login"))

    book_id = request.form.get("book_id")
    action = request.form.get("action")
    name = request.form.get("borrower_name", "")
    phone = request.form.get("phone", "")

    if not book_id or not book_id.isdigit():
        flash("Invalid book selected.", "danger")
        return redirect(url_for("dashboard"))

    book_id = int(book_id)
    con = get_db()
    cur = con.cursor()

    if action == "borrow":
        cur.execute("SELECT available FROM books WHERE id = %s", (book_id,))
        result = cur.fetchone()
        if result and result[0]:
            cur.execute("UPDATE books SET available = 0 WHERE id = %s", (book_id,))
            cur.execute("""
                INSERT INTO transactions (user_id, book_id, type, borrower_name, phone)
                VALUES (%s, %s, 'borrow', %s, %s)
            """, (session["user_id"], book_id, name.strip(), phone.strip()))
            flash("Book borrowed successfully!", "success")
        else:
            flash("Book is not available for borrowing.", "warning")

    elif action == "return":
        # Fetch the borrower's name from the most recent borrow transaction
        cur.execute("""
            SELECT borrower_name FROM transactions
            WHERE book_id = %s AND type = 'borrow'
            ORDER BY date DESC LIMIT 1
        """, (book_id,))
        borrow_info = cur.fetchone()
        borrower_name = borrow_info[0] if borrow_info else "-"

        # Update availability and log return with borrower's name
        cur.execute("UPDATE books SET available = 1 WHERE id = %s", (book_id,))
        cur.execute("""
            INSERT INTO transactions (user_id, book_id, type, borrower_name)
            VALUES (%s, %s, 'return', %s)
        """, (session["user_id"], book_id, borrower_name))
        flash("Book returned successfully!", "success")

    con.commit()
    cur.close()
    con.close()
    return redirect(url_for("dashboard"))

@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    con = get_db()
    cur = con.cursor(dictionary=True)

    if session.get("is_admin"):
        cur.execute("""
            SELECT t.id, u.username, b.title, t.type, t.date, t.borrower_name, t.phone 
            FROM transactions t 
            JOIN users u ON t.user_id = u.id 
            JOIN books b ON t.book_id = b.id 
            ORDER BY t.date DESC
        """)
        rows = cur.fetchall()
        admin_view = True
    else:
        cur.execute("""
            SELECT t.id, b.title, t.type, t.date 
            FROM transactions t 
            JOIN books b ON t.book_id = b.id 
            WHERE t.user_id = %s ORDER BY t.date DESC
        """, (session["user_id"],))
        rows = cur.fetchall()
        admin_view = False

    cur.close()
    con.close()
    return render_template("history.html", transactions=rows, admin_view=admin_view)

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("is_admin"):
        return redirect(url_for("dashboard"))

    con = get_db()
    cur = con.cursor()
    stats = {
        "total_books": 0,
        "available_books": 0,
        "total_users": 0,
        "borrowed_today": 0
    }
    cur.execute("SELECT COUNT(*) FROM books")
    stats["total_books"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM books WHERE available = 1")
    stats["available_books"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
    stats["total_users"] = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE DATE(date) = CURDATE() AND type = 'borrow'
    """)
    stats["borrowed_today"] = cur.fetchone()[0]
    cur.close()
    con.close()
    return render_template("admin_dashboard.html", stats=stats)

@app.route("/admin/add_book", methods=["GET", "POST"])
def add_book():
    if not session.get("is_admin"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form.get("title").strip()
        author = request.form.get("author").strip()

        if title and author:
            con = get_db()
            cur = con.cursor()
            cur.execute("INSERT INTO books (title, author, available) VALUES (%s, %s, 1)", (title, author))
            con.commit()
            cur.close()
            con.close()
            flash("Book added successfully.", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Please provide valid book title and author.", "warning")
    return render_template("add_book.html")

if __name__ == "__main__":
    app.run(debug=True)