import json

import pytest

from muse_replay.annotations import AnnotationStore

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


def test_add_label_persist_and_reload(tmp_path):
    st = AnnotationStore(tmp_path / "ann.jsonl")
    r = st.add("Rocket Rally", "callout", "  Rotate back,  goal is empty ", observation="ball in your half", mode="live", frame_jpeg=JPEG)
    assert r.text == "Rotate back, goal is empty" and (tmp_path / "frames" / r.frame).is_file()
    st.label(r.id, "down", "we had a defender back")
    again = AnnotationStore(tmp_path / "ann.jsonl")
    g = again.get(r.id)
    assert g.label == "down" and g.correction == "we had a defender back" and g.frame == r.frame
    assert again.stats() == {"records": 1, "labeled": 1, "up": 0, "down": 1, "corrections": 1, "frames": 1}


def test_validation(tmp_path):
    st = AnnotationStore(tmp_path / "a.jsonl")
    with pytest.raises(ValueError):
        st.add("g", "thought", "x")
    with pytest.raises(ValueError):
        st.add("g", "reply", "   ")
    r = st.add("g", "reply", "ok")
    with pytest.raises(ValueError):
        st.label(r.id, "meh")
    with pytest.raises(KeyError):
        st.label("nope", "up")
    assert st.add("g", "reply", "no frame", frame_jpeg=b"not jpeg").frame == ""


def test_corrupt_lines_are_skipped(tmp_path):
    p = tmp_path / "a.jsonl"
    st = AnnotationStore(p); st.add("g", "reply", "one")
    with open(p, "a") as f:
        f.write("{broken\n")
    st2 = AnnotationStore(p); st2.add("g", "reply", "two")
    assert st2.stats()["records"] == 2


def test_learned_prompt_uses_ratings_only(tmp_path):
    st = AnnotationStore(tmp_path / "a.jsonl")
    assert st.learned_prompt("g") == ""
    a = st.add("g", "callout", "Push now, they are reloading", observation="two enemies reloading")
    b = st.add("g", "callout", "Go left", observation="x")
    st.add("g", "callout", "unrated", observation="y")
    st.add("other", "callout", "other game", observation="y"); st.label(st.recent()[-1].id, "up")
    st.label(a.id, "up"); st.label(b.id, "down", "left was a dead end")
    p = st.learned_prompt("g")
    assert "LEARNED for g" in p and "Push now" in p and "two enemies reloading" in p
    assert 'Avoid: "Go left". Player said: left was a dead end' in p
    assert "unrated" not in p and "other game" not in p


def test_export_training(tmp_path):
    st = AnnotationStore(tmp_path / "a.jsonl")
    up = st.add("g", "reply", "Hold Space to boost.", player_text="how do I go faster?", playbook="Rocket Rally")
    st.label(up.id, "up")
    down = st.add("g", "callout", "Rush mid", observation="enemy mid")
    st.label(down.id, "down", "Hold, they have mid covered")
    st.add("g", "callout", "unlabeled one")
    st.add("g", "observation", "just an observation"); st.label(st.recent()[-1].id, "up")
    out = tmp_path / "train.jsonl"
    assert st.export_training(out) == 2
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows[0]["messages"][1]["content"] == "Game: Rocket Rally\n\nhow do I go faster?"
    assert rows[0]["messages"][2]["content"] == "Hold Space to boost."
    assert rows[1]["messages"][2]["content"] == "Hold, they have mid covered" and "On screen: enemy mid" in rows[1]["messages"][1]["content"]
    assert st.export_training(out, include_unlabeled=True) == 3
    assert st.export_training(out, game="nope") == 0
