"""Code similarity and duplicate detection across submissions.

The kernel's side of an audit: normalise away names, whitespace and comments, fingerprint the
remaining token structure, and report how much two submissions share.  It produces numbers and
evidence, never a verdict - deciding what a high score *means* belongs to a human reviewer.

Nothing here touches the network, executes the inspected code, or copies source text into a
report: evidence is line ranges and token counts only.
"""
from __future__ import annotations

import itertools
import json
import os
import re
from dataclasses import dataclass, field

from .document import Document, build_document, normalize as normalize_text
from .tokens import CHR, CMT, ID, KW, NUM, PRE, PUNCT, SPEC_BY_NAME, STR, detect, spec_from_path

SCHEMA_VERSION = 1
DEFAULT_K = 7
DEFAULT_WINDOW = 4
DEFAULT_MIN_SHARED = 3
DEFAULT_MIN_TOKENS = 80
DEFAULT_MIN_JACCARD = 0.5
DEFAULT_MIN_CONTAINMENT = 0.8
DEFAULT_EVIDENCE = 3
BOILERPLATE_MIN_DOCS = 10
BOILERPLATE_DOC_RATIO = 0.8
MAX_POSTINGS = 256      # a k-gram in more submissions than this cannot discriminate inside the bucket
POSITION_CAP = 12          # a k-gram this repetitive is not useful evidence

MASK64 = (1 << 64) - 1
FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
BASE = 257


class SimilarityError(ValueError):
    """A manifest or submission set the caller described cannot be used."""


def fnv1a(text: str) -> int:
    """A process-independent 64-bit hash.

    ``hash()`` is salted per Python run, so two runs over the same submissions would disagree.
    """
    h = FNV_OFFSET
    for byte in text.encode("utf-8", "replace"):
        h = ((h ^ byte) * FNV_PRIME) & MASK64
    return h


# -- data model ---------------------------------------------------------------


@dataclass(frozen=True)
class NormalToken:
    kind: str
    text: str
    row: int

    def key(self) -> str:
        return self.kind if self.kind in ("ID", "NUM", "STR") else f"{self.kind} {self.text}"


@dataclass(frozen=True)
class MatchSpan:
    a_lines: tuple[int, int]
    b_lines: tuple[int, int]
    tokens: int

    def to_dict(self) -> dict:
        return {"a_lines": list(self.a_lines), "b_lines": list(self.b_lines), "tokens": self.tokens}


@dataclass(frozen=True)
class Fingerprint:
    tokens: int
    rows: int
    hashes: frozenset                      # winnowed representatives, the scoring basis
    kgrams: tuple                          # (normalised-token index, hash) for every k-gram
    row_at: tuple = ()                     # token index -> source row, so evidence carries no source

@dataclass(frozen=True)
class Submission:
    path: str
    id: str = ""
    user: str = "unknown"
    problem: str | None = None
    language: str | None = None
    submitted_at: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", self.path)


@dataclass(frozen=True)
class Similarity:
    a: str
    b: str
    user_a: str
    user_b: str
    cross_user: bool
    problem: str | None
    language_a: str
    language_b: str
    jaccard: float
    containment_ab: float
    containment_ba: float
    containment: float
    shared_ngrams: int
    tokens_a: int
    tokens_b: int
    evidence: tuple
    qualifies: bool
    warnings: tuple

    def to_dict(self) -> dict:
        return {
            "a": self.a, "b": self.b, "user_a": self.user_a, "user_b": self.user_b,
            "cross_user": self.cross_user, "problem": self.problem,
            "language_a": self.language_a, "language_b": self.language_b,
            "jaccard": self.jaccard, "containment_ab": self.containment_ab,
            "containment_ba": self.containment_ba, "containment": self.containment,
            "shared_ngrams": self.shared_ngrams, "tokens_a": self.tokens_a,
            "tokens_b": self.tokens_b, "evidence": [e.to_dict() for e in self.evidence],
            "qualifies": self.qualifies, "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SubmissionInfo:
    id: str
    user: str
    problem: str | None
    path: str
    language: str
    tokens: int
    rows: int

    def to_dict(self) -> dict:
        return {"id": self.id, "user": self.user, "problem": self.problem, "path": self.path,
                "language": self.language, "tokens": self.tokens, "rows": self.rows}


@dataclass(frozen=True)
class Cluster:
    id: str
    members: tuple
    users: tuple
    cross_user: bool
    pair_ids: tuple
    max_jaccard: float
    max_containment: float
    size: int

    def to_dict(self) -> dict:
        return {"id": self.id, "members": list(self.members), "users": list(self.users),
                "cross_user": self.cross_user, "pair_ids": [list(p) for p in self.pair_ids],
                "max_jaccard": self.max_jaccard, "max_containment": self.max_containment,
                "size": self.size}


@dataclass
class SimilarityReport:
    version: int = SCHEMA_VERSION
    params: dict = field(default_factory=dict)
    submissions: list = field(default_factory=list)
    pairs: list = field(default_factory=list)
    clusters: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "params": dict(self.params),
            "submissions": [s.to_dict() for s in sorted(self.submissions, key=lambda x: x.id)],
            "pairs": [p.to_dict() for p in self.pairs],
            "clusters": [c.to_dict() for c in self.clusters],
            "warnings": list(self.warnings),
        }


# -- normalisation ------------------------------------------------------------


def normalize(doc: Document) -> list[NormalToken]:
    """Drop everything a rename or a reindent would change; keep the structure.

    Identifiers, numbers and string/char literals become one symbol each, comments vanish,
    keywords and punctuation keep their text.  Python has no braces, so its block level is
    emitted as ``{``/``}`` markers - without them a nested and a flat program would normalise
    to the same stream.
    """
    levels: dict[int, int] = {}
    if doc.spec.family == "python":
        from .py_lang import python_levels

        levels = python_levels(doc.src)
    out: list[NormalToken] = []
    previous = 0
    seen: set[int] = set()
    for t in doc.tokens:
        if t.kind == CMT:
            continue
        if levels and t.kind != PRE and t.row not in seen:
            seen.add(t.row)
            level = max(0, int(levels.get(t.row, previous)))
            if level > previous:
                out.extend(NormalToken("BLOCK", "{", t.row) for _ in range(level - previous))
            elif level < previous:
                out.extend(NormalToken("BLOCK", "}", t.row) for _ in range(previous - level))
            previous = level
        if t.kind == PRE:
            out.append(NormalToken("PRE", "PRE " + re.sub(r"\s+", " ", t.text.strip()), t.row))
        elif t.kind in (KW, PUNCT):
            out.append(NormalToken(t.kind, f"{t.kind} {t.text}", t.row))
        elif t.kind == ID:
            out.append(NormalToken("ID", "ID", t.row))
        elif t.kind in (NUM, STR, CHR):
            out.append(NormalToken({NUM: "NUM", STR: "STR", CHR: "STR"}[t.kind],
                                   {NUM: "NUM", STR: "STR", CHR: "STR"}[t.kind], t.row))
        else:
            out.append(NormalToken("ID", "ID", t.row))
    return out


_CODE_MEMO: dict[str, int] = {}


def _token_code(key: str) -> int:
    """A content-derived code per normalised token, so a k-gram hashes the same everywhere.

    Interning against a per-run table would be faster still, but the ids would then depend on
    the order files were read in, and two processes would disagree about what matches.
    """
    code = _CODE_MEMO.get(key)
    if code is None:
        code = fnv1a(key) or 1
        if len(_CODE_MEMO) < 200_000:
            _CODE_MEMO[key] = code
    return code


def _window_hashes(codes: list[int], k: int) -> list[tuple[int, int]]:
    """Rabin-Karp rolling hash of every k-length window: O(1) per step, no string building.

    The values depend only on the codes in the window, so they are stable across runs,
    processes and file order - the same guarantee ``fnv1a`` gave, for a fraction of the work.
    """
    n = len(codes)
    if n < k:
        return []
    power = pow(BASE, k - 1, 1 << 64)
    h = 0
    for i in range(k):
        h = (h * BASE + codes[i]) & MASK64
    out = [(0, h)]
    for i in range(1, n - k + 1):
        h = ((h - codes[i - 1] * power) * BASE + codes[i + k - 1]) & MASK64
        out.append((i, h))
    return out


def fingerprint(doc: Document, *, k: int = DEFAULT_K, window: int = DEFAULT_WINDOW,
                winnow: bool = True) -> Fingerprint:
    """The k-gram fingerprint of one document."""
    if k < 1:
        raise SimilarityError("k must be at least 1")
    norm = normalize(doc)
    codes = [_token_code(nt.key()) for nt in norm]
    kgrams = tuple(_window_hashes(codes, k))
    row_at = tuple(nt.row for nt in norm)      # token index -> source row, for evidence
    if not kgrams:
        return Fingerprint(len(norm), len(doc.lines), frozenset(), (), row_at)
    if not winnow or window <= 1:
        return Fingerprint(len(norm), len(doc.lines), frozenset(h for _s, h in kgrams), kgrams, row_at)
    hashes = [h for _s, h in kgrams]
    keep: set[int] = set()
    for i in range(len(hashes)):
        keep.add(min(hashes[i:i + window]))
    return Fingerprint(len(norm), len(doc.lines), frozenset(keep), kgrams, row_at)


# -- evidence -----------------------------------------------------------------


def shared_runs(a: Fingerprint, b: Fingerprint, allowed: set, keep: int, k: int) -> tuple[list, bool]:
    """Longest contiguous stretches of shared k-grams, as line ranges (no source text)."""
    if not a.kgrams or not b.kgrams:
        return [], False
    hash_a = tuple(h for _start, h in a.kgrams)
    hash_b = tuple(h for _start, h in b.kgrams)
    pos_b: dict[int, list[int]] = {}
    for ordinal, h in enumerate(hash_b):
        pos_b.setdefault(h, []).append(ordinal)
    runs: list[tuple[int, int, int]] = []
    truncated = False
    for ai, h in enumerate(hash_a):
        if h not in allowed:
            continue
        candidates = pos_b.get(h, ())
        if len(candidates) > POSITION_CAP:
            candidates = candidates[:POSITION_CAP]
            truncated = True
        for bi in candidates:
            if ai and bi and hash_a[ai - 1] == hash_b[bi - 1]:
                continue  # this cell continues a run already recorded at its first cell
            length = 1
            while (ai + length < len(hash_a) and bi + length < len(hash_b)
                   and hash_a[ai + length] == hash_b[bi + length] and hash_a[ai + length] in allowed):
                length += 1
            runs.append((ai, bi, length))
    runs.sort(key=lambda r: (-r[2], r[0], r[1]))
    spans: list[MatchSpan] = []
    taken: list[tuple[int, int]] = []
    last_a = max(1, len(a.row_at) - 1)
    last_b = max(1, len(b.row_at) - 1)
    for ai, bi, length in runs:
        a0, a1 = a.kgrams[ai][0], a.kgrams[min(ai + length - 1, len(a.kgrams) - 1)][0]
        b0, b1 = b.kgrams[bi][0], b.kgrams[min(bi + length - 1, len(b.kgrams) - 1)][0]
        if any(not (a1 + k - a0 < lo or a0 > hi) for lo, hi in taken):
            continue
        taken.append((a0, a1 + k - a0))
        spans.append(MatchSpan(
            (a.row_at[a0], a.row_at[min(a1 + k - 1, last_a)]),
            (b.row_at[b0], b.row_at[min(b1 + k - 1, last_b)]),
            a1 - a0 + k,
        ))
        if len(spans) >= keep:
            break
    return spans, truncated


def _scores(ha: frozenset, hb: frozenset) -> tuple:
    inter = len(ha & hb)
    union = len(ha | hb)
    jaccard = inter / union if union else 0.0
    cab = inter / len(ha) if ha else 0.0
    cba = inter / len(hb) if hb else 0.0
    return (round(jaccard, 3), round(cab, 3), round(cba, 3), round(max(cab, cba), 3), inter)


def _compare(a: Document, b: Document, fa: Fingerprint, fb: Fingerprint, ha: frozenset, hb: frozenset,
             *, meta_a, meta_b, k: int, min_shared: int, min_jaccard: float, min_containment: float,
             min_tokens: int, evidence: int, drop: set = frozenset()) -> Similarity:
    jaccard, cab, cba, containment, shared = _scores(ha, hb)
    warnings: list[str] = []
    for side, fp in (("a", fa), ("b", fb)):
        if fp.tokens < min_tokens:
            warnings.append(f"{side}-too-short:{fp.tokens}")
    # the score uses the winnowed representatives; evidence has to walk the full k-gram
    # sequence, because representatives are deliberately sparse and never adjacent
    common = ({h for _start, h in fa.kgrams} & {h for _start, h in fb.kgrams}) - drop
    if shared < min_shared:
        warnings.append(f"below-min-shared:{shared}")
        qualifies = False
    else:
        qualifies = fa.tokens >= min_tokens and fb.tokens >= min_tokens and (
            jaccard >= min_jaccard or containment >= min_containment)
    if evidence <= 0:
        spans, truncated = [], False
    else:
        spans, truncated = (shared_runs(fa, fb, common, evidence, k) if common else ([], False))
    if truncated:
        warnings.append("evidence-truncated")
    if not spans and qualifies:
        warnings.append("no-evidence-runs")
    return Similarity(
        a=meta_a.id, b=meta_b.id, user_a=meta_a.user, user_b=meta_b.user,
        cross_user=meta_a.user != meta_b.user,
        problem=meta_a.problem if meta_a.problem == meta_b.problem else None,
        language_a=a.spec.name, language_b=b.spec.name,
        jaccard=jaccard, containment_ab=cab, containment_ba=cba, containment=containment,
        shared_ngrams=shared, tokens_a=fa.tokens, tokens_b=fb.tokens,
        evidence=tuple(spans), qualifies=qualifies, warnings=tuple(warnings),
    )


def compare_documents(a: Document, b: Document, *, k: int = DEFAULT_K, window: int = DEFAULT_WINDOW,
                      min_shared: int = DEFAULT_MIN_SHARED, min_tokens: int = DEFAULT_MIN_TOKENS,
                      winnow: bool = True, keep_common: bool = False,
                      evidence: int = DEFAULT_EVIDENCE,
                      min_jaccard: float = DEFAULT_MIN_JACCARD,
                      min_containment: float = DEFAULT_MIN_CONTAINMENT) -> Similarity:
    """Compare two documents on their own (no corpus-level boilerplate filtering)."""
    fa = fingerprint(a, k=k, window=window, winnow=winnow)
    fb = fingerprint(b, k=k, window=window, winnow=winnow)
    return _compare(a, b, fa, fb, fa.hashes, fb.hashes,
                    meta_a=Submission(path=a.path, user="unknown"),
                    meta_b=Submission(path=b.path, user="unknown"),
                    k=k, min_shared=min_shared, min_jaccard=min_jaccard,
                    min_containment=min_containment, min_tokens=min_tokens, evidence=evidence)


# -- manifest -----------------------------------------------------------------


def load_manifest(path: str) -> list[Submission]:
    """Read a submissions manifest; paths inside it resolve against the manifest's folder."""
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as exc:
        raise SimilarityError(f"cannot read manifest {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SimilarityError(f"manifest {path} is not valid JSON: {exc}") from exc
    items = data.get("submissions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SimilarityError(f"manifest {path} needs a 'submissions' list")
    base = os.path.dirname(os.path.abspath(path))
    out: list[Submission] = []
    seen: set[str] = set()
    for n, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("path"):
            raise SimilarityError(f"manifest {path}: entry #{n + 1} has no 'path'")
        file_path = item["path"] if os.path.isabs(item["path"]) else os.path.normpath(os.path.join(base, item["path"]))
        sub = Submission(
            path=file_path,
            id=item.get("id") or file_path,
            user=item.get("user") or "unknown",
            problem=item.get("problem"),
            language=item.get("lang") or item.get("language"),
            submitted_at=item.get("submitted_at"),
        )
        if sub.id in seen:
            raise SimilarityError(f"manifest {path}: duplicate submission id {sub.id!r}")
        seen.add(sub.id)
        out.append(sub)
    return out


def read_document(sub: Submission) -> Document:
    """Load a submission's source, honouring an explicit language when the manifest gives one."""
    from .sources import InputError, decode_bytes, read_bytes
    from .tokens import SPEC_BY_NAME

    spec = None
    if sub.language:
        if sub.language not in SPEC_BY_NAME:
            raise SimilarityError(f"unknown language {sub.language!r} for {sub.id}")
        spec = SPEC_BY_NAME[sub.language]
    if sub.text is not None:
        return build_document(sub.text, sub.path, spec)
    try:
        text, _enc = decode_bytes(read_bytes(sub.path))
    except InputError as exc:
        raise SimilarityError(str(exc)) from exc
    return build_document(text, sub.path, spec)


# -- corpus pass --------------------------------------------------------------

# A shard's documents and fingerprints stay in the process that lexed them, so the scoring pass
# over the same shard does not read the files a second time.
_SHARD_CACHE: dict[tuple, tuple] = {}
_RUN_IDS = itertools.count(1)


def _shard_of(sub: Submission, same_problem: bool, same_language: bool) -> tuple:
    """The (problem, language family) shard a submission belongs to, decided without lexing it.

    Sharding is what keeps the pass cheap, so the parent must be able to partition before paying
    for the lexer; the worker re-reads the same file anyway, it just does it in parallel.
    """
    family = None
    if same_language:
        if sub.language:
            if sub.language not in SPEC_BY_NAME:
                raise SimilarityError(f"unknown language {sub.language!r} for {sub.id}")
            family = SPEC_BY_NAME[sub.language].family
        else:
            by_path = spec_from_path(sub.path)
            if by_path is not None:
                family = by_path.family
            elif sub.text is not None:
                family = detect(sub.path, normalize_text(sub.text)[0]).family
            else:
                from .sources import InputError, decode_bytes, read_bytes

                try:
                    text, _enc = decode_bytes(read_bytes(sub.path))
                except InputError as exc:
                    raise SimilarityError(str(exc)) from exc
                family = detect(sub.path, normalize_text(text)[0]).family
    return (sub.problem if same_problem else None, family)


def _lex_shard(subs: list[Submission], params: dict):
    """Lex one shard and split off the k-grams that say nothing about matching in this shard."""
    docs, fps = [], []
    for sub in subs:
        doc = read_document(sub)
        docs.append(doc)
        fps.append(fingerprint(doc, k=params["k"], window=params["window"], winnow=params["winnow"]))
    kept = [f.hashes for f in fps]
    if params["keep_common"] or len(subs) < BOILERPLATE_MIN_DOCS:
        return docs, fps, kept, frozenset(), 0
    df: dict[int, int] = {}
    for hashes in kept:
        for h in hashes:
            df[h] = df.get(h, 0) + 1
    drop = {h for h, count in df.items() if count > params["max_df"] * len(subs)}
    if not drop:
        return docs, fps, kept, frozenset(), 0
    frozen = frozenset(drop)
    return docs, fps, [h - frozen for h in kept], frozen, len(drop)


def _count_shard(payload: dict) -> dict:
    """Read a shard, then count how many representatives each pair inside it shares.

    Candidate codes use the corpus-wide index space (``i * n + j``), not shard-local positions, so
    the caller can order and truncate candidates globally: ``max_candidates`` has to mean the same
    thing sharded or not, and a per-shard budget would quietly multiply it by the number of shards.
    """
    subs, params, gidx = payload["subs"], payload["params"], payload["gidx"]
    for stale in [k for k in _SHARD_CACHE if k[0] != payload["run"]]:
        del _SHARD_CACHE[stale]      # the previous run's shards: this run's scoring pops as it goes
    docs, fps, kept, frozen, filtered = _lex_shard(subs, params)
    index: dict[int, list[int]] = {}
    for pos, hashes in enumerate(kept):
        for h in hashes:
            index.setdefault(h, []).append(pos)
    candidates: dict[int, int] = {}
    capped = 0
    n = params["n"]
    for holders in index.values():
        if len(holders) > MAX_POSTINGS:
            capped += 1
            continue  # this k-gram cannot discriminate inside such a large shard
        for x in range(len(holders)):
            left = gidx[holders[x]] * n
            for y in range(x + 1, len(holders)):
                code = left + gidx[holders[y]]
                candidates[code] = candidates.get(code, 0) + 1
    _SHARD_CACHE[payload["run"], payload["key"]] = (subs, docs, fps, kept, frozen)
    # short or contentless submissions cannot carry evidence; say so at report level, because
    # the pairs they would have produced are filtered out and would never be shown
    infos, short = [], []
    for pos, sub in enumerate(subs):
        fp = fps[pos]
        infos.append(SubmissionInfo(sub.id, sub.user, sub.problem, sub.path, docs[pos].spec.name,
                                    fp.tokens, fp.rows))
        if fp.tokens < params["min_tokens"]:
            short.append((sub.id, f"too-short:{sub.id}:{fp.tokens}"))
        elif not fp.kgrams:
            short.append((sub.id, f"no-kgrams:{sub.id}"))
    return {"candidates": list(candidates.items()),
            "sizes": [(gidx[p], len(kept[p])) for p in range(len(subs))],
            "infos": infos, "short": short, "filtered": filtered, "capped": capped}


def _score_shard(payload: dict) -> list:
    """Take evidence for the pairs the caller kept, in the shard that already lexed them."""
    subs, params, gidx = payload["subs"], payload["params"], payload["gidx"]
    state = _SHARD_CACHE.pop((payload["run"], payload["key"]), None)
    if state is None:  # the shard was never counted here: a recycled worker, or a direct call
        docs, fps, kept, frozen, _f = _lex_shard(subs, params)
    else:
        docs, fps, kept, frozen = state[1], state[2], state[3], state[4]
    pos = {g: p for p, g in enumerate(gidx)}
    out = []
    for i, j, _shared in payload["pairs"]:
        pi, pj = pos[i], pos[j]
        sim = _compare(docs[pi], docs[pj], fps[pi], fps[pj], kept[pi], kept[pj],
                       meta_a=subs[pi], meta_b=subs[pj], k=params["k"],
                       min_shared=params["min_shared"], min_jaccard=params["min_jaccard"],
                       min_containment=params["min_containment"], min_tokens=params["min_tokens"],
                       evidence=params["evidence"], drop=frozen)
        if sim.qualifies:
            out.append(sim)
    return out


def _pool_for(jobs: int, count: int):
    """A process pool for one run, or None to do the work in this process.

    One pool serves both passes because creating it costs interpreter startup per worker; paying
    that twice per run would eat the win on anything but the largest corpora.
    """
    if jobs < 2 or count < 2:
        return None
    import multiprocessing

    return multiprocessing.Pool(min(jobs, count))


def _spread(work, payloads: list, pool):
    """Run a shard pass inline or through the pool.  Results keep payload order, so sharding
    cannot reorder anything the report shows."""
    if pool is None:
        return [work(p) for p in payloads]
    return pool.map(work, payloads, chunksize=1)


def find_duplicates(submissions: list[Submission], *, min_jaccard: float = DEFAULT_MIN_JACCARD,
                    min_containment: float = DEFAULT_MIN_CONTAINMENT,
                    min_shared: int = DEFAULT_MIN_SHARED, min_tokens: int = DEFAULT_MIN_TOKENS,
                    same_problem: bool = True, same_language: bool = True,
                    include_same_user: bool = True, include_cross_user: bool = True,
                    max_candidates: int | None = None, evidence: int = DEFAULT_EVIDENCE,
                    k: int = DEFAULT_K, window: int = DEFAULT_WINDOW, winnow: bool = True,
                    keep_common: bool = False, max_df: float = BOILERPLATE_DOC_RATIO,
                    jobs: int = 1) -> SimilarityReport:
    """Compare a set of submissions and group the pairs that share too much.

    ``max_df`` is the document frequency, as a fraction of the shard, above which a k-gram is
    treated as boilerplate: it appears in nearly every submission of that problem, so it says
    nothing about whether two of them match.

    ``jobs`` spreads the shards over processes: 1 keeps everything in this process, 0 uses every
    cpu, any larger number caps it.  It changes scheduling only - the report is identical either
    way, which ``test_jobs_matches_serial`` pins down.
    """
    report = SimilarityReport(params={
        "k": k, "window": window, "min_jaccard": round(min_jaccard, 3),
        "min_containment": round(min_containment, 3), "min_shared": min_shared,
        "min_tokens": min_tokens, "winnow": winnow, "keep_common": keep_common,
        "same_problem": same_problem, "same_language": same_language, "max_df": round(max_df, 3),
    })
    if not submissions:
        return report
    ids = [s.id for s in submissions]
    if len(set(ids)) != len(ids):
        raise SimilarityError("submission ids must be unique")

    subs = sorted(submissions, key=lambda s: s.id)
    n = len(subs)
    params = {"k": k, "window": window, "winnow": winnow, "n": n, "min_shared": min_shared,
              "min_jaccard": min_jaccard, "min_containment": min_containment,
              "min_tokens": min_tokens, "evidence": evidence, "keep_common": keep_common,
              "max_df": max_df}
    # Candidates are generated per (problem, language family) shard, never globally: a boilerplate
    # k-gram sitting in most of 2000 submissions would otherwise be counted 2000*1999/2 times,
    # while submissions to different problems are never compared anyway.  Shards are disjoint, so
    # they can also be worked in parallel - which is how the pass stays flat past 1000 people.
    shards: dict[tuple, list[int]] = {}
    owner: dict[int, tuple] = {}
    for idx, sub in enumerate(subs):
        key = _shard_of(sub, same_problem, same_language)
        shards.setdefault(key, []).append(idx)
        owner[idx] = key
    run = next(_RUN_IDS)
    payloads = []
    for key in sorted(shards, key=str):
        members = sorted(shards[key])
        payloads.append({"run": run, "key": key, "gidx": members, "params": params,
                         "subs": [subs[i] for i in members]})
    workers = _pool_for((os.cpu_count() or 1) if jobs < 1 else jobs, len(payloads))
    try:
        counted = _spread(_count_shard, payloads, workers)
        candidates: dict[int, int] = {}
        sizes: dict[int, int] = {}
        short: list[tuple[str, str]] = []
        filtered = 0
        capped = 0
        for result in counted:
            report.submissions.extend(result["infos"])
            candidates.update(result["candidates"])
            sizes.update(result["sizes"])
            short.extend(result["short"])
            filtered += result["filtered"]
            capped += result["capped"]
        report.submissions.sort(key=lambda info: info.id)
        for _sid, warning in sorted(short, key=lambda item: item[0]):
            report.warnings.append(warning)
        if filtered:
            report.warnings.append(f"boilerplate-filtered:{filtered}")
        if capped:
            report.warnings.append(f"postings-capped:{capped}")
        if same_problem:
            untagged = sum(1 for sub in subs if not sub.problem)
            if untagged:
                report.warnings.append(f"no-problem-id:{untagged}(compared globally)")
        if same_language and len(shards) > len({key[0] for key in shards}):
            report.warnings.append(f"language-split:{len(shards)}")

        ordered = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
        if max_candidates is not None and len(ordered) > max_candidates:
            report.warnings.append(f"candidates-truncated:{len(ordered) - max_candidates}")
            ordered = ordered[:max_candidates]

        # The postings count for a pair *is* |ha ∩ hb| (a representative appears at most once per
        # document), so both scores follow exactly from the counts we already have - no set work
        # and no approximation.  Note containment cannot be bounded by the size ratio: for a
        # subset copy it reaches 1.0 however different the sizes are, so pruning on ratio would
        # lose real matches.
        todo: dict[tuple, list] = {}
        pruned_by_score = 0
        for code, shared in ordered:
            i, j = divmod(code, n)
            if shared < min_shared:
                continue
            sub_a, sub_b = subs[i], subs[j]
            if sub_a.user == sub_b.user and not include_same_user:
                continue
            if sub_a.user != sub_b.user and not include_cross_user:
                continue
            pair_sizes = (sizes[i], sizes[j])
            smaller = min(pair_sizes)
            union = pair_sizes[0] + pair_sizes[1] - shared
            containment = shared / smaller if smaller else 0.0
            jaccard = shared / union if union else 0.0
            if jaccard < min_jaccard and containment < min_containment:
                pruned_by_score += 1
                continue
            todo.setdefault(owner[i], []).append((i, j, shared))
        scoring = []
        for payload in payloads:
            pairs = todo.get(payload["key"])
            if pairs:
                item = dict(payload)
                item["pairs"] = pairs
                scoring.append(item)
        chunks = _spread(_score_shard, scoring, workers)
    finally:
        if workers is not None:
            workers.close()
            workers.join()
    for chunk in chunks:
        report.pairs.extend(chunk)
    if pruned_by_score:
        report.warnings.append(f"pruned-by-score:{pruned_by_score}")

    report.pairs.sort(key=lambda s: (-s.jaccard, -s.containment, s.a, s.b))
    report.clusters = _clusters(report.pairs)
    return report


def _clusters(pairs) -> list:
    """Connected components over qualifying pairs (chain-linked groups are reported as such)."""
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    by_user = {}
    for p in pairs:
        union(p.a, p.b)
        by_user[p.a] = p.user_a
        by_user[p.b] = p.user_b
    groups: dict[str, list] = {}
    for p in pairs:
        groups.setdefault(find(p.a), []).append(p)
    out = []
    for root, members in groups.items():
        ids = sorted({s for p in members for s in (p.a, p.b)})
        users = sorted({by_user[i] for i in ids})
        out.append(Cluster(
            id="", members=tuple(ids), users=tuple(users), cross_user=len(users) > 1,
            pair_ids=tuple(sorted((p.a, p.b) for p in members)),
            max_jaccard=max(p.jaccard for p in members), max_containment=max(p.containment for p in members),
            size=len(ids),
        ))
    out.sort(key=lambda c: (-c.size, -c.max_jaccard, c.members[0]))
    return [Cluster(f"cluster-{n}", c.members, c.users, c.cross_user, c.pair_ids,
                    c.max_jaccard, c.max_containment, c.size) for n, c in enumerate(out, 1)]


def chain_warning(report: SimilarityReport) -> str | None:
    """Clusters are transitive: A~B and B~C gives one cluster of three even when A and C differ."""
    chained = [c for c in report.clusters if c.size > 2]
    if not chained:
        return None
    return f"{len(chained)} cluster(s) group more than two submissions by transitive matching"
