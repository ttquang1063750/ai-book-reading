from app.models.book_structure import Block
from app.pipeline.chunking import build_chunks, estimate_tokens


def make_block(id_: int, type_: str = "paragraph", text: str = "", page: int = 1) -> Block:
    return Block(id=id_, page=page, type=type_, text=text, order_key=id_)


def test_all_blocks_kept_in_order():
    blocks = [make_block(i, text=f"para {i} " + "x" * 100) for i in range(20)]
    chunks = build_chunks(blocks, token_budget=100)
    flat = [b.id for c in chunks for b in c.blocks]
    assert flat == list(range(20))


def test_budget_respected_at_paragraph_boundaries():
    blocks = [make_block(i, text="word " * 80) for i in range(10)]  # ~100 tokens each
    chunks = build_chunks(blocks, token_budget=250)
    for chunk in chunks:
        assert len(chunk.text_blocks) <= 3
        assert all(b.type == "paragraph" for b in chunk.text_blocks)
    assert len(chunks) >= 4


def test_oversized_block_gets_own_chunk():
    blocks = [
        make_block(0, text="short one"),
        make_block(1, text="y" * 5000),  # way over budget
        make_block(2, text="short two"),
    ]
    chunks = build_chunks(blocks, token_budget=100)
    assert len(chunks) == 3
    assert [b.id for b in chunks[1].blocks] == [1]


def test_page_breaks_attached_not_counted():
    blocks = [
        make_block(0, text="a" * 400, page=1),
        make_block(1, type_="page_break", page=2),
        make_block(2, text="b" * 400, page=2),
    ]
    chunks = build_chunks(blocks, token_budget=120)
    assert len(chunks) == 2
    # page_break travels with the chunk that was open when it appeared
    assert [b.id for b in chunks[0].blocks] == [0, 1]
    assert [b.id for b in chunks[1].blocks] == [2]


def test_trailing_page_break_appended_to_last_chunk():
    blocks = [
        make_block(0, text="a" * 400),
        make_block(1, text="b" * 400),
        make_block(2, type_="page_break", page=2),
    ]
    chunks = build_chunks(blocks, token_budget=120)
    flat = [b.id for c in chunks for b in c.blocks]
    assert flat == [0, 1, 2]


def test_source_text_joins_with_blank_lines():
    blocks = [make_block(0, text="First."), make_block(1, text="Second.")]
    chunks = build_chunks(blocks, token_budget=1000)
    assert len(chunks) == 1
    assert chunks[0].source_text == "First.\n\nSecond."


def test_estimate_tokens_rough():
    assert estimate_tokens("x" * 400) == 101
