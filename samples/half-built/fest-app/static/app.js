async function loadStats() {
  const res = await fetch("/api/stats");
  const s = await res.json();
  document.getElementById("stats").textContent = `${s.events} events, ${s.registrations} registrations`;
}

async function loadEvents() {
  const res = await fetch("/api/events");
  const data = await res.json();
  const list = document.getElementById("events");
  list.textContent = "";
  for (const e of data.items) {
    const li = document.createElement("li");
    li.textContent = `${e.name} at ${e.venue} (capacity ${e.capacity})`;
    const reg = document.createElement("button");
    reg.textContent = "Register me";
    reg.addEventListener("click", async () => {
      await fetch(`/api/events/${e.id}/registrations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_name: "Guest", email: "guest@example.com" }),
      });
      loadStats();
    });
    li.appendChild(reg);
    list.appendChild(li);
  }
}

async function loadSponsors() {
  const res = await fetch("/api/sponsors");
  const data = await res.json();
  const list = document.getElementById("sponsors");
  list.textContent = "";
  for (const s of data.items) {
    const li = document.createElement("li");
    li.textContent = `${s.company}: ${s.amount}`;
    list.appendChild(li);
  }
}

document.getElementById("event-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: document.getElementById("name").value, venue: document.getElementById("venue").value, capacity: 100 }),
  });
  loadEvents();
  loadStats();
});

loadEvents();
loadSponsors();
loadStats();
