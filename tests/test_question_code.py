from bs4 import BeautifulSoup

from moodlectl.output.question_code import render_code_block


def test_java_preserves_code_text_and_highlights_syntax():
    snippet = '\nfor (int i = 0; i < n && ready; i++) {\n    run("<b>// x</b>"); // step\n}\n'
    fragment = BeautifulSoup(render_code_block(snippet), "html.parser")

    code = fragment.select_one('pre[dir="ltr"] > code')
    assert code is not None
    assert code.get_text() == snippet
    assert code.find("b") is None
    colors = {span.get_text(): span["style"] for span in code.select("span")}
    assert colors["int"] == "color:#93c5fd"
    assert colors["0"] == "color:#fcd34d"
    assert colors['"<b>// x</b>"'] == "color:#86efac"
    assert colors["// step"] == "color:#cbd5e1"


def test_csharp_has_a_language_specific_keyword_and_label():
    html = render_code_block("foreach (var item in items)", "csharp")
    fragment = BeautifulSoup(html, "html.parser")

    label = fragment.select_one("div[dir=ltr]")
    keyword = fragment.select_one("code span")
    assert label is not None and label.get_text() == "C#"
    assert keyword is not None and keyword.get_text() == "foreach"


def test_unknown_language_remains_plain_code_with_an_escaped_label():
    fragment = BeautifulSoup(render_code_block("let x = 1 < 2", "<language>"), "html.parser")

    label = fragment.select_one("div[dir=ltr]")
    code = fragment.select_one("pre code")
    assert label is not None and label.get_text() == "<language>"
    assert code is not None and code.get_text() == "let x = 1 < 2"
    assert fragment.select_one("code span") is None
