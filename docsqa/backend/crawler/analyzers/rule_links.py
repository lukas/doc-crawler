import asyncio
import logging
from typing import List, Dict, Any
from dataclasses import dataclass

from ...core.linkcheck import LinkChecker, extract_urls_from_text
from ...core.mdx_parse import MDXDocument
from ...core.schemas import IssueCreate, IssueSeverity

logger = logging.getLogger(__name__)


@dataclass
class LinkIssue:
    rule_code: str
    severity: IssueSeverity
    title: str
    description: str
    line_start: int
    line_end: int
    snippet: str
    evidence: Dict[str, Any]
    provenance: List[str] = None

    def __post_init__(self):
        if self.provenance is None:
            self.provenance = ["rule"]


class LinkAnalyzer:
    """Analyzer for validating links in markdown documents"""
    
    def __init__(self, timeout_ms: int = 4000, concurrency: int = 8, per_host_limit: int = 2):
        self.timeout_ms = timeout_ms
        self.concurrency = concurrency
        self.per_host_limit = per_host_limit
        self.base_url = "https://docs.wandb.ai"  # Base URL for relative link resolution
    
    async def analyze_document(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Analyze all links in a document"""
        issues = []
        
        try:
            # Extract all links from the document
            all_links = self._extract_all_links(doc)
            
            if not all_links:
                return issues
            
            # Check links
            async with LinkChecker(
                timeout_ms=self.timeout_ms,
                concurrency=self.concurrency,
                per_host_limit=self.per_host_limit
            ) as checker:
                # Get unique URLs to check
                urls_to_check = list(set(link['url'] for link in all_links))
                results = await checker.check_links(urls_to_check, self.base_url)
                
                # Process results and create issues
                for link in all_links:
                    url = link['url']
                    result = results.get(url)
                    
                    if result and not result.is_valid:
                        issue = self._create_link_issue(link, result, file_id, run_id)
                        if issue:
                            issues.append(issue)
                
        except Exception as e:
            logger.error(f"Error analyzing links in {doc.filepath}: {e}")
        
        return issues
    
    def _extract_all_links(self, doc: MDXDocument) -> List[Dict[str, Any]]:
        """Extract all links from document with context"""
        links = []
        
        # Extract from MDX elements
        for link_element in doc.links:
            links.append({
                'url': link_element.attributes['url'],
                'text': link_element.attributes['text'],
                'line_start': link_element.line_start,
                'line_end': link_element.line_end,
                'type': 'markdown_link',
                'context': self._get_line_context(doc, link_element.line_start)
            })
        
        # Also check for URLs in plain text (not caught by markdown parser)
        lines = doc.body_content.split('\n')
        for i, line in enumerate(lines, 1):
            # Skip lines that are already markdown links or in code blocks
            if '[' in line and '](' in line:
                continue
            if line.strip().startswith('```'):
                continue
            
            urls = extract_urls_from_text(line)
            for url in urls:
                if not any(link['url'] == url and link['line_start'] == i for link in links):
                    links.append({
                        'url': url,
                        'text': url,
                        'line_start': i,
                        'line_end': i,
                        'type': 'plain_url',
                        'context': line.strip()
                    })
        
        return links
    
    def _get_line_context(self, doc: MDXDocument, line_num: int, context_lines: int = 2) -> str:
        """Get context around a line"""
        lines = doc.body_content.split('\n')
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        
        context = lines[start:end]
        return '\n'.join(context)
    
    def _create_link_issue(self, link: Dict[str, Any], result, file_id: int, run_id: int) -> Optional[IssueCreate]:
        """Create an issue for a broken link"""
        try:
            # Determine severity based on error type
            severity = self._determine_severity(result)
            
            # Determine rule code based on status
            rule_code = self._determine_rule_code(result)
            
            # Create descriptive title and description
            title = f"Broken link: {link['url']}"
            
            if result.status_code:
                description = f"Link returns HTTP {result.status_code}: {result.error_message}"
            else:
                description = f"Link is unreachable: {result.error_message}"
            
            # Add helpful context
            if result.redirect_url:
                description += f"\nRedirected to: {result.redirect_url}"
            
            if link['type'] == 'markdown_link' and link['text'] != link['url']:
                description += f"\nLink text: '{link['text']}'"
            
            evidence = {
                'url': link['url'],
                'status_code': result.status_code,
                'error_message': result.error_message,
                'response_time_ms': result.response_time_ms,
                'link_type': link['type'],
                'link_text': link['text']
            }
            
            if result.redirect_url:
                evidence['redirect_url'] = result.redirect_url
            
            return IssueCreate(
                file_id=file_id,
                rule_code=rule_code,
                severity=severity,
                title=title,
                description=description,
                snippet=link['context'],
                line_start=link['line_start'],
                line_end=link['line_end'],
                evidence=evidence,
                provenance=["rule"],
                can_auto_apply=False,  # Link fixes usually need manual review
                first_seen_run_id=run_id,
                last_seen_run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Error creating link issue: {e}")
            return None
    
    def _determine_severity(self, result) -> IssueSeverity:
        """Determine issue severity based on link check result"""
        if not result.status_code:
            # Connection errors, timeouts
            return IssueSeverity.HIGH
        
        if result.status_code == 404:
            return IssueSeverity.HIGH
        elif result.status_code in [403, 401]:
            return IssueSeverity.MEDIUM
        elif result.status_code >= 500:
            return IssueSeverity.MEDIUM  # Could be temporary
        else:
            return IssueSeverity.LOW
    
    def _determine_rule_code(self, result) -> str:
        """Determine rule code based on link check result"""
        if not result.status_code:
            if "timeout" in (result.error_message or "").lower():
                return "LINK_TIMEOUT"
            else:
                return "LINK_UNREACHABLE"
        
        if result.status_code == 404:
            return "LINK_404"
        elif result.status_code in [403, 401]:
            return "LINK_FORBIDDEN"
        elif result.status_code >= 500:
            return "LINK_SERVER_ERROR"
        else:
            return "LINK_ERROR"


# Async wrapper function for easier integration
async def analyze_links(doc: MDXDocument, file_id: int, run_id: int, config: Dict[str, Any] = None) -> List[IssueCreate]:
    """Convenience function to analyze links in a document"""
    analyzer_config = config or {}
    
    analyzer = LinkAnalyzer(
        timeout_ms=analyzer_config.get('timeout_ms', 4000),
        concurrency=analyzer_config.get('concurrency', 8),
        per_host_limit=analyzer_config.get('per_host_limit', 2)
    )
    
    return await analyzer.analyze_document(doc, file_id, run_id)