"""Render short programming examples as Moodle question HTML."""

import re
from html import escape

_KEYWORDS = {
    "java": {
        "boolean", "break", "byte", "case", "catch", "char", "class", "continue",
        "default", "do", "double", "else", "extends", "false", "final", "float",
        "for", "if", "implements", "import", "int", "interface", "long", "new",
        "null", "package", "private", "protected", "public", "return", "short",
        "static", "String", "super", "switch", "this", "throw", "throws", "true",
        "try", "void", "while",
    },
    "c#": {
        "async", "await", "bool", "break", "byte", "case", "catch", "char", "class",
        "const", "continue", "decimal", "default", "do", "double", "else", "false",
        "float", "for", "foreach", "if", "in", "int", "interface", "long",
        "namespace", "new", "null", "override", "private", "protected", "public",
        "readonly", "return", "short", "static", "string", "switch", "this",
        "throw", "true", "try", "using", "var", "virtual", "void", "while",
    },
}
_TOKENS = re.compile(
    r"(?P<comment>//[^\r\n]*|/\*[\s\S]*?\*/)"
    r"""|(?P<string>"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*')"""
    r"|(?P<number>\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[dDfFlLmM]?\b)"
    r"|(?P<word>[$\w]+)"
)
_COLORS = {"comment": "#cbd5e1", "string": "#86efac", "number": "#fcd34d", "word": "#93c5fd"}


def render_code_block(code: str, language: str = "Java") -> str:
    """Return a labelled, left-to-right fragment that preserves the original code text."""
    if language.casefold() == "csharp":
        language = "C#"
    keywords = _KEYWORDS.get(language.casefold())
    if keywords is None:
        highlighted = escape(code)
    else:
        parts: list[str] = []
        end = 0
        for token in _TOKENS.finditer(code):
            parts.append(escape(code[end:token.start()]))
            kind = token.lastgroup
            value = token.group()
            if kind is None or (kind == "word" and value not in keywords):
                parts.append(escape(value))
            else:
                parts.append(f'<span style="color:{_COLORS[kind]}">{escape(value)}</span>')
            end = token.end()
        parts.append(escape(code[end:]))
        highlighted = "".join(parts)

    return (
        '<div dir="ltr" style="text-align:left;margin-top:16px;'
        f'font:600 13px Arial,sans-serif;color:#475569">{escape(language)}</div>'
        '<pre dir="ltr" style="text-align:left;white-space:pre;overflow-x:auto;'
        'background:#0f172a;color:#e2e8f0;padding:18px;border-radius:8px;'
        'font:16px/1.6 Consolas,monospace;margin:6px 0 16px">'
        '<code style="font:inherit;color:inherit;background:transparent;padding:0">'
        f'{highlighted}</code></pre>'
    )
