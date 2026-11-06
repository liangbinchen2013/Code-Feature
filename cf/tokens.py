"""Language specs, detection and a self-contained clike tokenizer.

Python sources use ``tokenize``/``ast`` (see :mod:`cf.py_lang`); every other
supported language is scanned here so the rest of the kernel sees one token model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Token kinds
ID = "id"
KW = "kw"
NUM = "num"
STR = "str"
CHR = "char"
CMT = "cmt"
PUNCT = "punct"
PRE = "pre"  # preprocessor directive, kept verbatim

_MULTI_OPS = sorted(
    {
        "<<=", ">>=", "...", "===", "!==", "**=", "&&=", "||=", "??=",
        "->", "=>", "::", ":=", "==", "!=", "<=", ">=", "&&", "||", "++", "--",
        "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "**", "//",
        "<>", "^^", "??", "!!", "|>",
    },
    key=len,
    reverse=True,
)
_OPS = set("+-*/%=&|^~<>!?:;,.(){}[]@#\\$'\"")

CONTROL_KW = frozenset(
    "if else elif for while do switch try catch finally synchronized with match case "
    "when foreach loop unless fn func def lambda".split()
)
BRACE_LEAD_KW = frozenset(
    "if else for while do switch try catch finally with match fn func foreach loop unless".split()
)
TYPE_KW = frozenset(
    "class struct enum union interface trait impl typedef namespace template typename module record".split()
)
DECL_KW = frozenset(
    "const static constexpr volatile extern register inline public private protected virtual "
    "override final explicit export default readonly let var mut abstract sealed async".split()
)
BRANCH_KW = frozenset("else catch finally elif".split())


@dataclass(frozen=True)
class Spec:
    name: str
    family: str = "clike"  # "clike" | "python"
    keywords: frozenset = frozenset()
    line_comments: tuple = ("//",)
    block_comments: tuple = (("/*", "*/"),)
    char_literals: bool = True
    single_quote_strings: bool = False
    double_quote_strings: bool = True
    backtick_strings: bool = False
    triple_quotes: bool = False
    escapes: bool = True
    preprocessor: bool = False
    semicolons: bool = True
    brace_blocks: bool = True


_C_KW = frozenset(
    "auto break case char const continue default do double else enum extern float for "
    "goto if inline int long register restrict return short signed sizeof static struct "
    "switch typedef union unsigned void volatile while _Bool NULL".split()
)
_CPP_KW = _C_KW | frozenset(
    "bool catch class constexpr decltype delete dynamic_cast explicit export false friend "
    "mutable namespace new noexcept operator override private protected public "
    "reinterpret_cast static_cast template this throw true try typename using virtual "
    "wchar_t nullptr string vector map pair set shared_ptr unique_ptr".split()
)
_GO_KW = frozenset(
    "break case chan const continue default defer else fallthrough for func go goto if "
    "import interface map package range return select struct switch type var nil true false "
    "int int8 int16 int32 int64 string error rune bool byte float32 float64 append make len "
    "cap copy delete panic recover any".split()
)
_JS_KW = frozenset(
    "async await break case catch class const continue debugger default delete do else enum "
    "export extends false finally for from function get if implements import in instanceof "
    "interface let new null of package private protected public return set static super switch "
    "this throw true try typeof var void while with yield undefined NaN".split()
)
_TS_KW = _JS_KW | frozenset(
    "declare namespace module keyof infer satisfies readonly unknown never any string number "
    "boolean bigint symbol is abstract".split()
)
_JAVA_KW = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for goto if implements import instanceof int "
    "interface long native new package private protected public return short static strictfp "
    "super switch synchronized this throw throws transient try void volatile while true false "
    "null var record yield sealed".split()
)
_RUST_KW = frozenset(
    "as async await break const continue crate dyn else enum extern false fn for if impl in "
    "let loop match mod move mut pub ref return self Self static struct super trait true type "
    "unsafe use where while union Some None Ok Err Vec String Box i32 u32 i64 u64 f32 f64 "
    "usize isize bool char".split()
)
_CS_KW = frozenset(
    "abstract as base bool break byte case catch char checked class const continue decimal "
    "default delegate do double else enum event explicit extern false finally fixed float for "
    "foreach goto if implicit in int interface internal is lock long namespace new null object "
    "operator out override params private protected public readonly ref return sbyte sealed "
    "short sizeof stackalloc static string struct switch this throw true try typeof uint ulong "
    "unchecked unsafe ushort using var virtual void volatile while async await record".split()
)
_PY_KW = frozenset(
    "and as assert async await break class continue def del elif else except finally for from "
    "global if import in is lambda nonlocal not or pass raise return try while with yield True "
    "False None self match case".split()
)
_SHELL_KW = frozenset(
    "if then else elif fi for in do done while until case esac function return local export".split()
)

SPEC_BY_NAME: dict[str, Spec] = {
    "c": Spec(name="c", keywords=_C_KW, preprocessor=True),
    "cpp": Spec(name="cpp", keywords=_CPP_KW, preprocessor=True),
    "go": Spec(name="go", keywords=_GO_KW, single_quote_strings=False),
    "javascript": Spec(name="javascript", keywords=_JS_KW, single_quote_strings=True,
                       backtick_strings=True, char_literals=False),
    "typescript": Spec(name="typescript", keywords=_TS_KW, single_quote_strings=True,
                       backtick_strings=True, char_literals=False),
    "java": Spec(name="java", keywords=_JAVA_KW),
    "rust": Spec(name="rust", keywords=_RUST_KW, single_quote_strings=False),
    "csharp": Spec(name="csharp", keywords=_CS_KW, single_quote_strings=False),
    "shell": Spec(name="shell", keywords=_SHELL_KW, line_comments=("#",), block_comments=(),
                  single_quote_strings=True, char_literals=False, semicolons=False),
    "clike": Spec(name="clike", keywords=_C_KW | _CPP_KW | _JAVA_KW, preprocessor=True),
}
PYTHON = Spec(name="python", family="python", keywords=_PY_KW, line_comments=("#",),
              block_comments=(), char_literals=False, single_quote_strings=True,
              double_quote_strings=True, triple_quotes=True, semicolons=False,
              brace_blocks=False)
SPEC_BY_NAME["python"] = PYTHON

_EXT_MAP = {
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".hh": "cpp", ".hxx": "cpp", ".ino": "cpp",
    ".go": "go", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".java": "java",
    ".rs": "rust", ".cs": "csharp", ".py": "python", ".pyw": "python", ".pyi": "python",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
}


@dataclass
class Token:
    kind: str
    text: str
    row: int      # 1-based row where the token starts
    col: int      # 0-based column where the token starts
    end_row: int
    end_col: int
    gap: int      # whitespace chars since the previous token on the same row, -1 after a line break
    index: int = 0

    @property
    def multiline(self) -> bool:
        return self.end_row != self.row

    @property
    def is_comment(self) -> bool:
        return self.kind == CMT

    @property
    def is_directive(self) -> bool:
        return self.kind == PRE

    def is_punct(self, *vals: str) -> bool:
        return self.kind == PUNCT and (not vals or self.text in vals)

    def is_kw(self, *vals: str) -> bool:
        return self.kind == KW and (not vals or self.text in vals)


def spec_from_path(path: str | None) -> Spec | None:
    """The spec a filename alone settles, or None when the content has to be read.

    Callers that only need the family - sharding an audit, for instance - can skip reading the
    file entirely, which is most of the cost when the extension is already decisive.
    """
    if not path:
        return None
    m = re.search(r"(\.[A-Za-z0-9]+)$", path)
    if m and m.group(1).lower() in _EXT_MAP:
        return SPEC_BY_NAME[_EXT_MAP[m.group(1).lower()]]
    base = re.split(r"[/\\]", path)[-1].lower()
    if base in ("makefile", "dockerfile"):
        return SPEC_BY_NAME["shell"]
    return None


def detect(path: str | None, src: str) -> Spec:
    """Resolve a spec from filename, else from content heuristics."""
    by_path = spec_from_path(path)
    if by_path is not None:
        return by_path
    head = src[:8000]
    # A Python class header is ``class Name:`` or ``class Name(Base, ...):`` and the colon ends the
    # line (a comment may follow).  ``class Foo : public Bar {`` and ``class Foo : Bar {`` are
    # C++/C# inheritance and must not be claimed here.  [ \t] rather than \s so the match cannot
    # reach across a line break.
    python_class = r"class\s+\w+(?:[ \t]*\([^)]*\))?[ \t]*:[ \t]*(?:#.*)?$"
    if re.match(r"^#!.*\bpython\b", src) or re.search(
        r"^\s*(?:from\s+\S+\s+import|def\s+\w+\s*\(|" + python_class + r"|import\s+\w+$)", head, re.M
    ):
        return PYTHON
    if re.search(r"^\s*#include\s*[<\"]", head, re.M):
        cpp_signals = r"\b(std::|template\s*<|class\s+\w+|new\s+\w+|nullptr\b|\bcout\b|\bcin\b|using\s+namespace\b|bits/)"
        return SPEC_BY_NAME["cpp"] if re.search(cpp_signals, head) else SPEC_BY_NAME["c"]
    if re.search(r"^\s*(package\s+main|func\s+\w+\s*\()", head, re.M):
        return SPEC_BY_NAME["go"]
    if re.search(r"^\s*(pub\s+fn|fn\s+\w+\s*\(|let\s+mut\s)", head, re.M):
        return SPEC_BY_NAME["rust"]
    if re.search(r"^\s*(import\s+java\.|public\s+(static\s+)?(class|void|final))", head, re.M):
        return SPEC_BY_NAME["java"]
    if re.search(r"^\s*(import\s+\{|\bexport\s+(default|const|function|async)|const\s+\w+\s*=\s*(async\s*)?\()", head, re.M):
        return SPEC_BY_NAME["typescript"] if re.search(r"\b(interface|type)\s+\w+\s*[={:]|:\s*(string|number|boolean)\b", head) else SPEC_BY_NAME["javascript"]
    if re.search(r"^\s*(#!/usr/bin/(env )?(ba)?sh|\bthen\b)", head, re.M):
        return SPEC_BY_NAME["shell"]
    return SPEC_BY_NAME["clike"]


def _ident_start(ch: str) -> bool:
    return ch.isalpha() or ch in "_$" or ord(ch) > 127


def _ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$" or ord(ch) > 127


def _scan_quoted(src: str, i: int, quote: str, escapes: bool) -> int | None:
    """Index just past the closing quote, or None when unterminated before a line break."""
    j = i + 1
    n = len(src)
    while j < n:
        ch = src[j]
        if ch == "\n":
            return None
        if escapes and ch == "\\":
            j += 2
            if src.startswith("\n", j - 1):
                return None
            continue
        if ch == quote:
            return j + 1
        j += 1
    return None


def _scan_triple(src: str, i: int, quote: str) -> int:
    closer = quote * 3
    j = i + 3
    n = len(src)
    while j < n:
        if src[j] == "\\":
            j += 2
            continue
        if src.startswith(closer, j):
            return j + 3
        j += 1
    return n


_NUMBER_RE = re.compile(
    r"(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?"
    r"|\.\d[\d_]*(?:[eE][+-]?\d+)?)"
)


def _scan_number(src: str, i: int) -> int:
    m = _NUMBER_RE.match(src, i)
    if not m:
        return i + 1
    end = m.end()
    while end < len(src) and src[end] in "uUlLfFjJ":
        end += 1
    return end


def _scan_operator(src: str, i: int) -> int:
    for op in _MULTI_OPS:
        if src.startswith(op, i):
            return i + len(op)
    return i + 1


def _scan_directive(src: str, i: int) -> int:
    n = len(src)
    j = src.find("\n", i)
    if j < 0:
        return n
    while src[i:j].rstrip("\r").endswith("\\"):
        k = src.find("\n", j + 1)
        if k < 0:
            return n
        j = k
    return j


class _Cursor:
    """Tracks row/line_start so token spans can be computed cheaply."""

    def __init__(self, src: str):
        self.src = src
        self.row = 1
        self.line_start = 0
        self.last_end = -1
        self.last_end_row = -1

    def advance_to(self, pos: int) -> None:
        nl = self.src.count("\n", self.line_start, pos)
        if nl:
            self.row += nl
            self.line_start = self.src.rfind("\n", 0, pos) + 1

    def gap_before(self, start: int) -> int:
        if self.last_end < 0 or self.last_end_row != self.row:
            return -1
        return start - self.last_end


def tokenize_clike(src: str, spec: Spec) -> list[Token]:
    """Scan ``src``; whitespace is dropped but each token keeps its gap to the previous one."""
    toks: list[Token] = []
    cur = _Cursor(src)

    def emit(kind: str, start: int, end: int) -> None:
        text = src[start:end]
        col = start - cur.line_start
        nl = text.count("\n")
        end_row = cur.row + nl if nl else cur.row
        end_col = (len(text) - text.rfind("\n") - 1) if nl else col + len(text)
        toks.append(
            Token(
                kind=kind,
                text=text,
                row=cur.row,
                col=col,
                end_row=end_row,
                end_col=end_col,
                gap=cur.gap_before(start),
                index=len(toks),
            )
        )
        cur.last_end = end
        cur.last_end_row = end_row

    i, n = 0, len(src)
    kw = spec.keywords

    while i < n:
        ch = src[i]
        if ch in " \t\r\f\v":
            i += 1
            continue
        if ch == "\n":
            cur.advance_to(i + 1)
            i += 1
            continue
        cur.advance_to(i)
        if spec.preprocessor and ch == "#" and not src[cur.line_start : i].strip():
            end = _scan_directive(src, i)
            emit(PRE, i, end)
            cur.advance_to(end)
            i = end
            continue
        consumed = False
        for lc in spec.line_comments:
            if src.startswith(lc, i):
                end = _to_eol(src, i)
                emit(CMT, i, end)
                i = end
                consumed = True
                break
        if consumed:
            continue
        for op, cl in spec.block_comments:
            if src.startswith(op, i):
                end = _find_closer(src, i + len(op), cl)
                emit(CMT, i, end)
                cur.advance_to(end)
                i = end
                consumed = True
                break
        if consumed:
            continue
        if spec.triple_quotes and ch in "\"'" and src.startswith(ch * 3, i):
            end = _scan_triple(src, i, ch)
            emit(STR, i, end)
            cur.advance_to(end)
            i = end
            continue
        if ch == '"' and spec.double_quote_strings:
            end = _scan_quoted(src, i, '"', spec.escapes) or _to_eol(src, i)
            emit(STR, i, end)
            cur.advance_to(end)
            i = end
            continue
        if ch == "'":
            end = _scan_quoted(src, i, "'", spec.escapes)
            if end is None:
                if spec.char_literals or spec.single_quote_strings:
                    emit(PUNCT, i, i + 1)
                    i += 1
                    continue
                end = _to_eol(src, i)
                emit(STR, i, end)
                cur.advance_to(end)
                i = end
                continue
            inner = src[i + 1 : end - 1]
            as_char = spec.char_literals and not spec.single_quote_strings and len(inner) <= 2 and "\n" not in inner
            emit(CHR if as_char else STR, i, end)
            i = end
            continue
        if ch == "`" and spec.backtick_strings:
            end = src.find("`", i + 1)
            end = n if end < 0 else end + 1
            emit(STR, i, end)
            cur.advance_to(end)
            i = end
            continue
        if _ident_start(ch):
            j = i + 1
            while j < n and _ident_char(src[j]):
                j += 1
            word = src[i:j]
            emit(KW if word in kw else ID, i, j)
            i = j
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            end = _scan_number(src, i)
            emit(NUM, i, end)
            i = end
            continue
        if ch in _OPS:
            end = _scan_operator(src, i)
            emit(PUNCT, i, end)
            i = end
            continue
        i += 1
    return toks


def _to_eol(src: str, i: int) -> int:
    j = src.find("\n", i)
    return len(src) if j < 0 else j


def _find_closer(src: str, i: int, closer: str) -> int:
    j = src.find(closer, i)
    return len(src) if j < 0 else j + len(closer)


tokenize = tokenize_clike


