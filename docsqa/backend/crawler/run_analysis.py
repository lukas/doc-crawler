#!/usr/bin/env python3
"""
Main entrypoint for running document analysis.
"""
import asyncio
import logging
import sys
import argparse
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings
from core.db import db, init_db
from core.models import AnalysisRun, File, Issue, RunStatus, RunSource
from core.git_utils import GitRepository
from core.mdx_parse import parse_mdx_file
from core.chunker import DocumentChunker
from services.llm_client import create_llm_client
from services.embeddings import get_embedding_service
from core.verifier import verifier
from .pipeline import AnalysisPipeline
from .repo_sync import RepositorySync

logger = logging.getLogger(__name__)


class AnalysisRunner:
    """Main runner for document analysis"""
    
    def __init__(self, config_path: Optional[str] = None, llm_enabled: bool = True):
        self.config = settings.config
        self.llm_enabled = llm_enabled
        self.pipeline: Optional[AnalysisPipeline] = None
        
        # Initialize services
        self.repo_sync = RepositorySync(self.config)
        
        if self.llm_enabled:
            self.llm_client = create_llm_client(
                provider=self.config.llm.provider,
                model=self.config.llm.model,
                temperature=self.config.llm.temperature,
                max_output_tokens=self.config.llm.max_output_tokens,
                json_mode=self.config.llm.json_mode
            )
            
            self.embedding_service = get_embedding_service(
                model_name=self.config.retrieval.embedding_model,
                index_path=self.config.retrieval.index_path
            )
        else:
            self.llm_client = None
            self.embedding_service = None
        
        self.chunker = DocumentChunker()
    
    async def run_full_analysis(self, source: str = "manual", commit_sha: Optional[str] = None) -> int:
        """Run complete analysis pipeline"""
        logger.info("Starting full document analysis")
        
        # Initialize database
        init_db()
        
        # Create analysis run record
        with db.get_session() as session:
            run = AnalysisRun(
                commit_sha=commit_sha or "",
                source=RunSource(source),
                status=RunStatus.RUNNING,
                started_at=datetime.now()
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id
        
        try:
            # 1. Repository sync
            logger.info("Syncing repository...")
            repo_info = await self.repo_sync.sync_repository()
            
            if not commit_sha:
                commit_sha = repo_info['current_commit']
            
            # Update run with actual commit SHA
            with db.get_session() as session:
                run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
                run.commit_sha = commit_sha
                session.commit()
            
            # 2. Get changed files
            changed_files = await self.repo_sync.get_changed_files(run_id)
            logger.info(f"Found {len(changed_files)} files to analyze")
            
            if not changed_files:
                logger.info("No files to analyze")
                await self._mark_run_completed(run_id, {"files_analyzed": 0})
                return run_id
            
            # 3. Initialize pipeline
            self.pipeline = AnalysisPipeline(
                llm_client=self.llm_client,
                embedding_service=self.embedding_service,
                verifier=verifier,
                config=self.config
            )
            
            # 4. Process files
            total_issues = 0
            llm_token_in = 0
            llm_token_out = 0
            
            for file_record in changed_files:
                try:
                    logger.info(f"Processing {file_record.path}")
                    
                    # Get file content
                    content = self.repo_sync.get_file_content(file_record.path)
                    if not content:
                        logger.warning(f"Could not read content for {file_record.path}")
                        continue
                    
                    # Parse document
                    doc = parse_mdx_file(file_record.path, content)
                    
                    # Chunk document
                    chunks = self.chunker.chunk_document(doc)
                    
                    # Update embeddings
                    if self.embedding_service:
                        await self.embedding_service.add_chunks(chunks)
                    
                    # Run analysis pipeline
                    file_issues, token_usage = await self.pipeline.analyze_file(
                        doc, chunks, file_record.id, run_id
                    )
                    
                    total_issues += len(file_issues)
                    llm_token_in += token_usage.get('tokens_in', 0)
                    llm_token_out += token_usage.get('tokens_out', 0)
                    
                    logger.info(f"Found {len(file_issues)} issues in {file_record.path}")
                    
                except Exception as e:
                    logger.error(f"Error processing {file_record.path}: {e}")
                    continue
            
            # 5. Mark run as completed
            stats = {
                "files_analyzed": len(changed_files),
                "total_issues": total_issues,
                "llm_tokens_in": llm_token_in,
                "llm_tokens_out": llm_token_out
            }
            
            await self._mark_run_completed(run_id, stats, llm_token_in, llm_token_out)
            logger.info(f"Analysis completed. Found {total_issues} issues across {len(changed_files)} files")
            
            return run_id
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            await self._mark_run_failed(run_id, str(e))
            raise
        
        finally:
            if self.llm_client:
                await self.llm_client.close()
    
    async def _mark_run_completed(self, run_id: int, stats: Dict[str, Any], 
                                 llm_token_in: int = 0, llm_token_out: int = 0):
        """Mark analysis run as completed"""
        with db.get_session() as session:
            run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
            if run:
                run.status = RunStatus.SUCCESS
                run.finished_at = datetime.now()
                run.stats = stats
                run.llm_token_in = llm_token_in
                run.llm_token_out = llm_token_out
                # Simple cost estimation: $0.0001 per 1K tokens
                run.llm_cost_estimate = (llm_token_in + llm_token_out) * 0.0001 / 1000
                session.commit()
    
    async def _mark_run_failed(self, run_id: int, error_message: str):
        """Mark analysis run as failed"""
        with db.get_session() as session:
            run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
            if run:
                run.status = RunStatus.FAILED
                run.finished_at = datetime.now()
                run.stats = {"error": error_message}
                session.commit()


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Run document analysis")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--source", default="manual", help="Run source (manual, scheduled, webhook)")
    parser.add_argument("--commit", help="Specific commit SHA to analyze")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM analysis")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        runner = AnalysisRunner(
            config_path=args.config,
            llm_enabled=not args.no_llm
        )
        
        run_id = await runner.run_full_analysis(
            source=args.source,
            commit_sha=args.commit
        )
        
        print(f"Analysis completed successfully. Run ID: {run_id}")
        return 0
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))