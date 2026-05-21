"""Text chunking strategies."""

import re
from typing import List


class RecursiveCharacterTextSplitter:
    """Recursively split text by separators, trying each in order."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100,
                 separators: List[str] = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", "。", "！", "？", ". ", " ", ""]

    def split_text(self, text: str) -> List[str]:
        return self._split_text(text, self.separators)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        separator = separators[0] if separators else ""
        next_separators = separators[1:] if len(separators) > 1 else []

        splits = text.split(separator) if separator else list(text)

        final_chunks = []
        current = ""
        for s in splits:
            s = s.strip()
            if not s:
                continue
            if separator:
                candidate = current + separator + s if current else s
            else:
                candidate = current + s

            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    final_chunks.append(current.strip())
                    # overlap
                    overlap_start = max(0, len(current) - self.chunk_overlap)
                    current = current[overlap_start:] + (separator if separator else "") + s
                    if len(current) > self.chunk_size:
                        # Still too big, recurse
                        if next_separators:
                            final_chunks.extend(self._split_text(current, next_separators))
                        else:
                            final_chunks.extend(self._fixed_split(current))
                        current = ""
                else:
                    # Single chunk too big
                    if next_separators:
                        final_chunks.extend(self._split_text(s, next_separators))
                    else:
                        final_chunks.extend(self._fixed_split(s))

        if current:
            if len(current) > self.chunk_size and next_separators:
                final_chunks.extend(self._split_text(current, next_separators))
            else:
                final_chunks.append(current.strip())

        return final_chunks

    def _fixed_split(self, text: str) -> List[str]:
        """Force split by fixed size when no separator works."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end].strip())
            start += self.chunk_size - self.chunk_overlap
        return chunks


class FixedSizeSplitter:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> List[str]:
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start += self.chunk_size - self.chunk_overlap
        return chunks


class ParagraphSplitter:
    def __init__(self, min_length: int = 50):
        self.min_length = min_length

    def split_text(self, text: str) -> List[str]:
        paragraphs = re.split(r'\n\s*\n', text)
        result = []
        buffer = ""
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            if len(p) < self.min_length:
                buffer += "\n" + p
            else:
                if buffer:
                    p = buffer + "\n" + p
                    buffer = ""
                result.append(p)
        if buffer:
            if result:
                result[-1] += "\n" + buffer
            else:
                result.append(buffer)
        return result


def get_splitter(method: str = "recursive", **kwargs):
    if method == "recursive":
        return RecursiveCharacterTextSplitter(**kwargs)
    elif method == "fixed":
        return FixedSizeSplitter(**kwargs)
    elif method == "paragraph":
        return ParagraphSplitter(**kwargs)
    else:
        raise ValueError(f"Unknown method: {method}")
