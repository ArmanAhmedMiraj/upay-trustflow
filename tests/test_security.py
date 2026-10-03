import security


def test_pin_is_hashed_and_verifies(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)
    stored = security.hash_pin("12345")
    assert "12345" not in stored and stored.startswith("pbkdf2_sha256$")
    assert security.verify_pin("12345", stored)
    assert not security.verify_pin("12346", stored)


def test_same_pin_gets_a_different_hash_each_time(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)
    assert security.hash_pin("12345") != security.hash_pin("12345")


def test_malformed_stored_hashes_never_verify():
    for bad in ["", "x", "a$b$c$d", "pbkdf2_sha256$notanumber$00$00", "md5$1$00$00"]:
        assert not security.verify_pin("12345", bad)


def test_tokens_are_random_and_only_their_hash_is_stored():
    a, b = security.new_token(), security.new_token()
    assert a != b and len(a) >= 40
    assert security.hash_token(a) != a and security.hash_token(a) == security.hash_token(a)
