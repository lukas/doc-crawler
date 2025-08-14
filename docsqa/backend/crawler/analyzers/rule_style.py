import re
import logging
from typing import List, Dict, Any, Optional, Set
from core.mdx_parse import MDXDocument
from core.schemas import IssueCreate, IssueSeverity
from core.patches import create_line_replacement_patch

logger = logging.getLogger(__name__)


class StyleAnalyzer:
    """Analyzer for style and terminology consistency"""
    
    def __init__(self, require_one_h1: bool = True, require_img_alt: bool = True,
                 canonical_terms: List[str] = None):
        self.require_one_h1 = require_one_h1
        self.require_img_alt = require_img_alt
        self.canonical_terms = canonical_terms or []
        
        # Parse canonical terms into patterns
        self.term_patterns = self._parse_canonical_terms(self.canonical_terms)
    
    def analyze_document(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Analyze style issues in a document"""
        issues = []
        
        try:
            # Check heading structure
            heading_issues = self._check_heading_structure(doc, file_id, run_id)
            issues.extend(heading_issues)
            
            # Check image alt text
            if self.require_img_alt:
                img_issues = self._check_image_alt_text(doc, file_id, run_id)
                issues.extend(img_issues)
            
            # Check terminology consistency
            term_issues = self._check_terminology(doc, file_id, run_id)
            issues.extend(term_issues)
            
        except Exception as e:
            logger.error(f"Error analyzing style in {doc.filepath}: {e}")
        
        return issues
    
    def _parse_canonical_terms(self, terms: List[str]) -> List[Dict[str, Any]]:
        """Parse canonical terms into searchable patterns"""
        patterns = []
        
        for term in terms:
            if '|' in term:
                # Multiple variants: "Weights & Biases|W&B"
                variants = [v.strip() for v in term.split('|')]
                canonical = variants[0]  # First is canonical
                alternatives = variants[1:]
                
                patterns.append({
                    'canonical': canonical,
                    'alternatives': alternatives,
                    'pattern': '|'.join(re.escape(alt) for alt in alternatives)
                })
            else:
                # Single canonical term
                patterns.append({
                    'canonical': term,
                    'alternatives': [],
                    'pattern': re.escape(term)
                })
        
        return patterns
    
    def _check_heading_structure(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Check heading structure rules"""
        issues = []
        
        if self.require_one_h1:
            h1_headings = [h for h in doc.headings if h.attributes.get('level') == 1]
            
            if len(h1_headings) == 0:
                issues.append(IssueCreate(
                    file_id=file_id,
                    rule_code="STYLE_NO_H1",
                    severity=IssueSeverity.MEDIUM,
                    title="Missing H1 heading",
                    description="Document should have exactly one H1 heading for proper structure.",
                    snippet="",
                    line_start=1,
                    line_end=1,
                    evidence={'h1_count': 0, 'total_headings': len(doc.headings)},
                    provenance=["rule"],
                    can_auto_apply=False,  # Adding H1 needs manual decision
                    first_seen_run_id=run_id,
                    last_seen_run_id=run_id
                ))
            elif len(h1_headings) > 1:
                for i, heading in enumerate(h1_headings[1:], 1):  # Skip first H1
                    issues.append(IssueCreate(
                        file_id=file_id,
                        rule_code="STYLE_MULTIPLE_H1",
                        severity=IssueSeverity.LOW,
                        title=f"Multiple H1 headings (#{i+1})",
                        description=f"Document has multiple H1 headings. Consider using H2 instead: '{heading.content}'",
                        snippet=f"# {heading.content}",
                        line_start=heading.line_start,
                        line_end=heading.line_end,
                        evidence={
                            'h1_count': len(h1_headings),
                            'heading_text': heading.content,
                            'suggested_level': 2
                        },
                        proposed_snippet=f"## {heading.content}",
                        provenance=["rule"],
                        can_auto_apply=True,
                        first_seen_run_id=run_id,
                        last_seen_run_id=run_id
                    ))
        
        return issues
    
    def _check_image_alt_text(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Check that images have alt text"""
        issues = []
        
        for img in doc.images:
            alt_text = img.attributes.get('alt', '').strip()
            
            if not alt_text:
                url = img.attributes.get('url', '')
                
                issues.append(IssueCreate(
                    file_id=file_id,
                    rule_code="STYLE_IMG_NO_ALT",
                    severity=IssueSeverity.MEDIUM,
                    title="Image missing alt text",
                    description=f"Image '{url}' is missing alt text for accessibility.",
                    snippet=f"![{alt_text}]({url})",
                    line_start=img.line_start,
                    line_end=img.line_end,
                    evidence={
                        'image_url': url,
                        'current_alt': alt_text,
                        'accessibility_impact': True
                    },
                    provenance=["rule"],
                    can_auto_apply=False,  # Alt text needs manual writing
                    first_seen_run_id=run_id,
                    last_seen_run_id=run_id
                ))
        
        return issues
    
    def _check_terminology(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Check terminology consistency"""
        issues = []
        
        for term_pattern in self.term_patterns:
            if not term_pattern['alternatives']:
                continue  # No alternatives to check
            
            canonical = term_pattern['canonical']
            alternatives = term_pattern['alternatives']
            
            # Search for alternative terms in the document
            lines = doc.body_content.split('\n')
            
            for line_num, line in enumerate(lines, 1):
                for alt_term in alternatives:
                    # Use word boundary regex to avoid partial matches
                    pattern = r'\b' + re.escape(alt_term) + r'\b'
                    matches = list(re.finditer(pattern, line, re.IGNORECASE))
                    
                    for match in matches:
                        # Skip if it's in a code block (basic check)
                        if '```' in line or line.strip().startswith('    '):
                            continue
                        
                        # Create issue for non-canonical term
                        suggested_line = line.replace(match.group(0), canonical, 1)
                        
                        issues.append(IssueCreate(
                            file_id=file_id,
                            rule_code="STYLE_TERMINOLOGY",
                            severity=IssueSeverity.LOW,
                            title=f"Non-canonical terminology: '{alt_term}'",
                            description=f"Use the canonical term '{canonical}' instead of '{alt_term}' for consistency.",
                            snippet=line.strip(),
                            line_start=line_num,
                            line_end=line_num,
                            evidence={
                                'found_term': alt_term,
                                'canonical_term': canonical,
                                'match_position': match.start(),
                                'context': line.strip()
                            },
                            proposed_snippet=suggested_line.strip(),
                            provenance=["rule"],
                            can_auto_apply=True,  # Simple text replacement
                            first_seen_run_id=run_id,
                            last_seen_run_id=run_id
                        ))
        
        return issues
    
    def _check_list_formatting(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Check list formatting consistency (future enhancement)"""
        issues = []
        # TODO: Implement list formatting checks
        return issues
    
    def _check_code_block_languages(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Check that code blocks specify languages"""
        issues = []
        
        for code_block in doc.code_blocks:
            language = code_block.attributes.get('language', '').strip()
            
            if not language:
                # Try to infer language from content
                content = code_block.content.strip()
                inferred_lang = self._infer_code_language(content)
                
                if inferred_lang:
                    issues.append(IssueCreate(
                        file_id=file_id,
                        rule_code="STYLE_CODE_NO_LANG",
                        severity=IssueSeverity.LOW,
                        title="Code block missing language specification",
                        description=f"Code block should specify language for syntax highlighting. Inferred: {inferred_lang}",
                        snippet=f"```\n{content[:100]}...\n```" if len(content) > 100 else f"```\n{content}\n```",
                        line_start=code_block.line_start,
                        line_end=code_block.line_end,
                        evidence={
                            'inferred_language': inferred_lang,
                            'content_preview': content[:200]
                        },
                        proposed_snippet=f"```{inferred_lang}\n{content}\n```",
                        provenance=["rule"],
                        can_auto_apply=True,
                        first_seen_run_id=run_id,
                        last_seen_run_id=run_id
                    ))
        
        return issues
    
    def _infer_code_language(self, code_content: str) -> Optional[str]:
        """Infer programming language from code content"""
        content = code_content.strip().lower()
        
        # Simple heuristics
        if 'import ' in content or 'def ' in content or 'print(' in content:
            return 'python'
        elif 'wandb ' in content and content.startswith('wandb'):
            return 'bash'
        elif 'npm ' in content or 'yarn ' in content or 'const ' in content:
            return 'javascript'
        elif '#!/bin/bash' in content or content.startswith('$'):
            return 'bash'
        elif '{' in content and '"' in content and content.count('{') > content.count('def'):
            return 'json'
        
        return None


# Convenience function
def analyze_style(doc: MDXDocument, file_id: int, run_id: int, config: Dict[str, Any] = None) -> List[IssueCreate]:
    """Analyze style issues in a document"""
    style_config = config or {}
    
    analyzer = StyleAnalyzer(
        require_one_h1=style_config.get('require_one_h1', True),
        require_img_alt=style_config.get('require_img_alt', True),
        canonical_terms=style_config.get('canonical', [])
    )
    
    return analyzer.analyze_document(doc, file_id, run_id)