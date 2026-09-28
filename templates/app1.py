from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import io
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import csv

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Database setup
def init_db():
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bank_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_name TEXT,
                    account_type TEXT,
                    balance REAL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    amount REAL,
                    description TEXT,
                    created_at TEXT,
                    user_id INTEGER,
                    account_id INTEGER)""")
    conn.commit()
    conn.close()


# --- PDF Download Route ---
@app.route("/download_pdf")
def download_pdf():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("expenses.db")
    conn.row_factory = sqlite3.Row
    
    c = conn.cursor()

    # ✅ Correct query: join expenses with bank_accounts
    c.execute("""SELECT e.created_at, e.category, e.amount, e.description, 
                        b.account_name
                 FROM expenses e
                 JOIN bank_accounts b ON e.account_id = b.id
                 WHERE e.user_id=? ORDER BY e.created_at DESC""",
              (session["user_id"],))
    expenses = c.fetchall()
    conn.close()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(200, 750, "Expense Statement")

    p.setFont("Helvetica", 10)
    y = 720
    p.drawString(50, y, "Date")
    p.drawString(120, y, "Category")
    p.drawString(200, y, "Amount")
    p.drawString(260, y, "Description")
    p.drawString(400, y, "Account")
    # p.drawString(480, y, "Type")
    y -= 20

    for row in expenses:

        p.drawString(50, y, str(row["created_at"][:10]))
        p.drawString(120, y, row["category"])
        p.drawString(200, y, str(row["amount"]))
        p.drawString(260, y, row["description"][:20])  # truncate long text
        p.drawString(400, y, row["account_name"])
        
        y -= 20
        if y < 50:  # new page if space runs out
            p.showPage()
            y = 750

    p.showPage()
    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name="expense_statement.pdf",
                     mimetype="application/pdf")


# --- CSV Download Route ---
@app.route("/download_csv")
def download_csv():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("expenses.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""SELECT e.created_at, e.category, e.amount, e.description,
                        b.account_name, b.account_type
                 FROM expenses e
                 LEFT JOIN bank_accounts b ON e.account_id = b.id
                 WHERE e.user_id=? ORDER BY e.created_at DESC""",
              (session["user_id"],))
    expenses = c.fetchall()
    conn.close()

    # Write CSV to a text buffer then convert to bytes
    s = io.StringIO()
    writer = csv.writer(s)
    # Header
    writer.writerow(["Date", "Category", "Amount", "Description", "Account", "Account Type"])
    # Rows
    for row in expenses:
        created_at = row["created_at"] if row["created_at"] is not None else ""
        category = row["category"] if row["category"] is not None else ""
        amount = row["amount"] if row["amount"] is not None else ""
        description = row["description"] if row["description"] is not None else ""
        account_name = row["account_name"] if row["account_name"] is not None else ""
        account_type = row["account_type"] if row["account_type"] is not None else ""
        writer.writerow([created_at, category, amount, description, account_name, account_type])

    mem = io.BytesIO()
    mem.write(s.getvalue().encode("utf-8"))
    mem.seek(0)
    s.close()

    return send_file(mem, as_attachment=True,
                     download_name="expense_statement.csv",
                     mimetype="text/csv")


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        conn = sqlite3.connect("expenses.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[2], password):
            session["user_id"] = user[0]
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials!", "error")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        conn = sqlite3.connect("expenses.db")
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            flash("Account created successfully! Please log in.", "success")
        except sqlite3.IntegrityError:
            flash("Username already exists!", "error")
        conn.close()
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()

    if request.method == "POST":
        category = request.form["category"]
        amount = float(request.form["amount"])
        description = request.form["description"]
        account_id = int(request.form["account_id"])
        if "date" in request.form and request.form["date"]:
            created_at = request.form["date"] + " " + datetime.now().strftime("%H:%M:%S")
        else:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get account type
        c.execute("SELECT account_type, balance FROM bank_accounts WHERE id=?", (account_id,))
        acc_type, current_balance = c.fetchone()

        # Adjust balance
        if acc_type == "Debit":
            new_balance = current_balance - amount
        elif acc_type == "Credit":
            new_balance = current_balance + amount
        else:
            new_balance = current_balance

        # Update account balance
        c.execute("UPDATE bank_accounts SET balance=? WHERE id=?", (new_balance, account_id))

        # ✅ Insert expense with balance snapshot included
        c.execute("""INSERT INTO expenses (category, amount, description, created_at, user_id, account_id, balance) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (category, amount, description, created_at, session["user_id"], account_id, new_balance))

        conn.commit()
        conn.close()

        flash("Expense added successfully!", "success")
        return redirect(url_for("dashboard"))


    c.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id=? GROUP BY category", (session["user_id"],))
    data = c.fetchall()

    c.execute("""SELECT e.category, e.amount, e.description, e.created_at, b.account_name, b.account_type,e.balance
                 FROM expenses e
                 JOIN bank_accounts b ON e.account_id = b.id
                 WHERE e.user_id=? ORDER BY e.created_at DESC""", (session["user_id"],))
    all_expenses = c.fetchall()

    c.execute("SELECT account_name, account_type, balance, id FROM bank_accounts WHERE user_id=?", (session["user_id"],))
    accounts = c.fetchall()

    total_debit = sum(acc[2] for acc in accounts if acc[1] == "Debit")
    total_credit = sum(acc[2] for acc in accounts if acc[1] == "Credit")
    total_available = total_debit - total_credit

    conn.close()
    return render_template("dashboard.html", data=data, all_expenses=all_expenses, accounts=accounts, total_available=total_available, total_credit=total_credit, total_debit=total_debit)

@app.route("/accounts", methods=["GET", "POST"])
def accounts_page():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()

    if request.method == "POST":
        account_name = request.form["account_name"]
        account_type = request.form["account_type"]
        balance = float(request.form["balance"])
        c.execute("INSERT INTO bank_accounts (user_id, account_name, account_type, balance) VALUES (?, ?, ?, ?)",
                  (session["user_id"], account_name, account_type, balance))
        conn.commit()
        flash("Account added successfully!", "success")
        conn.close()
        return redirect(url_for("accounts_page"))

    c.execute("SELECT id, account_name, account_type, balance FROM bank_accounts WHERE user_id=?", (session["user_id"],))
    accounts = c.fetchall()
    conn.close()
    return render_template("accounts.html", accounts=accounts)

@app.route("/edit_account/<int:account_id>", methods=["GET", "POST"])
def edit_account(account_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()

    if request.method == "POST":
        account_name = request.form["account_name"]
        account_type = request.form["account_type"]
        balance = float(request.form["balance"])
        c.execute("""UPDATE bank_accounts 
                     SET account_name=?, account_type=?, balance=? 
                     WHERE id=? AND user_id=?""",
                  (account_name, account_type, balance, account_id, session["user_id"]))
        conn.commit()
        conn.close()
        flash("Account updated successfully!", "success")
        return redirect(url_for("accounts_page"))

    c.execute("SELECT id, account_name, account_type, balance FROM bank_accounts WHERE id=? AND user_id=?",
              (account_id, session["user_id"]))
    account = c.fetchone()
    conn.close()
    return render_template("edit_account.html", account=account)

@app.route("/delete_account/<int:account_id>")
def delete_account(account_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    c.execute("DELETE FROM bank_accounts WHERE id=? AND user_id=?", (account_id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Account deleted successfully!", "success")
    return redirect(url_for("accounts_page"))

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for("login"))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
    #app.run(debug=True)
