"""The goals the scripts build. CHIPS are the detailed example goals offered in the UI (frontend/src/examples.ts keeps the same list; only goals that built end to end are listed,
the habit tracker and quiz goals failed their one run and are not offered; the last four are the related-resource goals of P9a);
SHORT are the original one-line goals the generality check and the earlier comparisons used."""

CHIPS = [
    ("calculator with history", "Build a calculator with history: add, subtract, multiply and divide two numbers, show the result, keep a history list, clear the history"),
    ("todo app", "Build a todo app: title, description, priority Low/Medium/High, due date, mark as done, filter by status, edit and delete"),
    ("expense tracker", "Build an expense tracker: description, amount, category Food/Transport/Housing/Fun/Other, date, total spent, filter by category, edit and delete"),
    ("notes app", "Build a notes app: title, content, tag Work/Personal/Ideas, search by text, edit and delete"),
    ("contact book", "Build a contact book: name, phone, email, group Family/Friends/Work, search by name, edit and delete"),
    ("inventory list", "Build an inventory list: item name, quantity, location Warehouse/Shop/Home, status In stock/Low/Out of stock, edit and delete"),
]

SHORT = [
    "Build a calculator with history",
    "Build a todo app with priorities",
    "Build an expense tracker with categories and totals",
    "Build a notes app with search",
    "Build a habit tracker",
    "Build a quiz app",
    "Build a contact book",
    "Build an inventory list",
]

# Related resources (a parent and its children, votes, sort): the short goals a user would type, used for the P9a proof runs.
RELATED = [
    "Build a reddit replica",
    "Build a blog with comments",
    "Build a Q&A forum with answers and votes",
    "Build a project tracker where each project has tasks",
]

# Detailed versions of the same goals. All four built end to end (P9a), so they are appended to CHIPS below.
RELATED_DETAILED = [
    ("reddit replica", "Build a reddit-style forum: posts with title, content and author, comments on each post, upvote and downvote posts, sort by top or newest, edit and delete"),
    ("blog with comments", "Build a blog: posts with title, content and author, readers add comments to a post, edit and delete posts and comments"),
    ("Q&A forum", "Build a Q&A forum: questions with title, details and author, answers to each question, upvote questions and answers, sort by top or newest"),
    ("project tasks", "Build a project tracker: projects with name and description, tasks for each project with title and status To do/In progress/Done, edit and delete"),
]

CHIPS += RELATED_DETAILED

# "Try a famous app": the short names a judge types. Each maps to a hand-written small version (backend/app/platforms.py) and was built end to end by the
# judge test (scripts/judge.py, results in PROGRESS.md). Only the ones that built reliably are offered.
FAMOUS = [
    ("Instagram", "Build Instagram"),
    ("Twitter", "Build Twitter"),
    ("Amazon", "Build Amazon"),
    ("Zomato", "Build Zomato"),
    ("YouTube", "Build YouTube"),
    ("LinkedIn", "Build LinkedIn"),
    ("WhatsApp", "Build WhatsApp"),
    ("Uber", "Build Uber"),
    ("hospital system", "Build a hospital management system"),
    ("library system", "Build a library management system"),
]


# The flagship (four linked modules, exact text) and the clinic goal (a parent with three children): both are read by rules (backend/app/goalspec.py).
FLAGSHIP = 'Build a college tech fest manager: events have name, category Coding/Robotics/Gaming/Quiz/Workshop, venue, date, start time, capacity and entry fee in rupees. Each event has many registrations: student name, college, email, phone, team name and status Registered/Checked in/Cancelled; actions: check in and cancel. Each event has many volunteers: name, phone, role Coordinator/Helper/Tech support and shift Morning/Afternoon/Evening. Each event has many sponsors: company name, contact person, amount in rupees and status Pledged/Paid; action: mark paid. Show total registrations, total sponsorship received, registrations per event, filter registrations by status and events by category, search events by name, edit and delete everything.'
CLINIC = 'Build a clinic app: doctors have name, speciality General/Cardiology/Dermatology/Pediatrics/Orthopedics, phone, email, consultation fee in rupees and rating 1-5. Each doctor has many appointments: patient name, patient phone, date, time, reason and status Scheduled/Completed/Cancelled; actions: complete and cancel. Each doctor has many prescriptions: patient name, medicine and dosage. Each doctor has many reviews: author, rating 1-5 and comment.'

HACKATHON = ('Build a hackathon management platform: teams have name, college, city, track AI/Web/Health/Sustainability/Open, project title and stage Registered/Shortlisted/Finalist/Eliminated; actions: shortlist and eliminate. '
             'Each team has many members: name, email, phone and role Leader/Developer/Designer/Presenter. '
             'Each team has many mentor sessions: mentor name, topic, date, time and status Scheduled/Completed/Cancelled; actions: complete and cancel. '
             'Each team has many judge scores: judge name, innovation 1-10, technical depth 1-10, presentation 1-10, impact 1-10 and comments. '
             'Show total teams, members per team, average judge scores, filter teams by stage and track, search teams by name, edit and delete everything.')

HOSPITAL = ('Build a hospital OPD manager: doctors have name, department General Medicine/Cardiology/Dermatology/Pediatrics/Orthopedics/ENT, phone, email, consultation fee in rupees, room and availability Available/On leave. '
            'Each doctor has many appointments: patient name, patient phone, date, time, reason and status Booked/Completed/Cancelled; actions: complete and cancel. '
            'Each doctor has many prescriptions: patient name, medicine, dosage, days 1-90 and instructions. '
            'Each doctor has many lab tests: patient name, test name Blood test/X-ray/MRI/ECG/Urine test, cost in rupees and status Ordered/Collected/Reported; actions: collect and report. '
            'Show total doctors, appointments per doctor, lab revenue, filter doctors by department, filter appointments by status, search doctors by name, edit and delete everything.')

MIXED = ('Build a restaurant manager: restaurants have name, cuisine North Indian/South Indian/Chinese/Italian/Other, area, phone and average cost for two in rupees. '
         'Each restaurant has many menu items: name, category Starter/Main/Dessert/Drink, price in rupees and status Available/Sold out; actions: mark sold out and mark available. '
         'Each restaurant has many orders: customer name, table number, total in rupees and status Placed/Served/Paid; actions: serve and mark paid. '
         'Show total restaurants, orders per restaurant, filter menu items by category, search restaurants by name, edit and delete everything.')
