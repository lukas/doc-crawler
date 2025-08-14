"""Tests for MDX parsing functionality"""

import pytest

from docsqa.backend.core.mdx_parse import parse_mdx_file, MDXDocument


def test_parse_simple_markdown():
    """Test parsing simple markdown content"""
    content = """# Test Document

This is a test document with some content.

## Section 1

Some content here.

## Section 2  

More content here.
"""
    
    doc = parse_mdx_file("test.md", content)
    
    assert isinstance(doc, MDXDocument)
    assert doc.filepath == "test.md"
    assert doc.get_title() == "Test Document"
    assert len(doc.headings) >= 2
    
    # Check headings
    section1 = next((h for h in doc.headings if h.content == "Section 1"), None)
    assert section1 is not None
    
    section2 = next((h for h in doc.headings if h.content == "Section 2"), None) 
    assert section2 is not None


def test_parse_frontmatter():
    """Test parsing markdown with frontmatter"""
    content = """---
title: Custom Title
author: Test Author
tags: [test, markdown]
---

# Main Heading

Content goes here.
"""
    
    doc = parse_mdx_file("test.md", content)
    
    assert doc.get_title() == "Custom Title"  # Should use frontmatter title
    assert doc.frontmatter_data["author"] == "Test Author"
    assert doc.frontmatter_data["tags"] == ["test", "markdown"]


def test_parse_code_blocks():
    """Test parsing markdown with code blocks"""
    content = """# Code Examples

Here's some Python code:

```python
def hello():
    print("Hello, world!")
```

And some JavaScript:

```javascript
function hello() {
    console.log("Hello, world!");
}
```
"""
    
    doc = parse_mdx_file("test.md", content)
    
    # Code blocks should be parsed and available
    assert len(doc.code_blocks) >= 2
    
    python_block = next((cb for cb in doc.code_blocks if cb.attributes.get("language") == "python"), None)
    assert python_block is not None
    assert "def hello():" in python_block.content
    
    js_block = next((cb for cb in doc.code_blocks if cb.attributes.get("language") == "javascript"), None) 
    assert js_block is not None
    assert "function hello()" in js_block.content


def test_parse_links():
    """Test parsing markdown with links"""
    content = """# Links Test

Here are some links:

- [Internal link](/docs/guide)
- [External link](https://example.com)
"""
    
    doc = parse_mdx_file("test.md", content)
    
    assert len(doc.links) >= 2
    
    # Check for different link types  
    internal_link = next((l for l in doc.links if l.attributes.get("url") == "/docs/guide"), None)
    assert internal_link is not None
    assert internal_link.content == "Internal link"
    
    external_link = next((l for l in doc.links if l.attributes.get("url") == "https://example.com"), None)
    assert external_link is not None  
    assert external_link.content == "External link"


def test_parse_empty_document():
    """Test parsing empty document"""
    doc = parse_mdx_file("empty.md", "")
    
    assert doc.filepath == "empty.md"
    assert doc.get_title() is None
    assert doc.body_content == ""
    assert len(doc.headings) == 0
    assert len(doc.links) == 0


def test_parse_headings_hierarchy():
    """Test parsing documents with heading hierarchy"""
    content = """# Main Title

## Level 2 Heading

### Level 3 Heading

Content under level 3.

### Another Level 3

More content.

## Another Level 2

Final content.
"""
    
    doc = parse_mdx_file("test.md", content)
    
    assert doc.get_title() == "Main Title"
    assert len(doc.headings) >= 5  # At least 5 headings including title
    
    # Check heading hierarchy
    level2_headings = [h for h in doc.headings if h.attributes.get("level") == 2]
    level3_headings = [h for h in doc.headings if h.attributes.get("level") == 3]
    
    assert len(level2_headings) >= 2
    assert len(level3_headings) >= 2