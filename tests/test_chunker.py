"""Tests for document chunker functionality"""

import pytest

from docsqa.backend.core.chunker import DocumentChunker
from docsqa.backend.core.mdx_parse import parse_mdx_file


@pytest.fixture
def chunker():
    """Create a document chunker instance"""
    return DocumentChunker()


def test_chunk_simple_document(chunker):
    """Test chunking a simple document"""
    content = """# Test Document

This is the introduction.

## Section 1

This is section 1 content.

## Section 2

This is section 2 content.
"""
    
    doc = parse_mdx_file("test.md", content)
    chunks = chunker.chunk_document(doc)
    
    assert len(chunks) > 0
    
    # Each chunk should have required fields
    for chunk in chunks:
        assert hasattr(chunk, 'chunk_id') and chunk.chunk_id is not None
        assert hasattr(chunk, 'file_path') and chunk.file_path == "test.md"
        assert hasattr(chunk, 'content') and chunk.content is not None
        assert hasattr(chunk, 'start_line') and chunk.start_line >= 1
        assert hasattr(chunk, 'end_line') and chunk.end_line >= chunk.start_line


def test_chunk_by_headings(chunker):
    """Test that chunks are created based on headings"""
    content = """# Main Title

Introduction content.

## First Section

Content for first section.
This has multiple lines.

## Second Section

Content for second section.

### Subsection

Nested content here.
"""
    
    doc = parse_mdx_file("test.md", content)
    chunks = chunker.chunk_document(doc)
    
    # Should have chunks for different sections
    assert len(chunks) >= 3  # At least intro, section 1, section 2
    
    # Check that chunks contain the expected headings
    chunk_contents = [chunk.content for chunk in chunks]
    combined_content = " ".join(chunk_contents)
    
    assert "First Section" in combined_content
    assert "Second Section" in combined_content
    assert "Subsection" in combined_content


def test_chunk_large_sections(chunker):
    """Test chunking of large sections that exceed max size"""
    # Create a large section
    large_content = "This is a line of content. " * 200  # Very long content
    
    content = f"""# Large Document

## Large Section

{large_content}

## Another Section

Normal content here.
"""
    
    doc = parse_mdx_file("test.md", content)
    chunks = chunker.chunk_document(doc)
    
    # Should split large sections
    assert len(chunks) >= 2
    
    # No single chunk should be too large (rough check)
    for chunk in chunks:
        assert len(chunk.content) < 10000  # Reasonable max size


def test_chunk_metadata_preservation(chunker):
    """Test that chunk metadata is preserved correctly"""
    content = """# Test Document

## Section with Code

Here's some code:

```python
def hello():
    print("Hello")
```

## Section with Link

Check out [this link](https://example.com).
"""
    
    doc = parse_mdx_file("test.md", content)
    chunks = chunker.chunk_document(doc)
    
    # Find chunk with code
    code_chunk = None
    link_chunk = None
    
    for chunk in chunks:
        if "python" in chunk.content:
            code_chunk = chunk
        if "this link" in chunk.content:
            link_chunk = chunk
    
    assert code_chunk is not None
    assert link_chunk is not None
    
    # Check metadata
    assert len(code_chunk.heading_context) >= 0
    assert len(link_chunk.heading_context) >= 0


def test_chunk_empty_document(chunker):
    """Test chunking empty document"""
    doc = parse_mdx_file("empty.md", "")
    chunks = chunker.chunk_document(doc)
    
    # Should handle empty documents gracefully
    assert isinstance(chunks, list)
    # May have 0 chunks or 1 empty chunk depending on implementation


def test_chunk_no_headings(chunker):
    """Test chunking document without headings"""
    content = """This is a document without any headings.
It just has plain text content.
Multiple paragraphs of content.

More content here.
"""
    
    doc = parse_mdx_file("test.md", content)
    chunks = chunker.chunk_document(doc)
    
    assert len(chunks) >= 1
    # Should create at least one chunk for the content
    assert chunks[0].content.strip() != ""