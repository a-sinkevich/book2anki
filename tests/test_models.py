from book2anki.models import Card, Chapter


def test_card_creation():
    card = Card(question="Q", answer="A", chapter_title="Ch", book_title="Book")
    assert card.question == "Q"
    assert card.answer == "A"


def test_chapter_creation():
    ch = Chapter(title="Title", text="Content", index=0)
    assert ch.title == "Title"
    assert ch.index == 0
