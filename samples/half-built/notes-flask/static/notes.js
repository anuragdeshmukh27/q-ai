const list = document.getElementById("notes");

function draw(notes) {
  list.textContent = "";
  for (const n of notes) {
    const li = document.createElement("li");
    li.textContent = n.title + (n.body ? " - " + n.body : "");
    if (n.pinned) li.className = "pinned";
    const pin = document.createElement("button");
    pin.textContent = "Pin";
    pin.onclick = async () => { await fetch("/notes/" + n.id + "/pin", { method: "POST" }); load(); };
    const del = document.createElement("button");
    del.textContent = "Delete";
    del.onclick = async () => { await fetch("/notes/" + n.id, { method: "DELETE" }); load(); };
    li.append(" ", pin, del);
    list.appendChild(li);
  }
}

async function load() {
  const q = document.getElementById("q").value;
  const res = await fetch(q ? "/search?q=" + encodeURIComponent(q) : "/notes");
  draw(await res.json());
}

document.getElementById("add").onsubmit = async (ev) => {
  ev.preventDefault();
  await fetch("/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: document.getElementById("title").value, body: document.getElementById("body").value }) });
  load();
};
document.getElementById("q").oninput = load;
load();
