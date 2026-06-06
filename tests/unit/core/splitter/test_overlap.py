from src.core.splitter import ChunkOverlapConfig, ChunkOverlapper


class MockWordTokenizer:
    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])

    def truncate_text(self, text: str, max_tokens: int):
        words = [part for part in text.split() if part]
        if len(words) <= max_tokens:
            return " ".join(words), 0
        return " ".join(words[:max_tokens]), len(words) - max_tokens


def test_overlapper_should_apply_64_token_upper_bound():
    overlapper = ChunkOverlapper(
        tokenizer=MockWordTokenizer(),
        config=ChunkOverlapConfig(enabled=True, tokens=64),
    )
    previous_chunk = " ".join(f"p{i}" for i in range(70))
    next_atom = " ".join(f"n{i}" for i in range(10))

    result = overlapper.build_next_chunk(
        previous_chunk,
        next_atom,
        max_chunk_tokens=100,
    )

    overlap_text, next_text = result.split("\n\n")
    assert overlap_text == " ".join(f"p{i}" for i in range(6, 70))
    assert next_text == next_atom
    assert overlapper.count_tokens(overlap_text) == 64
