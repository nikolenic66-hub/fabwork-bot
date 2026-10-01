from storage.db import Database


def test_request_status_lifecycle(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    rid = db.save_request(1, "Иван", "+79990000000", "{}", "25000", address="ул. Тестовая 1")
    row = db.get_request(rid)
    assert row[0] == rid
    assert row[2] == "Иван"
    assert row[6] == "new"
    db.set_status(rid, "quote")
    assert db.get_request(rid)[6] == "quote"


def test_history_contains_request_and_owner(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    rid = db.save_request(42, "Анна", "+79990000001", '{"cart": []}', "31000", address="ул. Оконная 2")
    rows = db.history(42, limit=8)
    assert rows[0][0] == rid
    assert rows[0][1] == "31000"
    assert rows[0][2] == "new"
    assert db.get_request(rid)[1] == 42
    assert db.get_request(rid)[7] == "ул. Оконная 2"
