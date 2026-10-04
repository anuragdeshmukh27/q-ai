"""A tiny notes app (Flask, sqlite3). Written by hand, in a hurry."""
import os
import sqlite3

from flask import Flask, abort, g, jsonify, render_template, request

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(os.environ.get("NOTES_DB", "notes.db"))
        g.db.row_factory = sqlite3.Row
        g.db.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT DEFAULT '', pinned INTEGER DEFAULT 0)")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.commit()
        db.close()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/notes", methods=["GET"])
def list_notes():
    rows = get_db().execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/notes", methods=["POST"])
def add_note():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    body = data.get("body", "")
    cur = get_db().execute("INSERT INTO notes (title, body) VALUES (?, ?)", (title, body))
    return jsonify({"id": cur.lastrowid, "title": title, "body": body, "pinned": 0}), 201


@app.route("/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    # FIXME: this answers 204 but nothing is deleted, and an unknown id should be a 404
    return "", 204


@app.route("/notes/<int:note_id>/pin", methods=["POST"])
def pin_note(note_id):
    abort(501)


@app.route("/search")
def search():
    q = request.args.get("q", "")
    # TODO: notes whose title or body contains q (any case)
    return jsonify([])


if __name__ == "__main__":
    app.run(debug=True)
