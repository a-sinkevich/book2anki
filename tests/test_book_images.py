"""Tests for book image extraction and processing."""
from bs4 import BeautifulSoup

from book2anki.models import BookImage, Card
from book2anki.parser_epub import _extract_image_caption, _extract_images_from_html
from book2anki.prompts import build_prompt, _format_figures_section
from book2anki.diagram_gen import process_book_images, _BOOK_IMG_RE


# --- Caption extraction ---


def _make_soup_img(html: str):
    """Parse HTML and return the first <img> tag."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("img")


class TestExtractImageCaption:
    def test_figcaption(self):
        html = '<figure><img src="x.jpg"/><figcaption>Brain anatomy</figcaption></figure>'
        assert _extract_image_caption(_make_soup_img(html)) == "Brain anatomy"

    def test_caption_sibling_inside_container(self):
        """PodRis-style: caption <p> is sibling of <img> inside same div."""
        html = (
            '<div class="full_img">'
            '<img src="x.jpg"/>'
            '<p class="PodRis">Рис. 2.1. Схема мозга человека</p>'
            '</div>'
        )
        assert "Рис. 2.1" in _extract_image_caption(_make_soup_img(html))
        assert "Схема мозга" in _extract_image_caption(_make_soup_img(html))

    def test_caption_sibling_multiline(self):
        """Multi-paragraph caption: PodRis + PodRis-2 continuation."""
        html = (
            '<div class="full_img">'
            '<img src="x.jpg"/>'
            '<p class="PodRis">Рис. 3.1. Main caption text</p>'
            '<p class="PodRis-2">Additional details here</p>'
            '</div>'
        )
        caption = _extract_image_caption(_make_soup_img(html))
        assert "Рис. 3.1" in caption
        assert "Additional details" in caption

    def test_caption_sibling_stops_at_next_figure(self):
        """Multi-paragraph caption stops when next Рис. starts."""
        html = (
            '<div>'
            '<img src="x.jpg"/>'
            '<p>Рис. 1.1. First figure</p>'
            '<p>Continuation</p>'
            '<p>Рис. 1.2. Second figure</p>'
            '</div>'
        )
        caption = _extract_image_caption(_make_soup_img(html))
        assert "First figure" in caption
        assert "Continuation" in caption
        assert "Second figure" not in caption

    def test_caption_parent_sibling_figure_prefix(self):
        """Caption as next sibling of parent div."""
        html = (
            '<div><div class="img"><img src="x.jpg"/></div>'
            '<p>Figure 3. Dopamine pathways</p></div>'
        )
        img = _make_soup_img(html)
        caption = _extract_image_caption(img)
        assert "Dopamine pathways" in caption

    def test_fallback_to_surrounding_paragraphs(self):
        """When no formal caption, use before + after paragraphs."""
        html = (
            '<p>The hypothalamus controls hunger and satiety.</p>'
            '<div class="img"><img src="x.jpg"/></div>'
            '<p>Neurons in this region respond to glucose levels.</p>'
        )
        img = _make_soup_img(html)
        caption = _extract_image_caption(img)
        assert "hypothalamus" in caption
        assert "glucose" in caption
        assert " | " in caption

    def test_fallback_truncates_long_text(self):
        """Long paragraphs are truncated in fallback mode."""
        long_text = "Word " * 100  # 500 chars
        html = (
            f'<p>{long_text}</p>'
            '<div class="img"><img src="x.jpg"/></div>'
            '<p>Short after.</p>'
        )
        img = _make_soup_img(html)
        caption = _extract_image_caption(img)
        assert "…" in caption

    def test_empty_alt_ignored(self):
        html = '<div><img src="x.jpg" alt=""/></div>'
        caption = _extract_image_caption(_make_soup_img(html))
        assert caption == ""

    def test_generic_alt_ignored(self):
        html = '<div><img src="x.jpg" alt="cover"/></div>'
        caption = _extract_image_caption(_make_soup_img(html))
        assert caption == ""

    def test_meaningful_alt_used(self):
        html = '<div><img src="x.jpg" alt="Brain cross-section diagram"/></div>'
        caption = _extract_image_caption(_make_soup_img(html))
        assert caption == "Brain cross-section diagram"

    def test_russian_figure_prefix(self):
        html = (
            '<div class="full_img">'
            '<img src="x.jpg"/>'
            '<p>Рис. 5.2. Нейроэндокринная дуга</p>'
            '</div>'
        )
        caption = _extract_image_caption(_make_soup_img(html))
        assert "Рис. 5.2" in caption

    def test_figure_prefix_case_insensitive(self):
        html = (
            '<div class="full_img">'
            '<img src="x.jpg"/>'
            '<p>FIGURE 1. Important diagram</p>'
            '</div>'
        )
        caption = _extract_image_caption(_make_soup_img(html))
        assert "Important diagram" in caption


# --- Image extraction from HTML ---


def _make_image_map(name: str = "Images/1.jpg", data: bytes = b"x" * 6000,
                    media_type: str = "image/jpeg"):
    """Create a fake image map for testing."""
    class FakeItem:
        def __init__(self, n, d, mt):
            self._name = n
            self._data = d
            self.media_type = mt

        def get_name(self):
            return self._name

        def get_content(self):
            return self._data

    item = FakeItem(name, data, media_type)
    return {name: item, "1.jpg": item}


class TestExtractImagesFromHtml:
    def test_extracts_image_with_caption(self):
        html = (
            '<div class="full_img">'
            '<img src="../Images/1.jpg"/>'
            '<p>Fig. 1.1. Test caption</p>'
            '</div>'
        ).encode()
        image_map = _make_image_map()
        images = _extract_images_from_html(html, "Text/ch1.html", image_map)
        assert len(images) == 1
        assert images[0].id == "book-img-1"
        assert "Fig. 1.1" in images[0].caption
        assert images[0].ext == "jpg"

    def test_skips_small_images(self):
        """Images < 5KB are filtered out."""
        html = (
            '<div><img src="../Images/1.jpg"/>'
            '<p>Fig. 1.1. Caption</p></div>'
        ).encode()
        image_map = _make_image_map(data=b"x" * 100)  # tiny
        images = _extract_images_from_html(html, "Text/ch1.html", image_map)
        assert len(images) == 0

    def test_skips_images_without_caption(self):
        """Images without any caption context are filtered out."""
        html = b'<div><img src="../Images/1.jpg"/></div>'
        image_map = _make_image_map()
        images = _extract_images_from_html(html, "Text/ch1.html", image_map)
        assert len(images) == 0

    def test_skips_missing_images(self):
        html = (
            '<img src="../Images/missing.jpg"/>'
            '<p>Fig. 1.1. Caption</p>'
        ).encode()
        image_map = _make_image_map()  # only has 1.jpg
        images = _extract_images_from_html(html, "Text/ch1.html", image_map)
        assert len(images) == 0

    def test_deduplicates_same_image(self):
        html = (
            '<div><img src="../Images/1.jpg"/><p>Fig. 1. First</p></div>'
            '<div><img src="../Images/1.jpg"/><p>Fig. 2. Second</p></div>'
        ).encode()
        image_map = _make_image_map()
        images = _extract_images_from_html(html, "Text/ch1.html", image_map)
        assert len(images) == 1


# --- Book image reference pattern ---


class TestBookImgPattern:
    def test_matches_uppercase(self):
        assert _BOOK_IMG_RE.match("[BOOK-IMG-1]")
        assert _BOOK_IMG_RE.match("[BOOK-IMG-12]")

    def test_matches_lowercase(self):
        assert _BOOK_IMG_RE.match("[book-img-3]")

    def test_no_match_text(self):
        assert not _BOOK_IMG_RE.match("some diagram prompt text")

    def test_matches_with_caption(self):
        m = _BOOK_IMG_RE.match("[BOOK-IMG-1] translated caption")
        assert m and m.group(1) == "1"
        assert m.group(2) == "translated caption"

    def test_extracts_number(self):
        m = _BOOK_IMG_RE.match("[BOOK-IMG-7]")
        assert m and m.group(1) == "7"
        assert m.group(2) == ""


# --- Process book images ---


def _make_book_image(num: int, data: bytes = b"PNG_DATA") -> BookImage:
    return BookImage(
        id=f"book-img-{num}",
        data=data,
        ext="png",
        caption=f"Figure {num} caption",
    )


class TestProcessBookImages:
    def test_replaces_reference_with_img_tag(self, tmp_path):
        images = [_make_book_image(1)]
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="[BOOK-IMG-1]",
        )
        media = process_book_images([card], images, str(tmp_path))
        assert card.image.startswith('<img src="')
        assert len(media) == 1
        assert (tmp_path / media[0].split("/")[-1]).read_bytes() == b"PNG_DATA"

    def test_clears_invalid_reference(self, tmp_path):
        images = [_make_book_image(1)]
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="[BOOK-IMG-99]",  # doesn't exist
        )
        process_book_images([card], images, str(tmp_path))
        assert card.image == ""

    def test_ignores_non_reference_images(self, tmp_path):
        images = [_make_book_image(1)]
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="some random text",
        )
        process_book_images([card], images, str(tmp_path))
        assert card.image == "some random text"

    def test_ignores_empty_diagrams(self, tmp_path):
        images = [_make_book_image(1)]
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="",
        )
        process_book_images([card], images, str(tmp_path))
        assert card.image == ""

    def test_no_images_returns_empty(self, tmp_path):
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="[BOOK-IMG-1]",
        )
        media = process_book_images([card], [], str(tmp_path))
        assert media == []

    def test_deduplicates_media_files(self, tmp_path):
        images = [_make_book_image(1)]
        cards = [
            Card(question="Q1", answer="A", chapter_title="Ch",
                 book_title="B", image="[BOOK-IMG-1]"),
            Card(question="Q2", answer="A", chapter_title="Ch",
                 book_title="B", image="[BOOK-IMG-1]"),
        ]
        media = process_book_images(cards, images, str(tmp_path))
        assert len(media) == 1  # same image, one file

    def test_case_insensitive_reference(self, tmp_path):
        images = [_make_book_image(1)]
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="[book-img-1]",
        )
        process_book_images([card], images, str(tmp_path))
        assert card.image.startswith('<img src="')

    def test_includes_caption(self, tmp_path):
        images = [_make_book_image(1)]
        card = Card(
            question="Q", answer="A",
            chapter_title="Ch", book_title="B",
            image="[BOOK-IMG-1]",
        )
        process_book_images([card], images, str(tmp_path))
        assert "Figure 1 caption" in card.image
        assert "image-caption" in card.image


# --- Prompt integration ---


class TestFormatFiguresSection:
    def test_no_captions(self):
        assert _format_figures_section(None) == ""
        assert _format_figures_section([]) == ""

    def test_formats_captions(self):
        captions = [
            ("book-img-1", "Рис. 1.1. Brain diagram"),
            ("book-img-2", "Рис. 1.2. Neuron structure"),
        ]
        result = _format_figures_section(captions)
        assert "[BOOK-IMG-1]" in result
        assert "[BOOK-IMG-2]" in result
        assert "Brain diagram" in result
        assert "Neuron structure" in result


class TestBuildPromptWithBookImages:
    def test_no_diagrams_no_images(self):
        prompt = build_prompt("Book", "Ch", "text", 1, "en")
        assert "image" not in prompt.lower() or '"image"' not in prompt

    def test_book_images_without_diagrams_flag(self):
        """Book images add image field to prompt."""
        captions = [("book-img-1", "Figure 1")]
        prompt = build_prompt(
            "Book", "Ch", "text", 1, "en",
            book_image_captions=captions,
        )
        assert "[BOOK-IMG-1]" in prompt
        assert '"image"' in prompt

    def test_no_book_images_no_image_field(self):
        """Without book images, no image field in prompt."""
        prompt = build_prompt("Book", "Ch", "text", 1, "en")
        assert "BOOK-IMG" not in prompt
