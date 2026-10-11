"""Hidden acceptance for the notes-flask fixture (on top of the project's own tests, which are the real specification)."""
from conftest import *  # noqa: F401,F403  (the client fixture)


def add(client, title, body=""):
    return client.post("/notes", json={"title": title, "body": body}).get_json()


def test_a_deleted_note_is_gone_from_the_list_and_from_search(client):
    note = add(client, "Alpha", "unique-word")
    assert client.delete(f"/notes/{note['id']}").status_code == 204
    assert client.get("/search?q=unique-word").get_json() == []
    assert client.get("/notes").get_json() == []


def test_pinning_twice_keeps_it_pinned_and_unknown_notes_are_404(client):
    note = add(client, "Alpha")
    add(client, "Beta")
    assert client.post(f"/notes/{note['id']}/pin").get_json()["pinned"] == 1
    assert client.post(f"/notes/{note['id']}/pin").get_json()["pinned"] == 1
    assert client.post("/notes/999/pin").status_code == 404
    assert client.get("/notes").get_json()[0]["title"] == "Alpha"
