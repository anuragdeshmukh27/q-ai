"""A correct hand-written implementation of the generated reddit design: the generated tests must pass against it and fail against its mutants."""
from pathlib import Path

DB = '''"""reference"""
from database.connection import connect

SCHEMA = "{schema}"


def _one(conn, table, id_):
    row = conn.execute("SELECT * FROM " + table + " WHERE id = ?", (id_,)).fetchone()
    return dict(row) if row else None


def add_{s}({fk}{args}) -> dict:
    with connect(SCHEMA) as conn:
        cur = conn.execute("INSERT INTO {p} ({cols}) VALUES ({marks})", ({vals}))
        return _one(conn, "{p}", cur.lastrowid)


def get_{s}({s}_id: int):
    with connect(SCHEMA) as conn:
        return _one(conn, "{p}", {s}_id)


def list_{p}({fk}sort: str = "new") -> list[dict]:
    order = "{top} DESC, id DESC" if sort == "top" else "id DESC"
    with connect(SCHEMA) as conn:
        rows = conn.execute("SELECT * FROM {p} {where} ORDER BY " + order{wargs}).fetchall()
        return [dict(r) for r in rows]


def update_{s}({s}_id: int, {args}):
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE {p} SET {sets} WHERE id = ?", ({vals2}, {s}_id))
        return _one(conn, "{p}", {s}_id)


def delete_{s}({s}_id: int) -> bool:
    with connect(SCHEMA) as conn:
{cascade}        cur = conn.execute("DELETE FROM {p} WHERE id = ?", ({s}_id,))
        return cur.rowcount > 0


def upvote_{s}({s}_id: int):
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE {p} SET upvotes = upvotes + 1 WHERE id = ?", ({s}_id,))
        return _one(conn, "{p}", {s}_id)


def downvote_{s}({s}_id: int):
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE {p} SET downvotes = downvotes + 1 WHERE id = ?", ({s}_id,))
        return _one(conn, "{p}", {s}_id)
'''


def write(root: Path, schema: str, break_cascade=False, break_404=False, client_counters=False):
    (root / "database").mkdir(exist_ok=True)
    posts = DB.format(schema=schema, s="post", p="posts", fk="", args="title: str, content: str, author: str", cols="title, content, author",
                      marks="?, ?, ?", vals="title, content, author", where="", wargs="", top="upvotes - downvotes",
                      sets="title = ?, content = ?, author = ?", vals2="title, content, author",
                      cascade="" if break_cascade else '        conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))\n')
    comments = DB.format(schema=schema, s="comment", p="comments", fk="post_id: int, ", args="content: str, author: str", cols="post_id, content, author",
                         marks="?, ?, ?", vals="post_id, content, author", where="WHERE post_id = ?", wargs=", (post_id,)", top="upvotes - downvotes",
                         sets="content = ?, author = ?", vals2="content, author", cascade="")
    if client_counters:
        posts = posts.replace('"INSERT INTO posts (title, content, author) VALUES (?, ?, ?)", (title, content, author)',
                              '"INSERT INTO posts (title, content, author, upvotes) VALUES (?, ?, ?, 99)", (title, content, author)')
    (root / "database/posts.py").write_text(posts, encoding="utf-8")
    (root / "database/comments.py").write_text(comments, encoding="utf-8")
    (root / "backend/api").mkdir(parents=True, exist_ok=True)
    nf = "" if not break_404 else "#"
    (root / "backend/api/posts.py").write_text(f'''
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import posts as db

router = APIRouter()


class Body(BaseModel):
    title: str
    content: str
    author: str


@router.get("/api/posts")
def list_(sort: Literal["new", "top"] = "new"):
    return {{"items": db.list_posts(sort=sort)}}


@router.post("/api/posts", status_code=201)
def add(req: Body):
    return db.add_post(title=req.title, content=req.content, author=req.author)


@router.put("/api/posts/{{id}}")
def put(id: int, req: Body):
    row = db.update_post(post_id=id, title=req.title, content=req.content, author=req.author)
    if row is None: raise HTTPException(404, "Post not found")
    return row


@router.delete("/api/posts/{{id}}")
def delete(id: int):
    if not db.delete_post(post_id=id): raise HTTPException(404, "Post not found")
    return {{"deleted": True}}


@router.post("/api/posts/{{id}}/upvote")
def up(id: int):
    row = db.upvote_post(id)
    if row is None: raise HTTPException(404, "Post not found")
    return row


@router.post("/api/posts/{{id}}/downvote")
def down(id: int):
    row = db.downvote_post(id)
    if row is None: raise HTTPException(404, "Post not found")
    return row
''', encoding="utf-8")
    (root / "backend/api/comments.py").write_text(f'''
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import comments as db
from database import posts as posts_db

router = APIRouter()


class Body(BaseModel):
    content: str
    author: str


@router.get("/api/posts/{{post_id}}/comments")
def list_(post_id: int, sort: Literal["new", "top"] = "new"):
    {nf}if posts_db.get_post(post_id) is None: raise HTTPException(404, "Post not found")
    return {{"items": db.list_comments(post_id=post_id, sort=sort)}}


@router.post("/api/posts/{{post_id}}/comments", status_code=201)
def add(post_id: int, req: Body):
    {nf}if posts_db.get_post(post_id) is None: raise HTTPException(404, "Post not found")
    return db.add_comment(post_id=post_id, content=req.content, author=req.author)


@router.put("/api/comments/{{id}}")
def put(id: int, req: Body):
    row = db.update_comment(comment_id=id, content=req.content, author=req.author)
    if row is None: raise HTTPException(404, "Comment not found")
    return row


@router.delete("/api/comments/{{id}}")
def delete(id: int):
    if not db.delete_comment(comment_id=id): raise HTTPException(404, "Comment not found")
    return {{"deleted": True}}


@router.post("/api/comments/{{id}}/upvote")
def up(id: int):
    row = db.upvote_comment(id)
    if row is None: raise HTTPException(404, "Comment not found")
    return row


@router.post("/api/comments/{{id}}/downvote")
def down(id: int):
    row = db.downvote_comment(id)
    if row is None: raise HTTPException(404, "Comment not found")
    return row
''', encoding="utf-8")
