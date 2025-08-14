import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from markdown import Markdown
from markdown.extensions import tables, codehilite

from .patches import parse_unified_diff, count_whitespace_changes, validate_patch_scope
from .linkcheck import check_urls_batch, extract_urls_from_text
from .catalogs import catalog_loader
from .version_resolver import VersionResolver
from .mdx_parse import MDXDocument

logger = logging.getLogger(__name__)


class VerificationResult:
    def __init__(self):
        self.can_auto_apply = True
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.notes: List[str] = []
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def add_error(self, message: str):
        self.errors.append(message)
        self.can_auto_apply = False
    
    def add_note(self, message: str):
        self.notes.append(message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'can_auto_apply': self.can_auto_apply,
            'warnings': self.warnings,
            'errors': self.errors,
            'notes': self.notes
        }


class Verifier:
    """Verifies that suggested patches are safe to auto-apply"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.require_citations = self.config.get('require_citations', True)
        self.allow_code_edits = self.config.get('allow_code_edits', False)
        self.max_whitespace_delta_lines = self.config.get('max_whitespace_delta_lines', 3)
        
        self.version_resolver = VersionResolver()
        self.md = Markdown(extensions=['tables', 'codehilite'])
    
    async def verify_suggestion(self, original_content: str, suggested_patch: str,
                              line_start: int, line_end: int, suggestion_type: str,
                              citations: List[Dict[str, Any]], provenance: List[str],
                              file_path: str) -> VerificationResult:
        """Verify a suggestion for safety"""
        result = VerificationResult()
        
        try:
            # 1. Validate patch scope
            if not self._check_patch_scope(suggested_patch, line_start, line_end, result):
                return result
            
            # 2. Check markdown node consistency
            if not self._check_markdown_consistency(original_content, suggested_patch, suggestion_type, result):
                return result
            
            # 3. Check whitespace churn
            if not self._check_whitespace_churn(original_content, suggested_patch, result):
                return result
            
            # 4. Validate citations for accuracy claims
            if not await self._validate_citations(citations, suggestion_type, result):
                return result
            
            # 5. Check code edits
            if not self._check_code_edits(suggested_patch, citations, suggestion_type, result):
                return result
            
            # 6. Validate links if any are added/changed
            await self._validate_links(suggested_patch, file_path, result)
            
            # 7. Check version references
            await self._validate_versions(suggested_patch, result)
            
        except Exception as e:
            logger.error(f"Error during verification: {e}")
            result.add_error(f"Verification failed: {str(e)}")
        
        return result
    
    def _check_patch_scope(self, patch_content: str, allowed_start: int, 
                          allowed_end: int, result: VerificationResult) -> bool:
        """Check that patch only affects allowed lines"""
        try:
            if not validate_patch_scope(patch_content, allowed_start, allowed_end):
                result.add_error("Patch affects lines outside the allowed range")
                return False
            return True
        except Exception as e:
            result.add_error(f"Failed to validate patch scope: {e}")
            return False
    
    def _check_markdown_consistency(self, original_content: str, patch_content: str,
                                  suggestion_type: str, result: VerificationResult) -> bool:
        """Check that markdown structure is preserved"""
        try:
            # Extract snippets from patch
            from .patches import extract_snippet_from_patch
            snippets = extract_snippet_from_patch(patch_content)
            
            if not snippets:
                result.add_warning("Could not extract snippets from patch")
                return True
            
            original_snippet = snippets['original']
            modified_snippet = snippets['modified']
            
            # Parse both versions
            original_html = self.md.convert(original_snippet)
            self.md.reset()
            modified_html = self.md.convert(modified_snippet)
            
            # For text edits, structure should be very similar
            if suggestion_type == "text_edit":
                if self._count_html_tags(original_html) != self._count_html_tags(modified_html):
                    result.add_warning("Markdown structure changed significantly")
            
            # Code edits are only allowed if explicitly configured
            elif suggestion_type == "code_edit" and not self.allow_code_edits:
                result.add_error("Code edits are not allowed by configuration")
                return False
            
            return True
            
        except Exception as e:
            result.add_warning(f"Could not verify markdown consistency: {e}")
            return True  # Allow with warning
    
    def _count_html_tags(self, html: str) -> Dict[str, int]:
        """Count HTML tags in rendered markdown"""
        tags = re.findall(r'<(\w+)', html)
        tag_counts = {}
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return tag_counts
    
    def _check_whitespace_churn(self, original_content: str, patch_content: str, 
                              result: VerificationResult) -> bool:
        """Check for excessive whitespace-only changes"""
        try:
            from .patches import extract_snippet_from_patch
            snippets = extract_snippet_from_patch(patch_content)
            
            if not snippets:
                return True
            
            whitespace_changes = count_whitespace_changes(
                snippets['original'], snippets['modified']
            )
            
            if whitespace_changes > self.max_whitespace_delta_lines:
                result.add_error(f"Too many whitespace-only changes: {whitespace_changes}")
                return False
            
            return True
            
        except Exception as e:
            result.add_warning(f"Could not check whitespace changes: {e}")
            return True
    
    async def _validate_citations(self, citations: List[Dict[str, Any]], 
                                suggestion_type: str, result: VerificationResult) -> bool:
        """Validate that citations support accuracy claims"""
        try:
            # Accuracy claims must have citations if required
            if (self.require_citations and 
                suggestion_type in ["accuracy", "code_edit"] and 
                not citations):
                result.add_error("Accuracy claims require citations")
                return False
            
            # Validate citation format and content
            for citation in citations:
                citation_type = citation.get('type')
                
                if citation_type == "catalog":
                    # Validate catalog citations
                    key = citation.get('key', '')
                    if key.startswith('wandb.'):
                        catalog_info = catalog_loader.get_api_info(key)
                        if not catalog_info:
                            result.add_warning(f"Catalog citation not found: {key}")
                    elif key.startswith('wandb '):
                        catalog_info = catalog_loader.get_cli_info(key)
                        if not catalog_info:
                            result.add_warning(f"CLI catalog citation not found: {key}")
                
                elif citation_type == "fact":
                    # Basic validation for fact citations
                    if not citation.get('value'):
                        result.add_warning("Fact citation missing value")
            
            return True
            
        except Exception as e:
            result.add_warning(f"Could not validate citations: {e}")
            return True
    
    def _check_code_edits(self, patch_content: str, citations: List[Dict[str, Any]],
                         suggestion_type: str, result: VerificationResult) -> bool:
        """Check code edit requirements"""
        if suggestion_type != "code_edit":
            return True
        
        if not self.allow_code_edits:
            result.add_error("Code edits are disabled by configuration")
            return False
        
        # Code edits must have catalog citations
        catalog_citations = [c for c in citations if c.get('type') == 'catalog']
        if not catalog_citations:
            result.add_error("Code edits require catalog citations")
            return False
        
        return True
    
    async def _validate_links(self, patch_content: str, file_path: str, 
                            result: VerificationResult):
        """Validate any links added or changed in the patch"""
        try:
            from .patches import extract_snippet_from_patch
            snippets = extract_snippet_from_patch(patch_content)
            
            if not snippets:
                return
            
            original_urls = set(extract_urls_from_text(snippets['original']))
            modified_urls = set(extract_urls_from_text(snippets['modified']))
            
            # Check new or changed URLs
            new_urls = modified_urls - original_urls
            
            if new_urls:
                result.add_note(f"Patch adds {len(new_urls)} new links")
                
                # Quick validation for new URLs
                base_url = "https://docs.wandb.ai"  # Base for relative links
                link_results = await check_urls_batch(list(new_urls), base_url, timeout_ms=2000)
                
                for url, link_result in link_results.items():
                    if not link_result.is_valid:
                        result.add_warning(f"New link may be broken: {url} ({link_result.error_message})")
        
        except Exception as e:
            result.add_note(f"Could not validate links: {e}")
    
    async def _validate_versions(self, patch_content: str, result: VerificationResult):
        """Validate version references in the patch"""
        try:
            from .patches import extract_snippet_from_patch
            snippets = extract_snippet_from_patch(patch_content)
            
            if not snippets:
                return
            
            # Check for version changes
            original_versions = self.version_resolver.extract_versions_from_text(snippets['original'])
            modified_versions = self.version_resolver.extract_versions_from_text(snippets['modified'])
            
            # If versions are being changed, validate they exist
            for version_ref in modified_versions:
                version_str = version_ref['version']
                try:
                    # Basic version format check
                    from packaging import version
                    version.parse(version_str)
                    
                    # Could add more validation here (check if version exists on PyPI)
                    
                except Exception as e:
                    result.add_warning(f"Version format may be invalid: {version_str}")
        
        except Exception as e:
            result.add_note(f"Could not validate versions: {e}")


# Global verifier instance
verifier = Verifier()


async def verify_patch(original_content: str, suggested_patch: str, line_start: int, 
                      line_end: int, suggestion_type: str, citations: List[Dict[str, Any]],
                      provenance: List[str], file_path: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """Convenience function to verify a patch"""
    verification_config = config or {}
    patch_verifier = Verifier(verification_config)
    
    result = await patch_verifier.verify_suggestion(
        original_content, suggested_patch, line_start, line_end,
        suggestion_type, citations, provenance, file_path
    )
    
    return result.to_dict()