"""Famous apps by name: a judge types "Build Instagram", and the small version of it that Q can really build is already written down here.

Why a table and not the model: the same short goal made the 7B Architect build a different app on every run (Instagram came back as posts only, Amazon as
orders and order items). The spec of a famous app is therefore hand-written, one per family of apps (posts with comments, products with reviews, ...), and
every employee still builds the whole app from it: the contract, the plan and the page follow from the spec by rules, the agents write every function.
Each spec names what the small version leaves out (`not_included`); the page and the spec say so ("Not in this version: ...").

A goal matches when it is short (up to 9 words, no field list after a colon) and names a platform. A detailed goal is always followed as written.
"""
from __future__ import annotations

import re

from .schemas import SpecOutput

MAX_WORDS = 9


def _f(name: str, type_: str = "string", *options: str) -> dict:
    return {"name": name, "type": type_, **({"options": list(options)} if options else {})}


CRUD = ["list", "create", "update", "delete"]


def _likes(field: str = "likes", name: str = "like") -> list[dict]:
    return [{"name": name, "field": field, "kind": "increment"}]


def _feed(title: str, summary: str, parent: str, pfields: list[dict], child: str, cfields: list[dict], features: list[str], left: list[str],
          actions: list[dict] | None = None, sorts: bool = True) -> dict:
    """A parent with a child list, like posts with comments: the shape that becomes the feed layout."""
    return {"title": title, "summary": summary, "features": features, "not_included": left, "resources": [
        {"name": parent, "fields": pfields, "operations": CRUD, "actions": actions or [], "sorts": ["new", "top"] if sorts and actions else []},
        {"name": child, "parent": parent, "fields": cfields, "operations": CRUD}]}


def _posts(title: str, summary: str, first: str, left: list[str], votes: bool = False, child: str = "comments", child_field: str = "content",
           body: bool = False) -> dict:
    fields = [_f(first), *([_f("content")] if body else []), _f("author"), *([_f("upvotes", "integer"), _f("downvotes", "integer")] if votes else [_f("likes", "integer")])]
    actions = [{"name": "upvote", "field": "upvotes", "kind": "increment"}, {"name": "downvote", "field": "downvotes", "kind": "increment"}] if votes else _likes()
    what = "Vote on" if votes else "Like"
    return _feed(title, summary, "posts", fields, child, [_f(child_field), _f("author")],
                 ["Form to write a post", f"List of posts with the {'score and vote buttons' if votes else 'like button and the count'}", "Sort by newest or top",
                  f"Open a post to read and add {child}", "Edit and Delete buttons"], left, actions)


def _reviews(title: str, summary: str, parent: str, pfields: list[dict], left: list[str], noun: str) -> dict:
    return _feed(title, summary, parent, pfields, "reviews", [_f("author"), _f("rating", "integer"), _f("comment")],
                 [f"Form to add a {noun}", f"List of {parent}", f"Open a {noun} to read its reviews and add one with a rating", "Average rating of the open " + noun,
                  "Edit and Delete buttons"], left)


PLATFORMS: list[tuple[str, str, dict]] = [
    ("instagram", r"insta(?:gram)?|facebook|fb|snapchat|pinterest", _posts(
        "Instagram", "Share posts with a caption, like them and talk about them in comments.", "caption",
        ["photo and video uploads", "followers and profiles", "stories and reels", "direct messages", "login and accounts"])),
    ("twitter", r"twitter|tweets?|x\.com", _posts(
        "Twitter", "Write short tweets, like them and reply to them.", "text",
        ["followers and profiles", "retweets and hashtags", "direct messages", "images and video", "login and accounts"], child="replies", child_field="text")),
    ("reddit", r"reddit|hacker ?news|digg", _posts(
        "Reddit", "Share posts, vote on them and discuss them in comments.", "title",
        ["login and accounts", "subreddits", "images and links", "awards"], votes=True, body=True)),
    ("qa", r"quora|stack ?overflow|stackexchange", _feed(
        "Q&A forum", "Ask questions, answer them and vote on both.", "questions", [_f("title"), _f("details"), _f("author"), _f("upvotes", "integer"), _f("downvotes", "integer")],
        "answers", [_f("content"), _f("author"), _f("upvotes", "integer")],
        ["Form to ask a question", "List of questions with the score and vote buttons", "Sort by newest or top", "Open a question to read and add answers", "Edit and Delete buttons"],
        ["login and accounts", "tags and search", "reputation points"],
        [{"name": "upvote", "field": "upvotes", "kind": "increment"}, {"name": "downvote", "field": "downvotes", "kind": "increment"}])),
    ("blog", r"medium|wordpress|substack|blogger|blog", _feed(
        "Blog", "Publish posts and let readers discuss them in comments.", "posts", [_f("title"), _f("content"), _f("author")], "comments", [_f("content"), _f("author")],
        ["Form to write a post", "List of posts", "Open a post to read it and add comments", "Edit and Delete buttons"],
        ["login and accounts", "images", "rich text formatting"], sorts=False)),
    ("youtube", r"youtube|vimeo|dailymotion|tiktok|reels", _feed(
        "YouTube", "Share video links with a description, like them and comment on them.", "videos",
        [_f("title"), _f("description"), _f("channel"), _f("link"), _f("likes", "integer")], "comments", [_f("content"), _f("author")],
        ["Form to add a video link", "List of videos with the like button and the count", "Sort by newest or top", "Open a video to read and add comments", "Edit and Delete buttons"],
        ["video upload and playback", "subscriptions and channels", "recommendations", "login and accounts"], _likes())),
    ("amazon", r"amazon|flipkart|ebay|etsy|myntra|meesho|olx|shopify|online (?:shop|store)", _feed(
        "Amazon", "Browse products with a price and read or write reviews with a rating.", "products",
        [_f("name"), _f("description"), _f("price", "number"), _f("category", "string", "Electronics", "Books", "Home", "Fashion", "Other")],
        "reviews", [_f("author"), _f("rating", "integer"), _f("comment")],
        ["Form to add a product with name, description, price and category", "List of products with a price and a category badge",
         "Open a product to read its reviews and add one with a rating", "Average rating of the open product", "Edit and Delete buttons"],
        ["cart and checkout", "payments", "product images", "orders and shipping", "login and accounts"], sorts=False)),
    ("zomato", r"zomato|swiggy|yelp|tripadvisor|dineout|restaurants?", _reviews(
        "Zomato", "Find restaurants by cuisine and read or write reviews with a rating.", "restaurants",
        [_f("name"), _f("cuisine", "string", "North Indian", "South Indian", "Chinese", "Italian", "Fast food", "Other"), _f("area")],
        ["online ordering and delivery", "maps and search near me", "photos", "login and accounts"], "restaurant")),
    ("movies", r"netflix|imdb|hotstar|prime video|letterboxd|rotten tomatoes|movies?", _reviews(
        "Movie reviews", "Keep a list of movies and review them with a rating.", "movies",
        [_f("title"), _f("genre", "string", "Action", "Comedy", "Drama", "Sci-fi", "Horror", "Other"), _f("year", "integer"), _f("description")],
        ["video streaming", "watchlists and profiles", "search and recommendations", "login and accounts"], "movie")),
    ("books", r"goodreads|kindle|bookshelf", _reviews(
        "Book reviews", "Keep a list of books and review them with a rating.", "books",
        [_f("title"), _f("author"), _f("genre", "string", "Fiction", "Non-fiction", "Science", "History", "Other")],
        ["reading challenges", "friends and shelves", "login and accounts"], "book")),
    ("jobs", r"linkedin|naukri|indeed|glassdoor|monster|job (?:board|portal)", _feed(
        "LinkedIn", "Post jobs and let people apply to them.", "jobs",
        [_f("title"), _f("company"), _f("location"), _f("job_type", "string", "Full-time", "Part-time", "Internship", "Remote"), _f("description")],
        "applications", [_f("name"), _f("email"), _f("message")],
        ["Form to post a job", "List of jobs with a job type badge", "Open a job to see its applications and apply", "Edit and Delete buttons"],
        ["profiles and connections", "feed and messaging", "resume upload", "login and accounts"], sorts=False)),
    ("chat", r"whatsapp|telegram|messenger|signal|slack|discord|chat app|messaging app", _feed(
        "WhatsApp", "Keep chats and the messages sent in each one.", "chats", [_f("name"), _f("about")], "messages", [_f("sender"), _f("text")],
        ["Form to start a chat", "List of chats", "Open a chat to read its messages and send one", "Edit and Delete buttons"],
        ["real-time delivery", "voice and video calls", "photos and files", "group admin tools", "login and phone numbers"], sorts=False)),
    ("playlists", r"spotify|gaana|wynk|youtube music|apple music|playlists?", _feed(
        "Spotify", "Make playlists and fill them with songs.", "playlists", [_f("name"), _f("description")], "songs", [_f("title"), _f("artist"), _f("length")],
        ["Form to make a playlist", "List of playlists", "Open a playlist to see its songs and add one", "Edit and Delete buttons"],
        ["audio playback", "search and recommendations", "login and accounts"], sorts=False)),
    ("stays", r"airbnb|booking\.com|oyo|makemytrip|trivago|hotels?", _feed(
        "Airbnb", "List places to stay and book them.", "listings",
        [_f("title"), _f("city"), _f("price_per_night", "number"), _f("kind", "string", "Apartment", "House", "Room", "Villa")],
        "bookings", [_f("guest"), _f("check_in"), _f("check_out")],
        ["Form to add a listing", "List of listings with a price and a type badge", "Open a listing to see its bookings and add one", "Edit and Delete buttons"],
        ["payments", "maps and photos", "availability calendar", "login and accounts"], sorts=False)),
    ("events", r"bookmyshow|eventbrite|ticketmaster|paytm insider", _feed(
        "BookMyShow", "List events and book seats for them.", "events", [_f("name"), _f("venue"), _f("date"), _f("price", "number")],
        "bookings", [_f("name"), _f("seats", "integer")],
        ["Form to add an event", "List of events with a price", "Open an event to see its bookings and book seats", "Edit and Delete buttons"],
        ["seat maps", "payments", "login and accounts"], sorts=False)),
    ("github", r"github|gitlab|bitbucket", _feed(
        "GitHub", "Keep repositories and the issues filed against each one.", "repositories",
        [_f("name"), _f("description"), _f("language", "string", "Python", "JavaScript", "Java", "Go", "Other")],
        "issues", [_f("title"), _f("status", "string", "Open", "In progress", "Closed"), _f("author")],
        ["Form to add a repository", "List of repositories with a language badge", "Open a repository to see its issues and file one", "Edit and Delete buttons"],
        ["git hosting and code browsing", "pull requests", "login and accounts"], sorts=False)),
    ("projects", r"trello|jira|asana|monday\.com|basecamp|clickup|project (?:management|tracker)", _feed(
        "Project tracker", "Keep projects and the tasks that belong to each one.", "projects", [_f("name"), _f("description")],
        "tasks", [_f("title"), _f("status", "string", "To do", "In progress", "Done")],
        ["Form to add a project", "List of projects", "Open a project to see its tasks and add one", "Status badge on every task", "Edit and Delete buttons"],
        ["login and teams", "boards and drag and drop", "due dates and reminders"], sorts=False)),
    ("hospital", r"hospital|clinic|patient|medical|healthcare", _feed(
        "Hospital management", "Keep patients and the appointments booked for each one.", "patients",
        [_f("name"), _f("age", "integer"), _f("gender", "string", "Female", "Male", "Other"), _f("phone"), _f("diagnosis")],
        "appointments", [_f("doctor"), _f("date"), _f("reason"), _f("status", "string", "Scheduled", "Completed", "Cancelled")],
        ["Form to register a patient", "List of patients with a gender badge", "Open a patient to see their appointments and book one", "Status badge on every appointment",
         "Edit and Delete buttons"],
        ["billing and insurance", "medical records and reports", "doctor schedules", "login and roles"], sorts=False)),
    ("library", r"library|librarian|book (?:lending|loans?)", _feed(
        "Library management", "Keep the books of a library and who borrowed each one.", "books",
        [_f("title"), _f("author"), _f("genre", "string", "Fiction", "Non-fiction", "Science", "History", "Other"), _f("copies", "integer")],
        "loans", [_f("member"), _f("borrowed_on"), _f("due_on"), _f("status", "string", "Borrowed", "Returned", "Overdue")],
        ["Form to add a book", "List of books with a genre badge", "Open a book to see its loans and lend it", "Status badge on every loan", "Edit and Delete buttons"],
        ["member accounts and cards", "fines and payments", "barcode scanning", "login and roles"], sorts=False)),
    ("uber", r"uber|ola|lyft|rapido|taxi|cab booking|ride (?:hailing|sharing|booking)", {
        "title": "Uber", "summary": "Request rides and follow each one from requested to completed.", "resources": [
            {"name": "rides", "operations": CRUD, "fields": [_f("rider"), _f("pickup"), _f("destination"), _f("ride_type", "string", "Economy", "Premium", "Shared"),
                                                               _f("status", "string", "Requested", "Accepted", "Completed", "Cancelled"), _f("fare", "number")]}],
        "features": ["Form to request a ride", "List of rides with a status badge and the fare", "Total fare and rides by status", "Edit and Delete buttons"],
        "not_included": ["live map and driver tracking", "driver matching", "payments", "ratings", "login and accounts"]}),
    ("wallet", r"paytm|phonepe|gpay|google pay|venmo|paypal|splitwise|wallet", {
        "title": "Wallet", "summary": "Record money coming in and going out and see the totals.", "resources": [
            {"name": "transactions", "operations": CRUD, "fields": [_f("description"), _f("amount", "number"), _f("kind", "string", "Credit", "Debit"), _f("date")]}],
        "features": ["Form to add a transaction", "List of transactions with a kind badge and the amount", "Total amount and transactions by kind", "Edit and Delete buttons"],
        "not_included": ["real bank or card connections", "payments between people", "login and accounts"]}),
]
_COMPILED = [(key, re.compile(rf"\b(?:{words})\b", re.I), spec) for key, words, spec in PLATFORMS]


def match_platform(goal: str) -> SpecOutput | None:
    """The hand-written spec when the goal is a short one naming a platform, else None (the model then writes the spec)."""
    text = goal.strip()
    if ":" in text or len(text.split()) > MAX_WORDS:
        return None
    for _key, rx, spec in _COMPILED:
        if rx.search(text):
            return SpecOutput.model_validate(spec)
    return None
