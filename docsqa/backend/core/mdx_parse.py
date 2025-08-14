import re
import frontmatter
from markdown import Markdown
from markdown.extensions import codehilite, tables, toc
from bs4 import BeautifulSoup
from typing import Dict, List, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class MDXElement:
    def __init__(self, type: str, content: str, line_start: int, line_end: int, 
                 attributes: Dict[str, Any] = None):
        self.type = type
        self.content = content
        self.line_start = line_start
        self.line_end = line_end
        self.attributes = attributes or {}


class MDXDocument:
    def __init__(self, filepath: str, content: str):
        self.filepath = filepath
        self.raw_content = content
        self.frontmatter_data = {}
        self.body_content = ""
        self.elements: List[MDXElement] = []
        self.headings: List[MDXElement] = []
        self.links: List[MDXElement] = []
        self.images: List[MDXElement] = []
        self.code_blocks: List[MDXElement] = []
        self.inline_code: List[MDXElement] = []
        
        self._parse()
    
    def _parse(self):
        """Parse the MDX document into structured elements"""
        try:
            # Parse frontmatter
            post = frontmatter.loads(self.raw_content)
            self.frontmatter_data = post.metadata
            self.body_content = post.content
            
            # Parse body content
            self._parse_body()
            
        except Exception as e:
            logger.error(f"Error parsing MDX document {self.filepath}: {e}")
            # Fallback: treat entire content as body
            self.body_content = self.raw_content
            self._parse_body()
    
    def _parse_body(self):
        """Parse the body content into structured elements"""
        lines = self.body_content.split('\n')
        
        # Track current position
        current_line = 1
        in_code_block = False
        code_block_start = 0
        code_block_content = []
        code_block_language = ""
        
        for i, line in enumerate(lines, 1):
            line_num = current_line + i - 1
            
            # Handle code blocks
            if line.strip().startswith('```'):
                if not in_code_block:
                    # Starting a code block
                    in_code_block = True
                    code_block_start = line_num
                    code_block_content = []
                    # Extract language if present
                    language_match = re.match(r'^```(\w+)?', line.strip())
                    code_block_language = language_match.group(1) if language_match and language_match.group(1) else ""
                else:
                    # Ending a code block
                    in_code_block = False
                    self.code_blocks.append(MDXElement(
                        type="code_block",
                        content='\n'.join(code_block_content),
                        line_start=code_block_start,
                        line_end=line_num,
                        attributes={"language": code_block_language}
                    ))
                continue
            
            if in_code_block:
                code_block_content.append(line)
                continue
            
            # Parse headings
            heading_match = re.match(r'^(#+)\s+(.*)', line.strip())
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                self.headings.append(MDXElement(
                    type="heading",
                    content=text,
                    line_start=line_num,
                    line_end=line_num,
                    attributes={"level": level}
                ))
                continue
            
            # Parse links
            link_matches = re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', line)
            for match in link_matches:
                text = match.group(1)
                url = match.group(2)
                self.links.append(MDXElement(
                    type="link",
                    content=text,
                    line_start=line_num,
                    line_end=line_num,
                    attributes={"url": url, "text": text}
                ))
            
            # Parse images
            image_matches = re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', line)
            for match in image_matches:
                alt_text = match.group(1)
                url = match.group(2)
                self.images.append(MDXElement(
                    type="image",
                    content=alt_text,
                    line_start=line_num,
                    line_end=line_num,
                    attributes={"url": url, "alt": alt_text}
                ))
            
            # Parse inline code
            inline_code_matches = re.finditer(r'`([^`]+)`', line)
            for match in inline_code_matches:
                code_content = match.group(1)
                self.inline_code.append(MDXElement(
                    type="inline_code",
                    content=code_content,
                    line_start=line_num,
                    line_end=line_num,
                    attributes={}
                ))
        
        # Add all lines as paragraph elements (simplified)
        self._parse_paragraphs(lines)
    
    def _parse_paragraphs(self, lines: List[str]):
        """Parse paragraph content"""
        current_paragraph = []
        paragraph_start = 1
        
        for i, line in enumerate(lines, 1):
            if line.strip() == "":
                if current_paragraph:
                    # End current paragraph
                    self.elements.append(MDXElement(
                        type="paragraph",
                        content='\n'.join(current_paragraph),
                        line_start=paragraph_start,
                        line_end=i - 1,
                        attributes={}
                    ))
                    current_paragraph = []
                paragraph_start = i + 1
            elif not line.strip().startswith('#') and not line.strip().startswith('```'):
                # Add to current paragraph (skip headings and code blocks)
                current_paragraph.append(line)
        
        # Don't forget the last paragraph
        if current_paragraph:
            self.elements.append(MDXElement(
                type="paragraph",
                content='\n'.join(current_paragraph),
                line_start=paragraph_start,
                line_end=len(lines),
                attributes={}
            ))
    
    def get_title(self) -> Optional[str]:
        """Get document title from frontmatter or first H1"""
        # Try frontmatter first
        if 'title' in self.frontmatter_data:
            return self.frontmatter_data['title']
        
        # Try first H1 heading
        for heading in self.headings:
            if heading.attributes.get('level') == 1:
                return heading.content
        
        return None
    
    def get_language(self) -> str:
        """Get document language from frontmatter"""
        return self.frontmatter_data.get('lang', 'en')
    
    def get_headings_tree(self) -> List[Dict[str, Any]]:
        """Get headings organized as a tree structure"""
        tree = []
        stack = []
        
        for heading in self.headings:
            level = heading.attributes['level']
            node = {
                'text': heading.content,
                'level': level,
                'line': heading.line_start,
                'children': []
            }
            
            # Find the right parent level
            while stack and stack[-1]['level'] >= level:
                stack.pop()
            
            if stack:
                stack[-1]['children'].append(node)
            else:
                tree.append(node)
            
            stack.append(node)
        
        return tree
    
    def extract_code_symbols(self) -> List[Dict[str, Any]]:
        """Extract code symbols like function calls, imports, etc."""
        symbols = []
        
        for code_block in self.code_blocks:
            language = code_block.attributes.get('language', '')
            content = code_block.content
            
            # Extract Python-like patterns (wandb.* calls)
            if language in ['python', 'py', ''] or 'wandb' in content:
                wandb_calls = re.finditer(r'wandb\.(\w+)', content)
                for match in wandb_calls:
                    symbols.append({
                        'type': 'api_call',
                        'symbol': match.group(0),
                        'method': match.group(1),
                        'line': code_block.line_start,
                        'language': language
                    })
            
            # Extract CLI commands
            if 'wandb ' in content:
                cli_calls = re.finditer(r'wandb\s+(\w+)', content)
                for match in cli_calls:
                    symbols.append({
                        'type': 'cli_command',
                        'symbol': match.group(0),
                        'command': match.group(1),
                        'line': code_block.line_start,
                        'language': language
                    })
        
        # Also check inline code
        for inline in self.inline_code:
            content = inline.content
            if 'wandb.' in content:
                symbols.append({
                    'type': 'inline_api',
                    'symbol': content,
                    'line': inline.line_start,
                    'language': 'inline'
                })
        
        return symbols
    
    def to_rendered_text(self, exclude_code_blocks: bool = True) -> str:
        """Convert to rendered text for LLM processing"""
        lines = self.body_content.split('\n')
        rendered_lines = []
        
        in_code_block = False
        for line in lines:
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                if exclude_code_blocks:
                    if not in_code_block:
                        rendered_lines.append("[CODE BLOCK END]")
                    else:
                        # Extract language info
                        lang_match = re.match(r'^```(\w+)?', line.strip())
                        lang = lang_match.group(1) if lang_match and lang_match.group(1) else "unknown"
                        rendered_lines.append(f"[CODE BLOCK: {lang}]")
                    continue
            
            if in_code_block and exclude_code_blocks:
                continue
            
            rendered_lines.append(line)
        
        return '\n'.join(rendered_lines)


def parse_mdx_file(filepath: str, content: str) -> MDXDocument:
    """Parse an MDX file and return structured document"""
    return MDXDocument(filepath, content)