"""Contract tests for related resources and actions, generated from the resource model (no model writes these).

They sit in the generated API test file of each resource, so a router task only sees the tests of its own router:
- parent: counters are never taken from the client, every action changes exactly its field and returns the updated item, sort=top / new order the list;
- child: nested create and list, an unknown parent is a 404, every parent has its own list, deleting the parent deletes its children.
"""
from __future__ import annotations

from .relations import child_of, parent_of, payload
from .schemas import ArchitectOutput, ResourceInfo


def _create_url(ri: ResourceInfo, pr: ResourceInfo | None) -> str:
    """Source of a Python expression for the URL that creates (and lists) this resource's rows."""
    return f"f\"/api/{pr.name}/{{parent['id']}}/{ri.name}\"" if pr else f"'/api/{ri.name}'"


def _make(ri: ResourceInfo, pr: ResourceInfo | None) -> list[str]:
    body = f"{{**{payload(ri)!r}, **over}}"
    if pr is None:
        return [f"def make_{ri.singular}(**over):", f"    r = client.post('/api/{ri.name}', json={body})", "    assert r.status_code == 201, r.text", "    return r.json()", "", ""]
    return [f"def make_{ri.singular}(parent_id, **over):", f"    r = client.post(f'/api/{pr.name}/{{parent_id}}/{ri.name}', json={body})",
            "    assert r.status_code == 201, r.text", "    return r.json()", "", ""]


def _setup(ri: ResourceInfo, pr: ResourceInfo | None) -> list[str]:
    return [f"    parent = make_{pr.singular}()"] if pr else []


def _new(ri: ResourceInfo, pr: ResourceInfo | None, over: str = "") -> str:
    return f"make_{ri.singular}(parent['id']{', ' + over if over else ''})" if pr else f"make_{ri.singular}({over})"


def _action_tests(ri: ResourceInfo, pr: ResourceInfo | None) -> list[str]:
    out: list[str] = []
    for a in ri.actions:
        name = f"test_{ri.name}_{a.name}"
        out += [f"def {name}_changes_only_its_field():", *_setup(ri, pr), f"    item = {_new(ri, pr)}", f"    before = item[{a.field!r}]",
                f"    r = client.post(f\"/api/{ri.name}/{{item['id']}}/{a.name}\")", "    assert r.status_code == 200, r.text",
                f"    assert r.json()['id'] == item['id'], 'the action must return the updated item'"]
        if a.kind == "increment":
            out += [f"    assert r.json()[{a.field!r}] == before + 1, 'one {a.name} must add exactly 1 to {a.field}'",
                    f"    r = client.post(f\"/api/{ri.name}/{{item['id']}}/{a.name}\")", f"    assert r.json()[{a.field!r}] == before + 2"]
            others = [c for c in ri.counters if c != a.field]
            out += [f"    assert r.json()[{c!r}] == item[{c!r}], '{a.name} must not change {c}'" for c in others]
            want = f"before + 2"
        else:
            out += [f"    assert r.json()[{a.field!r}] == (not before), '{a.name} must flip {a.field}'",
                    f"    r = client.post(f\"/api/{ri.name}/{{item['id']}}/{a.name}\")", f"    assert r.json()[{a.field!r}] == before"]
            want = "before"
        out += [f"    listed = client.get({_create_url(ri, pr)}).json()['items']",
                f"    assert [i for i in listed if i['id'] == item['id']][0][{a.field!r}] == {want}, 'the list must show the new value'", "", ""]
    return out


def _sort_tests(ri: ResourceInfo, pr: ResourceInfo | None) -> list[str]:
    act = next((a for a in ri.actions if a.kind == "increment"), None)
    if not ri.sorts or act is None:
        return []
    url = _create_url(ri, pr)
    return [f"def test_{ri.name}_sort_top_and_new():", *_setup(ri, pr), f"    first = {_new(ri, pr)}", f"    second = {_new(ri, pr)}",
            f"    client.post(f\"/api/{ri.name}/{{first['id']}}/{act.name}\")",
            f"    top = [i['id'] for i in client.get({url}, params={{'sort': 'top'}}).json()['items']]",
            "    assert top == [first['id'], second['id']], 'sort=top lists the highest score first'",
            f"    new = [i['id'] for i in client.get({url}, params={{'sort': 'new'}}).json()['items']]",
            "    assert new == [second['id'], first['id']], 'sort=new lists the newest first'",
            f"    default = [i['id'] for i in client.get({url}).json()['items']]",
            "    assert default == new, 'without sort the list is newest first'",
            f"    assert client.get({url}, params={{'sort': 'bogus'}}).status_code == 422", "", ""]


def _owner_tests(ri: ResourceInfo, pr: ResourceInfo | None) -> list[str]:
    owned = [*ri.counters, *ri.flags]
    if not owned:
        return []
    body = f"{{**{payload(ri)!r}, " + ", ".join(f"{c!r}: 99" if c in ri.counters else f"{c!r}: True" for c in owned) + "}"
    return [f"def test_{ri.name}_counters_never_come_from_the_client():", *_setup(ri, pr),
            f"    r = client.post({_create_url(ri, pr)}, json={body})", "    assert r.status_code == 201, r.text",
            *[f"    assert r.json()[{c!r}] == {0 if c in ri.counters else False!r}, '{c} is owned by the server: ignore it in the request'" for c in owned],
            f"    item = r.json()", f"    r = client.put(f\"/api/{ri.name}/{{item['id']}}\", json={body})", "    assert r.status_code == 200, r.text",
            *[f"    assert r.json()[{c!r}] == {0 if c in ri.counters else False!r}, 'an edit must not change {c}'" for c in owned], "", ""]


def _child_tests(design: ArchitectOutput, ri: ResourceInfo, pr: ResourceInfo) -> list[str]:
    url = _create_url(ri, pr)
    nf = f"{pr.singular.capitalize()} not found"
    bad = f"f\"/api/{pr.name}/99999/{ri.name}\""
    out = [f"def test_{ri.name}_are_created_and_listed_under_their_{pr.singular}():", *_setup(ri, pr), f"    item = {_new(ri, pr)}",
           f"    assert item[{ri.fk!r}] == parent['id']", f"    items = client.get({url}).json()['items']",
           "    assert [i['id'] for i in items] == [item['id']]", "", "",
           f"def test_{ri.name}_of_an_unknown_{pr.singular}_are_404():",
           f"    r = client.get({bad})", f"    assert r.status_code == 404 and r.json() == {{'detail': {nf!r}}}, r.text",
           f"    r = client.post({bad}, json={payload(ri)!r})", f"    assert r.status_code == 404 and r.json() == {{'detail': {nf!r}}}, r.text", "", "",
           f"def test_{ri.name}_belong_to_one_{pr.singular}_only():",
           f"    a = make_{pr.singular}()", f"    b = make_{pr.singular}()", f"    item = make_{ri.singular}(a['id'])",
           f"    assert client.get(f\"/api/{pr.name}/{{b['id']}}/{ri.name}\").json()['items'] == []", "", "",
           f"def test_{ri.name}_parent_id_must_be_an_integer():",
           f"    assert client.get('/api/{pr.name}/abc/{ri.name}').status_code == 422", "", "",
           f"def test_{ri.name}_body_is_validated():", *_setup(ri, pr)]
    for f in ri.fields:
        bad_body = {k: v for k, v in payload(ri).items() if k != f.name}
        out.append(f"    assert client.post({url}, json={bad_body!r}).status_code == 422")
    out += ["", "",
            f"def test_deleting_a_{pr.singular}_deletes_its_{ri.name}():", *_setup(ri, pr), f"    item = {_new(ri, pr)}",
            f"    r = client.delete(f\"/api/{pr.name}/{{parent['id']}}\")", "    assert r.status_code == 200, r.text",
            f"    r = client.put(f\"/api/{ri.name}/{{item['id']}}\", json={payload(ri)!r})",
            f"    assert r.status_code == 404, 'deleting the {pr.singular} must delete its {ri.name} too'", "", ""]
    return out


def relation_tests(design: ArchitectOutput, ri: ResourceInfo) -> list[str]:
    """The test functions (and the helpers they need) for one resource of a relational design."""
    pr = parent_of(design, ri)
    out: list[str] = []
    if pr is not None:
        out += _make(pr, None)
    out += _make(ri, pr)
    if pr is not None:
        out += _child_tests(design, ri, pr)
    out += _owner_tests(ri, pr) + _action_tests(ri, pr) + _sort_tests(ri, pr)
    return out


# --- database layer tests -----------------------------------------------------------------------

def db_test_source(design: ArchitectOutput, ri: ResourceInfo) -> str:
    """tests/db/test_<table>.py: the data access functions of one table, written from the resource model (the database engineer makes them pass)."""
    pr, ch = parent_of(design, ri), child_of(design, ri)
    p, s = ri.name, ri.singular
    pay = payload(ri)
    edit = dict(pay)
    text = next((f.name for f in ri.fields if f.type == "string" and not f.options), None)
    if text:
        edit[text] = pay[text] + " v2"
    pid = "1, " if pr else ""  # the parent id every call of a child table starts with

    def ids(call: str) -> str:
        return f"[r['id'] for r in {call}]"

    def listing(sort: str = "") -> str:
        args = [*(["1"] if pr else []), *([f"sort={sort!r}"] if sort else [])]
        return f"m.list_{p}({', '.join(args)})"

    out = ['"""Database tests generated from the resource model. Do not edit; fix the data access functions instead."""',
           f"from database import {p} as m", "from database.connection import connect", "", "",
           f"def make({'pid=1, ' if pr else ''}**over):",
           f"    return m.add_{s}({f'{ri.fk}=pid, ' if pr else ''}**{{**{pay!r}, **over}})", "", "",
           "def test_add_returns_the_row_and_get_finds_it():", "    row = make()", "    assert isinstance(row, dict) and row['id'], 'add must return the new row as a dict'"]
    out += [f"    assert row[{k!r}] == {v!r}, 'the stored value must come back unchanged'" for k, v in pay.items()]
    out += [f"    assert row[{c!r}] == 0, '{c} starts at 0'" for c in ri.counters]
    out += [f"    assert row[{ri.fk!r}] == 1" if pr else "    assert row['created_at']",
            f"    assert m.get_{s}(row['id']) == row", f"    assert m.get_{s}(99999) is None", "", "",
            "def test_list_is_newest_first():", "    a, b = make(), make()", *(["    make(2)  # a row of another parent must not show up"] if pr else []),
            f"    assert {ids(listing())} == [b['id'], a['id']], 'newest first (ORDER BY id DESC)'", "", "",
            "def test_update_changes_the_user_fields_and_returns_the_row():", "    row = make()",
            f"    new = m.update_{s}(row['id'], **{edit!r})", f"    assert new is not None and all(new[k] == v for k, v in {edit!r}.items())",
            f"    assert m.update_{s}(99999, **{edit!r}) is None", "", "",
            "def test_delete_reports_whether_the_row_existed():", "    row = make()", f"    assert m.delete_{s}(row['id']) is True",
            f"    assert m.get_{s}(row['id']) is None", f"    assert m.delete_{s}(row['id']) is False", "", ""]
    for a in ri.actions:
        out += [f"def test_{a.name}_{s}():", "    row = make()", f"    r = m.{a.name}_{s}(row['id'])"]
        if a.kind == "increment":
            out += [f"    assert r[{a.field!r}] == row[{a.field!r}] + 1", f"    assert m.{a.name}_{s}(row['id'])[{a.field!r}] == row[{a.field!r}] + 2"]
        else:
            out += [f"    assert r[{a.field!r}] == 1 - row[{a.field!r}]", f"    assert m.{a.name}_{s}(row['id'])[{a.field!r}] == row[{a.field!r}]"]
        out += [f"    assert m.{a.name}_{s}(99999) is None", "", ""]
    act = next((a for a in ri.actions if a.kind == "increment"), None)
    if ri.sorts and act:
        out += ["def test_sort_top_puts_the_highest_score_first():", "    a, b = make(), make()", f"    m.{act.name}_{s}(a['id'])",
                f"    assert {ids(listing('top'))} == [a['id'], b['id']]", f"    assert {ids(listing('new'))} == [b['id'], a['id']]", "", ""]
    if ch:
        cols = [ch.fk, *payload(ch)]
        cvals = ", ".join(repr(v) for v in payload(ch).values())
        out += [f"def test_deleting_a_{s}_deletes_its_{ch.name}():", "    row = make()", "    with connect(m.SCHEMA) as conn:",
                f"        conn.execute('INSERT INTO {ch.name} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})', (row['id'], {cvals}))",
                f"    assert m.delete_{s}(row['id']) is True", "    with connect(m.SCHEMA) as conn:",
                f"        left = conn.execute('SELECT COUNT(*) FROM {ch.name} WHERE {ch.fk} = ?', (row['id'],)).fetchone()[0]",
                f"    assert left == 0, 'deleting a {s} must delete its {ch.name} (DELETE FROM {ch.name} WHERE {ch.fk} = ?)'", "", ""]
    return "\n".join(out).rstrip() + "\n"
