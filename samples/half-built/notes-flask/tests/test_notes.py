def add(client, title, body=""):
    r = client.post("/notes", json={"title": title, "body": body})
    assert r.status_code == 201
    return r.get_json()


def test_add_and_list(client):
    add(client, "Milk", "2 litres")
    notes = client.get("/notes").get_json()
    assert [n["title"] for n in notes] == ["Milk"]


def test_a_title_is_required(client):
    assert client.post("/notes", json={"title": "  "}).status_code == 400


def test_delete_removes_the_note(client):
    note = add(client, "Temporary")
    assert client.delete(f"/notes/{note['id']}").status_code == 204
    assert client.get("/notes").get_json() == []


def test_delete_of_an_unknown_note_is_a_404(client):
    assert client.delete("/notes/999").status_code == 404


def test_search_finds_by_title_or_body_in_any_case(client):
    add(client, "Groceries", "buy MILK")
    add(client, "Taxes", "file the return")
    assert [n["title"] for n in client.get("/search?q=milk").get_json()] == ["Groceries"]
    assert [n["title"] for n in client.get("/search?q=TAXES").get_json()] == ["Taxes"]
    assert client.get("/search?q=zzz").get_json() == []


def test_a_pinned_note_comes_first(client):
    first = add(client, "First")
    add(client, "Second")
    r = client.post(f"/notes/{first['id']}/pin")
    assert r.status_code == 200 and r.get_json()["pinned"] == 1
    assert [n["title"] for n in client.get("/notes").get_json()] == ["First", "Second"]
