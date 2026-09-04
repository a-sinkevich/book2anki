from book2anki.html_text import html_to_text


class TestSentencesStayWhole:
    """`get_text(separator="\\n")` broke a line at every inline tag; this must not."""

    def test_inline_emphasis_does_not_split_a_sentence(self):
        html = (b"<p>The difference is that Avro is friendlier to "
                b"<em>dynamically generated</em> schemas.</p>")

        assert html_to_text(html) == (
            "The difference is that Avro is friendlier to "
            "<em>dynamically generated</em> schemas."
        )

    def test_inline_code_and_links_stay_in_the_sentence(self):
        html = b'<p>Call <code>db_set</code> from <a href="#x">the shell</a> now.</p>'

        assert html_to_text(html) == "Call db_set from the shell now."

    def test_blocks_are_separated_by_a_blank_line(self):
        html = b"<p>First para.</p><p>Second para.</p>"

        assert html_to_text(html) == "First para.\n\nSecond para."

    def test_br_breaks_a_single_line(self):
        assert html_to_text(b"<p>One<br/>Two</p>") == "One\nTwo"


class TestPreformatted:
    def test_code_listing_keeps_its_line_breaks_and_indentation(self):
        html = (b"<pre><code>db_set () {\n"
                b'    echo "$1,$2" &gt;&gt; database\n'
                b"}</code></pre>")

        assert html_to_text(html) == (
            'db_set () {\n    echo "$1,$2" >> database\n}'
        )

    def test_emphasis_inside_pre_is_not_marked(self):
        """Syntax highlighting is not the author stressing a word."""
        html = b"<pre><code>x = <em>1</em></code></pre>"

        assert html_to_text(html) == "x = 1"


class TestEmphasis:
    def test_italic_and_em_both_become_em(self):
        assert html_to_text(b"<p><i>a</i> and <em>b</em></p>") == "<em>a</em> and <em>b</em>"

    def test_bold_and_strong_both_become_strong(self):
        html = b"<p><b>a</b> and <strong>b</strong></p>"

        assert html_to_text(html) == "<strong>a</strong> and <strong>b</strong>"

    def test_a_whole_italic_paragraph_is_not_marked(self):
        """Epigraphs and block quotes are typography, not a pointer at a phrase."""
        long_quote = b"word " * 40

        assert "<em>" not in html_to_text(b"<p><em>" + long_quote + b"</em></p>")

    def test_empty_emphasis_is_dropped(self):
        assert html_to_text(b"<p>a<em>  </em>b</p>") == "a b"


class TestNoise:
    def test_scripts_and_styles_are_dropped(self):
        html = b"<div><script>evil()</script><style>p{}</style><p>Real.</p></div>"

        assert html_to_text(html) == "Real."

    def test_comments_are_dropped(self):
        assert html_to_text(b"<p>a<!-- note -->b</p>") == "ab"

    def test_blank_lines_are_collapsed(self):
        html = b"<div><div><div><p>a</p></div></div><p>b</p></div>"

        assert html_to_text(html) == "a\n\nb"

    def test_empty_input(self):
        assert html_to_text(b"") == ""
