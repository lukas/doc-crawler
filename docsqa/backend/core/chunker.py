import re
import tiktoken
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from .mdx_parse import MDXDocument, MDXElement

DEFAULT_CHUNK_SIZE = 2000  # tokens
DEFAULT_CHUNK_OVERLAP = 200  # tokens


@dataclass
class DocumentChunk:
    chunk_id: str
    file_path: str
    content: str
    rendered_text: str  # Text for LLM processing
    start_line: int
    end_line: int
    heading_context: List[str]  # Hierarchical headings
    token_count: int
    metadata: Dict[str, Any]


class DocumentChunker:
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE, 
                 overlap_size: int = DEFAULT_CHUNK_OVERLAP,
                 model_name: str = "gpt-4"):
        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        
        # Initialize tokenizer
        try:
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # Fallback to a common encoding
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        return len(self.encoding.encode(text))
    
    def chunk_document(self, doc: MDXDocument) -> List[DocumentChunk]:
        """Chunk a document by heading boundaries while respecting token limits"""
        chunks = []
        
        # If document is small, return as single chunk
        full_text = doc.to_rendered_text()
        total_tokens = self.count_tokens(full_text)
        
        if total_tokens <= self.chunk_size:
            chunk = DocumentChunk(
                chunk_id=f"{doc.filepath}_chunk_0",
                file_path=doc.filepath,
                content=doc.body_content,
                rendered_text=full_text,
                start_line=1,
                end_line=len(doc.body_content.split('\n')),
                heading_context=self._get_document_heading_context(doc),
                token_count=total_tokens,
                metadata={
                    'is_complete_document': True,
                    'total_headings': len(doc.headings),
                    'total_links': len(doc.links),
                    'total_code_blocks': len(doc.code_blocks)
                }
            )
            return [chunk]
        
        # Chunk by heading boundaries
        return self._chunk_by_headings(doc)
    
    def _chunk_by_headings(self, doc: MDXDocument) -> List[DocumentChunk]:
        """Chunk document using heading structure as boundaries"""
        chunks = []
        lines = doc.body_content.split('\n')
        
        # Get heading positions
        heading_positions = []
        for heading in doc.headings:
            heading_positions.append({
                'line': heading.line_start,
                'level': heading.attributes['level'],
                'text': heading.content
            })
        
        # Sort by line number
        heading_positions.sort(key=lambda x: x['line'])
        
        # Add document start and end markers
        section_boundaries = [{'line': 1, 'level': 0, 'text': 'Document Start'}]
        section_boundaries.extend(heading_positions)
        section_boundaries.append({'line': len(lines) + 1, 'level': 0, 'text': 'Document End'})
        
        chunk_idx = 0
        current_section_start = 0
        
        for i in range(len(section_boundaries) - 1):
            current = section_boundaries[i]
            next_boundary = section_boundaries[i + 1]
            
            section_start_line = current['line']
            section_end_line = next_boundary['line'] - 1
            
            # Extract section content
            section_lines = lines[section_start_line - 1:section_end_line]
            section_content = '\n'.join(section_lines)
            
            if not section_content.strip():
                continue
            
            # Check if section fits in chunk size
            section_tokens = self.count_tokens(section_content)
            
            if section_tokens <= self.chunk_size:
                # Create chunk for this section
                heading_context = self._get_heading_context_for_line(doc, section_start_line)
                
                chunk = DocumentChunk(
                    chunk_id=f"{doc.filepath}_chunk_{chunk_idx}",
                    file_path=doc.filepath,
                    content=section_content,
                    rendered_text=self._render_section_for_llm(section_content),
                    start_line=section_start_line,
                    end_line=section_end_line,
                    heading_context=heading_context,
                    token_count=section_tokens,
                    metadata={
                        'section_heading': current['text'],
                        'heading_level': current['level'],
                        'is_complete_section': True
                    }
                )
                chunks.append(chunk)
                chunk_idx += 1
            else:
                # Section is too large, need to split further
                sub_chunks = self._split_large_section(
                    doc, section_content, section_start_line, section_end_line, chunk_idx
                )
                chunks.extend(sub_chunks)
                chunk_idx += len(sub_chunks)
        
        return chunks
    
    def _split_large_section(self, doc: MDXDocument, content: str, 
                           start_line: int, end_line: int, chunk_idx: int) -> List[DocumentChunk]:
        """Split a large section into smaller chunks"""
        chunks = []
        lines = content.split('\n')
        current_chunk_lines = []
        current_chunk_start = start_line
        current_tokens = 0
        
        for i, line in enumerate(lines):
            line_tokens = self.count_tokens(line)
            
            # If adding this line would exceed chunk size, finalize current chunk
            if current_tokens + line_tokens > self.chunk_size and current_chunk_lines:
                chunk_content = '\n'.join(current_chunk_lines)
                heading_context = self._get_heading_context_for_line(doc, current_chunk_start)
                
                chunk = DocumentChunk(
                    chunk_id=f"{doc.filepath}_chunk_{chunk_idx + len(chunks)}",
                    file_path=doc.filepath,
                    content=chunk_content,
                    rendered_text=self._render_section_for_llm(chunk_content),
                    start_line=current_chunk_start,
                    end_line=current_chunk_start + len(current_chunk_lines) - 1,
                    heading_context=heading_context,
                    token_count=current_tokens,
                    metadata={
                        'is_partial_section': True,
                        'split_reason': 'token_limit'
                    }
                )
                chunks.append(chunk)
                
                # Start new chunk with overlap
                overlap_lines = current_chunk_lines[-self.overlap_size // 50:]  # Rough estimate
                current_chunk_lines = overlap_lines + [line]
                current_chunk_start = current_chunk_start + len(current_chunk_lines) - len(overlap_lines) - 1
                current_tokens = sum(self.count_tokens(l) for l in current_chunk_lines)
            else:
                current_chunk_lines.append(line)
                current_tokens += line_tokens
        
        # Don't forget the last chunk
        if current_chunk_lines:
            chunk_content = '\n'.join(current_chunk_lines)
            heading_context = self._get_heading_context_for_line(doc, current_chunk_start)
            
            chunk = DocumentChunk(
                chunk_id=f"{doc.filepath}_chunk_{chunk_idx + len(chunks)}",
                file_path=doc.filepath,
                content=chunk_content,
                rendered_text=self._render_section_for_llm(chunk_content),
                start_line=current_chunk_start,
                end_line=end_line,
                heading_context=heading_context,
                token_count=current_tokens,
                metadata={
                    'is_partial_section': True,
                    'split_reason': 'token_limit'
                }
            )
            chunks.append(chunk)
        
        return chunks
    
    def _get_heading_context_for_line(self, doc: MDXDocument, line_num: int) -> List[str]:
        """Get hierarchical heading context for a specific line"""
        context = []
        heading_stack = []
        
        for heading in doc.headings:
            if heading.line_start > line_num:
                break
            
            level = heading.attributes['level']
            text = heading.content
            
            # Pop headings of same or higher level
            while heading_stack and heading_stack[-1]['level'] >= level:
                heading_stack.pop()
            
            heading_stack.append({'level': level, 'text': text})
        
        return [h['text'] for h in heading_stack]
    
    def _get_document_heading_context(self, doc: MDXDocument) -> List[str]:
        """Get overall document heading context"""
        title = doc.get_title()
        if title:
            return [title]
        elif doc.headings:
            return [doc.headings[0].content]
        else:
            return [f"Document: {doc.filepath}"]
    
    def _render_section_for_llm(self, content: str) -> str:
        """Render section content for LLM processing"""
        # Remove excessive whitespace
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Preserve code blocks and meaningful whitespace
            if line.strip().startswith('```') or line.strip().startswith('    '):
                cleaned_lines.append(line)
            else:
                cleaned_lines.append(line.strip())
        
        # Remove excessive blank lines
        result_lines = []
        prev_empty = False
        
        for line in cleaned_lines:
            if line == '':
                if not prev_empty:
                    result_lines.append(line)
                prev_empty = True
            else:
                result_lines.append(line)
                prev_empty = False
        
        return '\n'.join(result_lines)
    
    def get_chunk_context(self, chunk: DocumentChunk, doc: MDXDocument, 
                         context_lines: int = 150) -> str:
        """Get surrounding context for a chunk"""
        lines = doc.body_content.split('\n')
        
        # Get lines before and after the chunk
        start_context = max(0, chunk.start_line - context_lines - 1)
        end_context = min(len(lines), chunk.end_line + context_lines)
        
        context_lines_list = lines[start_context:chunk.start_line - 1] + \
                           lines[chunk.end_line:end_context]
        
        if context_lines_list:
            return '\n'.join(context_lines_list)
        else:
            return ""