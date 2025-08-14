import logging
from typing import List, Dict, Any, Optional, Tuple
import asyncio

from ..core.mdx_parse import MDXDocument
from ..core.chunker import DocumentChunk
from ..core.schemas import IssueCreate, LLMSuggestion, Citation
from ..core.models import Issue
from ..core.db import db
from ..core.verifier import Verifier
from ..core.patches import create_unified_diff
from ..core.catalogs import catalog_loader
from ..core.version_resolver import VersionResolver
from ..services.llm_client import LLMClient
from ..services.embeddings import EmbeddingService

# Import analyzers
from .analyzers.rule_links import analyze_links
from .analyzers.rule_versions import analyze_versions
from .analyzers.rule_api_cli import analyze_api_cli
from .analyzers.rule_style import analyze_style

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Main pipeline for analyzing documents"""
    
    def __init__(self, llm_client: Optional[LLMClient], 
                 embedding_service: Optional[EmbeddingService],
                 verifier: Verifier, config: Any):
        self.llm_client = llm_client
        self.embedding_service = embedding_service
        self.verifier = verifier
        self.config = config
        
        # Initialize services
        self.version_resolver = VersionResolver()
        
    async def analyze_file(self, doc: MDXDocument, chunks: List[DocumentChunk],
                          file_id: int, run_id: int) -> Tuple[List[Issue], Dict[str, int]]:
        """Analyze a single file and return issues + token usage"""
        
        all_issues = []
        token_usage = {"tokens_in": 0, "tokens_out": 0}
        
        try:
            # 1. Run rule-based analyzers
            rule_issues = await self._run_rule_analyzers(doc, file_id, run_id)
            
            # 2. Run LLM quality analysis if enabled
            llm_issues = []
            if self.llm_client:
                llm_issues, llm_tokens = await self._run_llm_analysis(
                    doc, chunks, file_id, run_id
                )
                token_usage["tokens_in"] += llm_tokens.get("tokens_in", 0)
                token_usage["tokens_out"] += llm_tokens.get("tokens_out", 0)
            
            # 3. Combine and deduplicate issues
            combined_issues = self._combine_issues(rule_issues, llm_issues)
            
            # 4. Store issues in database
            stored_issues = await self._store_issues(combined_issues)
            all_issues.extend(stored_issues)
            
            logger.info(f"Analysis completed for {doc.filepath}: {len(stored_issues)} issues")
            
        except Exception as e:
            logger.error(f"Error analyzing file {doc.filepath}: {e}")
        
        return all_issues, token_usage
    
    async def _run_rule_analyzers(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Run all rule-based analyzers"""
        all_issues = []
        
        try:
            # Run analyzers concurrently
            tasks = [
                analyze_links(doc, file_id, run_id, self.config.links.__dict__),
                analyze_versions(doc, file_id, run_id, self.config.versions.__dict__),
                analyze_api_cli(doc, file_id, run_id),
                analyze_style(doc, file_id, run_id, {
                    **self.config.style.__dict__,
                    "canonical": self.config.terminology.canonical
                })
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    analyzer_name = ["links", "versions", "api_cli", "style"][i]
                    logger.error(f"Error in {analyzer_name} analyzer: {result}")
                else:
                    all_issues.extend(result)
            
        except Exception as e:
            logger.error(f"Error running rule analyzers: {e}")
        
        return all_issues
    
    async def _run_llm_analysis(self, doc: MDXDocument, chunks: List[DocumentChunk],
                              file_id: int, run_id: int) -> Tuple[List[IssueCreate], Dict[str, int]]:
        """Run LLM-based quality analysis"""
        llm_issues = []
        total_tokens = {"tokens_in": 0, "tokens_out": 0}
        
        try:
            # Process each chunk
            for chunk in chunks:
                try:
                    # Build context for LLM
                    context = await self._build_llm_context(doc, chunk)
                    
                    # Create prompt
                    prompt = self.llm_client.build_context_prompt(
                        chunk_text=chunk.rendered_text,
                        context_text=context["surrounding_context"],
                        retrieved_snippets=context["retrieved_snippets"],
                        facts=context["facts"],
                        file_path=doc.filepath,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line
                    )
                    
                    # Get LLM suggestions
                    response = await self.llm_client.generate_suggestions(prompt, context)
                    
                    # Track token usage (simplified)
                    estimated_tokens_in = len(prompt) // 4  # Rough estimation
                    estimated_tokens_out = sum(len(s.description) for s in response.suggestions) // 4
                    total_tokens["tokens_in"] += estimated_tokens_in
                    total_tokens["tokens_out"] += estimated_tokens_out
                    
                    # Convert LLM suggestions to issues
                    chunk_issues = await self._process_llm_suggestions(
                        response.suggestions, doc, file_id, run_id
                    )
                    llm_issues.extend(chunk_issues)
                    
                except Exception as e:
                    logger.error(f"Error processing chunk {chunk.chunk_id}: {e}")
                    continue
                
        except Exception as e:
            logger.error(f"Error in LLM analysis: {e}")
        
        return llm_issues, total_tokens
    
    async def _build_llm_context(self, doc: MDXDocument, chunk: DocumentChunk) -> Dict[str, Any]:
        """Build context for LLM analysis"""
        context = {
            "surrounding_context": "",
            "retrieved_snippets": [],
            "facts": {}
        }
        
        try:
            # Get surrounding context
            if hasattr(self.embedding_service, 'get_chunk_context'):
                context["surrounding_context"] = self.embedding_service.get_chunk_context(
                    chunk, doc, context_lines=150
                )
            
            # Get similar chunks via retrieval
            if self.embedding_service:
                similar_chunks = await self.embedding_service.query_similar_chunks(
                    chunk.rendered_text, 
                    k=self.config.retrieval.k_neighbors
                )
                
                context["retrieved_snippets"] = [
                    {
                        "path": result.chunk_data.get("file_path", "unknown"),
                        "lines": f"{result.chunk_data.get('start_line', 0)}-{result.chunk_data.get('end_line', 0)}",
                        "text": result.chunk_data.get("content_preview", "")
                    }
                    for result in similar_chunks
                ]
            
            # Build facts
            context["facts"] = await self._build_facts()
            
        except Exception as e:
            logger.warning(f"Error building LLM context: {e}")
        
        return context
    
    async def _build_facts(self) -> Dict[str, Any]:
        """Build facts for LLM context"""
        facts = {}
        
        try:
            # Get latest wandb version
            latest_info = await self.version_resolver.get_latest_version("wandb")
            if latest_info:
                facts["latest_wandb_version"] = latest_info["latest_version"]
            
            # Get API catalog keys
            api_catalog = catalog_loader.load_api_catalog()
            facts["api_catalog_keys"] = list(api_catalog.keys())[:50]  # Limit size
            
            # Get CLI catalog keys  
            cli_catalog = catalog_loader.load_cli_catalog()
            facts["cli_catalog_keys"] = list(cli_catalog.keys())[:50]
            
            # Get canonical terms
            facts["canonical_terms"] = self.config.terminology.canonical
            
        except Exception as e:
            logger.warning(f"Error building facts: {e}")
        
        return facts
    
    async def _process_llm_suggestions(self, suggestions: List[LLMSuggestion], 
                                     doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Convert LLM suggestions to issues"""
        issues = []
        
        for suggestion in suggestions:
            try:
                # Create suggested patch if snippets are different
                suggested_patch = None
                if suggestion.original_snippet != suggestion.proposed_snippet:
                    # Find the lines in the document
                    doc_lines = doc.body_content.split('\n')
                    
                    # Simple patch creation
                    original_content = '\n'.join(doc_lines)
                    modified_lines = doc_lines.copy()
                    
                    # Replace the snippet (simplified - in real system would be more robust)
                    for i, line in enumerate(modified_lines):
                        if suggestion.original_snippet.strip() in line:
                            modified_lines[i] = line.replace(
                                suggestion.original_snippet.strip(),
                                suggestion.proposed_snippet.strip()
                            )
                            break
                    
                    modified_content = '\n'.join(modified_lines)
                    suggested_patch = create_unified_diff(
                        original_content, modified_content, doc.filepath
                    )
                
                # Verify the suggestion
                verification_result = await self.verifier.verify_suggestion(
                    original_content=doc.body_content,
                    suggested_patch=suggested_patch or "",
                    line_start=suggestion.line_start,
                    line_end=suggestion.line_end,
                    suggestion_type=suggestion.type,
                    citations=[c.dict() for c in suggestion.citations],
                    provenance=["llm"],
                    file_path=doc.filepath
                )
                
                # Create issue
                issue = IssueCreate(
                    file_id=file_id,
                    rule_code=suggestion.rule_code,
                    severity=suggestion.severity,
                    title=suggestion.title,
                    description=suggestion.description,
                    snippet=suggestion.original_snippet,
                    line_start=suggestion.line_start,
                    line_end=suggestion.line_end,
                    evidence={
                        "confidence": suggestion.confidence,
                        "tags": suggestion.tags,
                        "llm_type": suggestion.type
                    },
                    proposed_snippet=suggestion.proposed_snippet if suggestion.proposed_snippet != suggestion.original_snippet else None,
                    suggested_patch=suggested_patch,
                    citations=[c.dict() for c in suggestion.citations],
                    provenance=["llm"],
                    can_auto_apply=verification_result["can_auto_apply"],
                    first_seen_run_id=run_id,
                    last_seen_run_id=run_id
                )
                
                issues.append(issue)
                
            except Exception as e:
                logger.error(f"Error processing LLM suggestion: {e}")
                continue
        
        return issues
    
    def _combine_issues(self, rule_issues: List[IssueCreate], 
                       llm_issues: List[IssueCreate]) -> List[IssueCreate]:
        """Combine and deduplicate issues from different sources"""
        # Simple combination - in a more sophisticated system would merge
        # issues that target the same lines/content
        all_issues = rule_issues + llm_issues
        
        # Basic deduplication based on file, rule, and line
        seen_keys = set()
        deduplicated = []
        
        for issue in all_issues:
            key = (issue.file_id, issue.rule_code, issue.line_start, issue.title)
            if key not in seen_keys:
                seen_keys.add(key)
                deduplicated.append(issue)
        
        return deduplicated
    
    async def _store_issues(self, issues: List[IssueCreate]) -> List[Issue]:
        """Store issues in database"""
        stored_issues = []
        
        with db.get_session() as session:
            for issue_data in issues:
                try:
                    # Check if similar issue already exists
                    existing = session.query(Issue).filter(
                        Issue.file_id == issue_data.file_id,
                        Issue.rule_code == issue_data.rule_code,
                        Issue.line_start == issue_data.line_start,
                        Issue.title == issue_data.title
                    ).first()
                    
                    if existing:
                        # Update existing issue
                        existing.last_seen_run_id = issue_data.last_seen_run_id
                        existing.description = issue_data.description
                        stored_issues.append(existing)
                    else:
                        # Create new issue
                        issue = Issue(**issue_data.dict())
                        session.add(issue)
                        session.flush()  # Get ID
                        stored_issues.append(issue)
                
                except Exception as e:
                    logger.error(f"Error storing issue: {e}")
                    continue
            
            session.commit()
        
        return stored_issues