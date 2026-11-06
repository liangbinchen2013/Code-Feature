import json
import os
import subprocess
import sys

import pytest

from cf.document import build_document
from cf.similarity import (
    MatchSpan,
    Similarity,
    SimilarityError,
    Submission,
    compare_documents,
    find_duplicates,
    fingerprint,
    load_manifest,
    normalize,
    read_document,
)
from tests.util import read_sample, sample_path

BASE = read_sample("cpp_knr.cpp")


def renamed(text):
    return text.replace("values", "nums").replace("total", "acc").replace("Solver", "Kit")


def docs(*pairs):
    return [build_document(text, name) for name, text in pairs]


def compare(a, b, **kw):
    return compare_documents(build_document(a, "a.cpp"), build_document(b, "b.cpp"), **kw)


def test_identical_files_score_one_and_carry_evidence():
    sim = compare(BASE, BASE, min_tokens=40)
    assert sim.jaccard == 1.0 and sim.containment == 1.0
    assert sim.qualifies and sim.shared_ngrams > 3
    assert sim.evidence and sim.evidence[0].a_lines == sim.evidence[0].b_lines


def test_renaming_identifiers_does_not_change_the_score():
    sim = compare(BASE, renamed(BASE), min_tokens=40)
    assert sim.jaccard == 1.0, sim


def test_whitespace_and_comment_changes_do_not_change_the_score():
    touched = BASE.replace("    int total = 0;", "// a note\n    int   total   =   0;\n")
    sim = compare(BASE, touched, min_tokens=40)
    assert sim.jaccard > 0.9, sim.jaccard


def test_partial_copy_shows_up_in_containment_not_jaccard():
    keep = BASE[: BASE.index("    void report")]
    sim = compare(BASE, keep, min_tokens=20)
    assert sim.containment > sim.jaccard
    assert sim.containment_ba > 0.8, sim.containment_ba  # the truncated copy is contained in the original
    assert sim.qualifies


def test_unrelated_code_stays_low():
    sim = compare(BASE, read_sample("go_style.go"), min_tokens=20)
    assert sim.jaccard < 0.5 and sim.containment < 0.8
    assert not sim.qualifies


def test_boilerplate_heavy_corpus_does_not_get_flagged():
    boiler = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){\n"
    tails = ["    int n; cin >> n; cout << n;\n}\n", "    int m; cin >> m; cout << m;\n}\n",
             "    int k; cin >> k; cout << k;\n}\n"]
    subs = [Submission(path=f"s{i}", id=f"s{i}", user=f"u{i}", problem="P",
                       text=boiler + tails[i % 3]) for i in range(12)]
    filtered = find_duplicates(subs, min_tokens=20)
    assert filtered.pairs == []
    assert any(w.startswith("boilerplate-filtered") for w in filtered.warnings), filtered.warnings
    kept = find_duplicates(subs, min_tokens=20, keep_common=True)
    assert kept.pairs, "without the filter the template text does match"


def test_short_submission_is_warned_about_and_not_clustered():
    subs = [Submission(path="big", id="big", user="a", text=BASE),
            Submission(path="small", id="small", user="b", text="int main(){return 0;}\n")]
    report = find_duplicates(subs, min_tokens=40)
    assert any(w.startswith("too-short:small") for w in report.warnings), report.warnings
    assert report.clusters == []


def test_empty_and_comment_only_files_do_not_crash():
    subs = [Submission(path="e1", id="e1", user="a", text=""),
            Submission(path="e2", id="e2", user="b", text="// nothing\n/* here */\n"),
            Submission(path="e3", id="e3", user="c", text="int main(){ return 0; }\n")]
    report = find_duplicates(subs, min_tokens=1)
    assert all(not p.qualifies for p in report.pairs)


def test_problem_and_language_gating(tmp_path):
    a = tmp_path / "a.cpp"; a.write_text(BASE, encoding="utf-8")
    b = tmp_path / "b.cpp"; b.write_text(renamed(BASE), encoding="utf-8")
    p = tmp_path / "p.py"; p.write_text("def solve(values):\n    return values\n", encoding="utf-8")
    subs = [Submission(str(a), "a", "u1", "P1"), Submission(str(b), "b", "u2", "P2"),
            Submission(str(p), "py", "u3", "P1")]
    strict = find_duplicates(subs, min_tokens=40)
    assert strict.pairs == []
    looser = find_duplicates(subs, min_tokens=40, same_problem=False, same_language=False)
    assert any({p.a, p.b} == {"a", "b"} for p in looser.pairs), looser.pairs


def test_cross_user_and_same_user_marks():
    subs = [Submission(path="x1", id="x1", user="alice", text=BASE),
            Submission(path="x2", id="x2", user="alice", text=renamed(BASE)),
            Submission(path="x3", id="x3", user="bob", text=renamed(BASE))]
    report = find_duplicates(subs, min_tokens=40)
    by = {(p.a, p.b): p for p in report.pairs}
    assert by[("x1", "x2")].cross_user is False
    assert by[("x2", "x3")].cross_user is True
    only_cross = find_duplicates(subs, min_tokens=40, include_same_user=False)
    assert all(p.cross_user for p in only_cross.pairs) and only_cross.pairs


def test_python_block_structure_is_part_of_the_fingerprint():
    flat = "def f(v):\n    return v + 1\n"
    nested = "def f(v):\n    if v:\n        return v + 1\n    return 0\n"
    assert fingerprint(build_document(flat, "a.py")).hashes != fingerprint(build_document(nested, "b.py")).hashes
    assert any(nt.kind == "BLOCK" for nt in normalize(build_document(nested, "b.py")))


def test_scores_survive_line_endings_and_encoding(tmp_path):
    unix = tmp_path / "u.cpp"; unix.write_bytes(BASE.encode("utf-8"))
    dos = tmp_path / "d.cpp"; dos.write_bytes(BASE.replace("\n", "\r\n").encode("utf-8"))
    gbk = tmp_path / "g.cpp"; gbk.write_bytes(("%s\n// 中文注释\n" % BASE).encode("gbk"))
    from cf.similarity import read_document

    a = fingerprint(read_document(Submission(str(unix), "u")))
    b = fingerprint(read_document(Submission(str(dos), "d")))
    c = fingerprint(read_document(Submission(str(gbk), "g")))
    assert a.hashes == b.hashes == c.hashes, (a.tokens, b.tokens, c.tokens)


def test_fingerprints_are_stable_across_processes(tmp_path):
    manifest = tmp_path / "m.json"
    (tmp_path / "a.cpp").write_text(BASE, encoding="utf-8")
    (tmp_path / "b.cpp").write_text(renamed(BASE), encoding="utf-8")
    manifest.write_text(json.dumps({"submissions": [
        {"id": "a", "user": "u1", "path": "a.cpp"}, {"id": "b", "user": "u2", "path": "b.cpp"}]}),
        encoding="utf-8")
    out = []
    for _ in range(2):
        env = dict(os.environ, PYTHONHASHSEED=str(len(out)), PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-m", "cf.cli", "dup", "--manifest", str(manifest),
                            "--min-tokens", "40", "--json", "--fail-on", "none"],
                           capture_output=True, text=True, encoding="utf-8", cwd=os.getcwd(), env=env)
        assert r.returncode == 0, r.stderr
        out.append(json.loads(r.stdout))
    assert out[0]["pairs"], "the pair should be found"
    assert out[0] == out[1]


def test_manifest_paths_resolve_relative_and_duplicate_ids_are_rejected(tmp_path):
    (tmp_path / "s.cpp").write_text(BASE, encoding="utf-8")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"submissions": [{"id": "x", "path": "s.cpp", "user": "u"}]}), encoding="utf-8")
    subs = load_manifest(str(m))
    assert subs[0].path.endswith("s.cpp") and os.path.isabs(subs[0].path)
    m.write_text(json.dumps({"submissions": [{"id": "x", "path": "s.cpp"}, {"id": "x", "path": "s.cpp"}]}),
                 encoding="utf-8")
    with pytest.raises(SimilarityError):
        load_manifest(str(m))
    m.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(SimilarityError):
        load_manifest(str(m))


def test_results_are_serialisable_and_json_friendly():
    sim = compare(BASE, renamed(BASE), min_tokens=40)
    payload = sim.to_dict()
    assert json.dumps(payload) and payload["qualifies"] is True
    assert isinstance(sim.evidence[0], MatchSpan)
    report = find_duplicates([Submission(path="p", id="p", text=BASE),
                              Submission(path="q", id="q", text=renamed(BASE))], min_tokens=40)
    doc = report.to_dict()
    assert doc["version"] == 1 and doc["params"]["k"] == 7
    assert {s["id"] for s in doc["submissions"]} == {"p", "q"}


def test_rolling_window_hash_matches_the_naive_polynomial():
    from cf.similarity import BASE, MASK64, _window_hashes

    codes = [i * 7919 + 3 for i in range(40)]
    for k in (1, 2, 5, 7):
        rolled = dict(_window_hashes(codes, k))
        naive = {}
        for start in range(0, len(codes) - k + 1):
            h = 0
            for j in range(k):
                h = ((h * BASE) + codes[start + j]) & MASK64
            naive[start] = h
        assert rolled == naive, k


def test_fingerprint_carries_rows_not_token_objects():
    fp = fingerprint(build_document(BASE, "mem.cpp"))
    assert not hasattr(fp, "norm")
    assert len(fp.row_at) == fp.tokens            # one row per normalised token
    assert min(fp.row_at) >= 1 and max(fp.row_at) <= fp.rows


def test_zero_evidence_keeps_scores_but_skips_run_detection():
    sim = compare(BASE, renamed(BASE), min_tokens=40, evidence=0)
    assert sim.jaccard == 1.0 and sim.qualifies
    assert sim.evidence == ()


def test_a_subset_copy_survives_the_score_prefilter():
    # the whole point of containment: a short file can sit entirely inside a long one even
    # though jaccard is small, so the pre-filter must never judge a pair by its size ratio
    head = BASE[: BASE.index("    void report")]
    report = find_duplicates([Submission(path="b", id="big", text=BASE, problem="P"),
                              Submission(path="s", id="small", text=head, problem="P")], min_tokens=20)
    assert report.pairs, report.warnings
    pair = report.pairs[0]
    assert pair.jaccard < 0.5 < pair.containment, pair.to_dict()
    assert pair.containment_ab >= 0.8 or pair.containment_ba >= 0.8


def test_pairs_without_a_single_shared_kgram_never_become_candidates():
    tiny = Submission(path="t", id="tiny", text="int main(){return 0;}\n", problem="P")
    big = Submission(path="b", id="big", text=BASE, problem="P")
    assert find_duplicates([tiny, big], min_tokens=1).pairs == []
    unbounded = find_duplicates([tiny, big], min_tokens=1, min_jaccard=0.0,
                                min_containment=0.0, min_shared=1)
    assert unbounded.pairs == [], "they share no k-gram, so no candidate is even formed"


def test_max_df_controls_the_boilerplate_cut():
    head = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){\n"
    bodies = ["    int n; cin >> n; cout << n << endl;\n}\n",
              "    int m; cin >> m; cout << m << endl;\n}\n",
              "    int k; cin >> k; cout << k << endl;\n}\n"]
    subs = [Submission(path=f"s{i}", id=f"s{i}", user=f"u{i}", problem="P",
                        text=head + bodies[i % 3]) for i in range(30)]
    strict = find_duplicates(subs, min_tokens=20, max_df=0.2)
    loose = find_duplicates(subs, min_tokens=20, keep_common=True)
    assert len(strict.pairs) <= len(loose.pairs)
    assert any(w.startswith("boilerplate-filtered") for w in strict.warnings), strict.warnings
    assert not any(w.startswith("boilerplate-filtered") for w in loose.warnings)


def test_the_optimised_pipeline_matches_brute_force_pairwise(tmp_path):
    """Grouping, posting counts and the score pre-filter must not change which pairs are reported."""
    import itertools

    base = read_sample("cpp_knr.cpp")
    variants = [base, base.replace("values", "nums"), base.replace("total", "acc"),
                read_sample("cpp_allman.cpp"), read_sample("mixed.cpp"),
                read_sample("go_style.go"), read_sample("js_single.js"),
                base.replace("cache_", "memo_")]
    subs = []
    for i, text in enumerate(variants):
        suffix = ".go" if "func main" in text else (".js" if "export" in text else ".cpp")
        path = tmp_path / f"v{i}{suffix}"
        path.write_text(text, encoding="utf-8")
        subs.append(Submission(path=str(path), id=f"v{i}", user=f"u{i % 4}",
                               problem=f"P{i // 4}"))
    kwargs = dict(min_tokens=20, min_shared=2)
    fast = {(min(p.a, p.b), max(p.a, p.b)) for p in find_duplicates(subs, **kwargs).pairs}
    slow = set()
    for a, b in itertools.combinations(subs, 2):
        if a.problem != b.problem:
            continue
        sim = compare_documents(read_document(a), read_document(b), **kwargs)
        if sim.qualifies:
            slow.add((min(a.id, b.id), max(a.id, b.id)))
    assert fast == slow, (fast - slow, slow - fast)


def test_jobs_matches_serial(tmp_path):
    """Spreading the shards over processes may change scheduling, never the report.

    The parallel pass counts candidates per process and re-merges them in the parent, so this
    compares the whole report - pairs, evidence, submission info and every warning counter - not
    just the pair ids.  max_candidates is in the list because it truncates globally, across shards.
    """
    texts = [BASE, renamed(BASE), BASE.replace("cache_", "memo_"), read_sample("cpp_allman.cpp"),
             read_sample("mixed.cpp"), read_sample("cpp_allman.cpp").replace("values", "nums"),
             BASE.replace("total", "acc"), read_sample("cpp_allman.cpp").replace("total", "acc")]
    subs = []
    for i, text in enumerate(texts):
        suffix = ".go" if "func main" in text else (".js" if "export" in text else ".cpp")
        path = tmp_path / f"s{i}{suffix}"
        path.write_text(text, encoding="utf-8")
        subs.append(Submission(path=str(path), id=f"s{i}", user=f"u{i % 3}", problem=f"P{i % 4}"))
    for kwargs in (dict(min_tokens=20, min_shared=2), dict(min_tokens=20, min_shared=2, evidence=0),
                   dict(min_tokens=20, max_candidates=3)):
        serial = find_duplicates(subs, jobs=1, **kwargs).to_dict()
        assert find_duplicates(subs, jobs=2, **kwargs).to_dict() == serial, kwargs


def test_the_shard_key_agrees_with_the_language_actually_lexed(tmp_path):
    """The parent shards by (problem, family) before lexing, so that guess must not be a guess.

    Sharding happens without reading the file whenever the name settles it, which is what makes
    the parallel pass cheap; an extension-less sample covers the path that has to look inside.
    """
    from cf.similarity import _shard_of

    for name in ("c_tabs.c", "cpp_allman.cpp", "cpp_knr.cpp", "go_style.go", "js_single.js",
                 "mixed.cpp", "py_default.py"):
        plain = tmp_path / name.split(".")[0]          # no extension: only the content decides
        plain.write_text(read_sample(name), encoding="utf-8")
        for path in (sample_path(name), str(plain)):
            sub = Submission(path=path, id=os.path.basename(path))
            assert _shard_of(sub, True, True)[1] == read_document(sub).spec.family, path
    forced = Submission(path=sample_path("cpp_knr.cpp"), id="forced", language="python")
    assert _shard_of(forced, True, True)[1] == read_document(forced).spec.family == "python"
