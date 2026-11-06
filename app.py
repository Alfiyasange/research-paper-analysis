
import os
from flask import Flask, request, jsonify, render_template, session, redirect
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import core
import database
import auth
import uuid

load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY environment variable is required")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# Initialize SQLite database

database.init_app(app)
database.init_db(app)
app.register_blueprint(auth.auth)
def get_sqlite_paper_id(neo4j_id, user_id):
    db = database.get_db()

    row = db.execute(
        """
        SELECT id
        FROM papers
        WHERE neo4j_id = ? AND user_id = ?
        """,
        (neo4j_id, user_id)
    ).fetchone()

    return row["id"] if row else None

# Dashboard
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")

    return render_template("index.html")

# Login page
@app.route("/login")
def login_page():
    return render_template("login.html")


# Registration page
@app.route("/register")
def register_page():
    return render_template("register.html")


# Profile page
@app.route("/profile")
def profile_page():
    if "user_id" not in session:
        return redirect("/login")

    return render_template("profile.html")


# Get papers
@app.get("/api/papers")
def papers():
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    return jsonify(
        core.papers(session["user_id"])
    )
# Upload papers
@app.post("/api/upload")
def upload():
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    out = []
    user_id = session["user_id"]

    for f in request.files.getlist("files"):
        if not f.filename:
            continue

        filename = secure_filename(f.filename)

        if not filename.lower().endswith(".pdf"):
            continue

        user_folder = os.path.join("uploads", str(user_id))
        os.makedirs(user_folder, exist_ok=True)

        unique_name = str(uuid.uuid4()) + "_" + filename
        path = os.path.join(user_folder, unique_name)

        f.save(path)

        result = core.ingest(path, filename, user_id)

        db = database.get_db()

        db.execute(
            """
            INSERT INTO papers
            (user_id, title, filename, file_path, neo4j_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                result["title"],
                filename,
                path,
                result["id"]
            )
        )

        db.commit()
        out.append(result)

    return jsonify(out)
# Ask questions
@app.post("/api/ask")
def ask():
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    d = request.json
    user_id = session["user_id"]

    question = d["question"]
    paper_ids = d.get("paper_ids", [])

    result = core.answer(
        question,
        user_id,
        d.get("mode", "qa"),
        paper_ids
    )

    # Save the chat in SQLite
    paper_id = None

    if len(paper_ids) == 1:
        paper_id = get_sqlite_paper_id(
            paper_ids[0],
            user_id
        )

    db = database.get_db()

    db.execute(
        """
        INSERT INTO chat_history
        (user_id, paper_id, question, answer)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            paper_id,
            question,
            result["answer"]
        )
    )

    db.commit()

    return jsonify(result)
# Summarize paper
@app.get("/api/summarize/<pid>")
def summarize(pid):
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    user_id = session["user_id"]

    # Generate summary
    result = core.summarize(pid, user_id)

    # Find the corresponding SQLite paper ID
    paper_id = get_sqlite_paper_id(pid, user_id)

    if paper_id is None:
        return jsonify({"error": "Paper not found"}), 404

    # Save summary history
    db = database.get_db()

    db.execute(
        """
        INSERT INTO summary_history
        (user_id, paper_id, summary)
        VALUES (?, ?, ?)
        """,
        (user_id, paper_id, result)
    )

    db.commit()

    return jsonify({"summary": result})
    # Delete a research paper
@app.delete("/api/papers/<paper_id>")
def delete_paper(paper_id):
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    user_id = session["user_id"]
    db = database.get_db()

    # Check that this paper belongs to the logged-in user.
    paper = db.execute(
        """
        SELECT id, file_path
        FROM papers
        WHERE neo4j_id = ? AND user_id = ?
        """,
        (paper_id, user_id)
    ).fetchone()

    if paper is None:
        return jsonify({"error": "Paper not found"}), 404

    # Delete from Neo4j.
    core.delete_paper(paper_id, user_id)

    # Delete the uploaded PDF from disk.
    if paper["file_path"] and os.path.exists(paper["file_path"]):
        os.remove(paper["file_path"])

    # Delete from SQLite.
    db.execute(
        "DELETE FROM papers WHERE id = ? AND user_id = ?",
        (paper["id"], user_id)
    )
    db.commit()

    return jsonify({"message": "Paper deleted successfully"})
# Compare papers
@app.post("/api/compare")
def compare():
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    d = request.json
    user_id = session["user_id"]

    paper_a = d["a"]
    paper_b = d["b"]
    aspect = d.get("aspect", "main methods and findings")

    # Generate comparison
    result = core.compare(
        paper_a,
        paper_b,
        user_id,
        aspect
    )

    # Convert Neo4j IDs to SQLite IDs
    sqlite_a = get_sqlite_paper_id(paper_a, user_id)
    sqlite_b = get_sqlite_paper_id(paper_b, user_id)

    if sqlite_a is None or sqlite_b is None:
        return jsonify({"error": "One or both papers were not found"}), 404

    # Save comparison history
    db = database.get_db()

    db.execute(
        """
        INSERT INTO comparison_history
        (user_id, paper_a_id, paper_b_id, aspect, result)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            sqlite_a,
            sqlite_b,
            aspect,
            result["comparison"]
        )
    )

    db.commit()

    return jsonify(result)
@app.get("/api/history")
def history():
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    user_id = session["user_id"]
    db = database.get_db()

    chats = db.execute(
        """
        SELECT
            'chat' AS type,
            question AS title,
            answer AS content,
            created_at
        FROM chat_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    ).fetchall()

    summaries = db.execute(
        """
        SELECT
            'summary' AS type,
            p.title AS title,
            s.summary AS content,
            s.created_at
        FROM summary_history s
        LEFT JOIN papers p ON s.paper_id = p.id
        WHERE s.user_id = ?
        ORDER BY s.created_at DESC
        """,
        (user_id,)
    ).fetchall()

    comparisons = db.execute(
        """
        SELECT
            'comparison' AS type,
            p1.title || ' vs ' || p2.title AS title,
            c.result AS content,
            c.created_at
        FROM comparison_history c
        LEFT JOIN papers p1 ON c.paper_a_id = p1.id
        LEFT JOIN papers p2 ON c.paper_b_id = p2.id
        WHERE c.user_id = ?
        ORDER BY c.created_at DESC
        """,
        (user_id,)
    ).fetchall()

    all_history = [
        dict(item)
        for item in chats + summaries + comparisons
    ]

    all_history.sort(
        key=lambda item: item["created_at"] or "",
        reverse=True
    )

    return jsonify(all_history)
# Research graph
# Research graph
@app.get("/api/graph")
def graph():
    if "user_id" not in session:
        return jsonify({"error": "Please log in"}), 401

    return jsonify(core.graph(session["user_id"]))


if __name__ == "__main__":
    app.run(debug=True, port=5000)