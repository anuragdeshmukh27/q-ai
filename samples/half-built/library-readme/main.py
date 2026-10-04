import os
import sqlite3

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Library")


def conn():
    c = sqlite3.connect(os.environ.get("LIB_DB", "library.db"))
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, author TEXT NOT NULL, borrowed_by TEXT, borrowed_at TEXT)")
    return c


class BookIn(BaseModel):
    title: str
    author: str


@app.post("/books", status_code=201)
def add_book(book: BookIn):
    c = conn()
    cur = c.execute("INSERT INTO books (title, author) VALUES (?, ?)", (book.title, book.author))
    c.commit()
    row = c.execute("SELECT * FROM books WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.get("/books")
def list_books(title: str = ""):
    c = conn()
    rows = c.execute("SELECT * FROM books WHERE title LIKE ? ORDER BY id", (f"%{title}%",)).fetchall()
    return {"items": [dict(r) for r in rows]}
