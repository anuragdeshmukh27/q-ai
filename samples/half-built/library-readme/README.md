# Library

A small library app (FastAPI + sqlite). Run: `python -m uvicorn main:app`. Tests: `python -m pytest`.

## Planned features

- [x] Add a book: `POST /books` with `title` and `author`.
- [x] List the books: `GET /books`, with an optional `?title=` filter.
- [ ] Borrow a book: `POST /books/{id}/borrow` with `member` (the name of the person). It sets `borrowed_by` and `borrowed_at` (an ISO timestamp) and returns the book. A book that is already borrowed answers 409 with the detail "Book is already borrowed"; an unknown id is a 404.
- [ ] Return a book: `POST /books/{id}/return` clears `borrowed_by` and `borrowed_at` and returns the book. A book that is not borrowed answers 409 with the detail "Book is not borrowed".
- [ ] Overdue books: `GET /books/overdue` returns `{"items": [...]}` with the books that were borrowed more than 14 days ago.
