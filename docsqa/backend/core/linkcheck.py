import asyncio
import httpx
import logging
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class LinkResult:
    url: str
    status_code: Optional[int]
    is_valid: bool
    error_message: Optional[str]
    redirect_url: Optional[str] = None
    response_time_ms: Optional[int] = None


class LinkChecker:
    def __init__(self, timeout_ms: int = 4000, concurrency: int = 8, per_host_limit: int = 2):
        self.timeout = timeout_ms / 1000  # Convert to seconds
        self.concurrency = concurrency
        self.per_host_limit = per_host_limit
        self.session: Optional[httpx.AsyncClient] = None
        
        # Cache for results to avoid duplicate checks
        self._cache: Dict[str, LinkResult] = {}
    
    async def __aenter__(self):
        """Async context manager entry"""
        limits = httpx.Limits(
            max_keepalive_connections=self.concurrency,
            max_connections=self.concurrency,
            max_connections_per_host=self.per_host_limit
        )
        
        self.session = httpx.AsyncClient(
            timeout=self.timeout,
            limits=limits,
            follow_redirects=True,
            headers={
                'User-Agent': 'DocsQA-LinkChecker/1.0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.aclose()
    
    async def check_links(self, urls: List[str], base_url: Optional[str] = None) -> Dict[str, LinkResult]:
        """Check multiple URLs concurrently"""
        if not self.session:
            raise RuntimeError("LinkChecker must be used as an async context manager")
        
        # Prepare URLs
        urls_to_check = []
        for url in urls:
            normalized_url = self._normalize_url(url, base_url)
            if normalized_url and normalized_url not in self._cache:
                urls_to_check.append(normalized_url)
        
        # Check URLs with concurrency control
        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [self._check_single_url(semaphore, url) for url in urls_to_check]
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(results):
                if isinstance(result, LinkResult):
                    self._cache[urls_to_check[i]] = result
                else:
                    # Handle exceptions
                    logger.error(f"Error checking {urls_to_check[i]}: {result}")
                    self._cache[urls_to_check[i]] = LinkResult(
                        url=urls_to_check[i],
                        status_code=None,
                        is_valid=False,
                        error_message=str(result)
                    )
        
        # Return results for all requested URLs
        final_results = {}
        for url in urls:
            normalized_url = self._normalize_url(url, base_url)
            if normalized_url in self._cache:
                final_results[url] = self._cache[normalized_url]
            else:
                final_results[url] = LinkResult(
                    url=url,
                    status_code=None,
                    is_valid=False,
                    error_message="URL could not be normalized"
                )
        
        return final_results
    
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _check_single_url(self, semaphore: asyncio.Semaphore, url: str) -> LinkResult:
        """Check a single URL with retry logic"""
        async with semaphore:
            import time
            start_time = time.time()
            
            try:
                # Skip certain schemes
                parsed = urlparse(url)
                if parsed.scheme in ['mailto', 'tel', 'javascript']:
                    return LinkResult(
                        url=url,
                        status_code=None,
                        is_valid=True,
                        error_message=None,
                        response_time_ms=0
                    )
                
                # For internal/fragment links, just validate format
                if url.startswith('#') or not parsed.netloc:
                    return LinkResult(
                        url=url,
                        status_code=None,
                        is_valid=True,
                        error_message=None,
                        response_time_ms=0
                    )
                
                # Make HEAD request first (faster), fallback to GET
                try:
                    response = await self.session.head(url)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 405:  # Method not allowed
                        response = await self.session.get(url)
                    else:
                        raise
                
                response_time_ms = int((time.time() - start_time) * 1000)
                
                # Consider redirect chains
                redirect_url = None
                if response.history:
                    redirect_url = str(response.url)
                
                # Determine if valid
                is_valid = 200 <= response.status_code < 400
                
                return LinkResult(
                    url=url,
                    status_code=response.status_code,
                    is_valid=is_valid,
                    error_message=None if is_valid else f"HTTP {response.status_code}",
                    redirect_url=redirect_url,
                    response_time_ms=response_time_ms
                )
                
            except httpx.TimeoutException:
                response_time_ms = int((time.time() - start_time) * 1000)
                return LinkResult(
                    url=url,
                    status_code=None,
                    is_valid=False,
                    error_message="Timeout",
                    response_time_ms=response_time_ms
                )
            
            except httpx.ConnectError as e:
                response_time_ms = int((time.time() - start_time) * 1000)
                return LinkResult(
                    url=url,
                    status_code=None,
                    is_valid=False,
                    error_message=f"Connection error: {str(e)}",
                    response_time_ms=response_time_ms
                )
            
            except Exception as e:
                response_time_ms = int((time.time() - start_time) * 1000)
                logger.error(f"Unexpected error checking {url}: {e}")
                return LinkResult(
                    url=url,
                    status_code=None,
                    is_valid=False,
                    error_message=str(e),
                    response_time_ms=response_time_ms
                )
    
    def _normalize_url(self, url: str, base_url: Optional[str] = None) -> Optional[str]:
        """Normalize URL for checking"""
        if not url or url.strip() == '':
            return None
        
        url = url.strip()
        
        # Handle relative URLs
        if base_url and not url.startswith(('http://', 'https://', 'mailto:', 'tel:', 'javascript:')):
            if url.startswith('//'):
                # Protocol-relative URL
                parsed_base = urlparse(base_url)
                url = f"{parsed_base.scheme}:{url}"
            elif url.startswith('/'):
                # Absolute path
                url = urljoin(base_url, url)
            elif not url.startswith('#'):
                # Relative path (skip fragments for now)
                url = urljoin(base_url, url)
            else:
                # Fragment-only link, validate relative to base
                return url
        
        # Clean up URL
        if '#' in url:
            url = url.split('#')[0]  # Remove fragment for link checking
        
        if '?' in url:
            # Keep query parameters for now
            pass
        
        return url if url else None
    
    def categorize_links(self, urls: List[str], base_url: str) -> Dict[str, List[str]]:
        """Categorize links by type"""
        categories = {
            'internal': [],
            'external': [],
            'fragments': [],
            'special': []  # mailto, tel, etc.
        }
        
        base_domain = urlparse(base_url).netloc if base_url else ''
        
        for url in urls:
            if not url:
                continue
                
            if url.startswith('#'):
                categories['fragments'].append(url)
            elif url.startswith(('mailto:', 'tel:', 'javascript:')):
                categories['special'].append(url)
            else:
                parsed = urlparse(url if url.startswith('http') else urljoin(base_url, url))
                if parsed.netloc == base_domain:
                    categories['internal'].append(url)
                else:
                    categories['external'].append(url)
        
        return categories


# Utility functions for common use cases
async def check_urls_batch(urls: List[str], base_url: Optional[str] = None, 
                          timeout_ms: int = 4000, concurrency: int = 8) -> Dict[str, LinkResult]:
    """Convenience function to check URLs in a batch"""
    async with LinkChecker(timeout_ms=timeout_ms, concurrency=concurrency) as checker:
        return await checker.check_links(urls, base_url)


def extract_urls_from_text(text: str) -> List[str]:
    """Extract URLs from markdown text"""
    import re
    
    # Markdown link pattern: [text](url)
    markdown_pattern = r'\[([^\]]*)\]\(([^)]+)\)'
    
    # Direct URL pattern
    url_pattern = r'https?://[^\s<>"\'\)]+|www\.[^\s<>"\'\)]+'
    
    urls = []
    
    # Extract markdown links
    for match in re.finditer(markdown_pattern, text):
        urls.append(match.group(2))
    
    # Extract direct URLs (but avoid duplicates from markdown links)
    markdown_urls = {match.group(2) for match in re.finditer(markdown_pattern, text)}
    for match in re.finditer(url_pattern, text):
        url = match.group(0)
        if url not in markdown_urls:
            urls.append(url)
    
    return list(set(urls))  # Remove duplicates