import logging
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
import fnmatch

from ..core.config import Config
from ..core.git_utils import GitRepository
from ..core.models import File, AnalysisRun
from ..core.db import db

logger = logging.getLogger(__name__)


class RepositorySync:
    """Handles repository synchronization and file change detection"""
    
    def __init__(self, config: Config):
        self.config = config
        # Use /data for containers (root), local data dir otherwise
        if Path("/data").exists() and os.access("/data", os.W_OK):
            self.repo_path = Path("/data/repo")
        else:
            self.repo_path = Path("data/repo")
        self.repo = GitRepository(
            str(self.repo_path),
            config.repo.url,
            config.repo.branch
        )
    
    async def sync_repository(self) -> Dict[str, Any]:
        """Sync repository and return current state"""
        logger.info(f"Syncing repository {self.config.repo.url}")
        
        # Clone or update repository
        current_commit = self.repo.clone_or_update()
        
        # Get commit info
        commit_info = self.repo.get_commit_info(current_commit)
        
        logger.info(f"Repository synced to commit {current_commit[:8]}")
        
        return {
            "current_commit": current_commit,
            "commit_info": commit_info,
            "repo_path": str(self.repo_path)
        }
    
    async def get_changed_files(self, run_id: int) -> List[File]:
        """Get files that need to be analyzed"""
        with db.get_session() as session:
            # Get the last successful run
            last_run = session.query(AnalysisRun).filter(
                AnalysisRun.status == "success",
                AnalysisRun.id < run_id
            ).order_by(AnalysisRun.id.desc()).first()
            
            if last_run:
                logger.info(f"Comparing with last run {last_run.id} (commit {last_run.commit_sha[:8]})")
                changed_file_paths = self.repo.get_changed_files(
                    last_run.commit_sha,
                    self.repo.get_current_commit()
                )
            else:
                logger.info("No previous run found, analyzing all files")
                changed_file_paths = [
                    {"status": "A", "path": path} 
                    for path in self.repo.list_files_matching_patterns(
                        self.config.paths.include,
                        self.config.paths.exclude
                    )
                ]
            
            # Filter and process files
            files_to_analyze = []
            current_commit = self.repo.get_current_commit()
            
            for file_change in changed_file_paths:
                path = file_change["path"]
                status = file_change.get("status", "M")
                
                # Check if file matches include/exclude patterns
                if not self._should_include_file(path):
                    continue
                
                # Skip deleted files
                if status == "D":
                    self._mark_file_deleted(session, path)
                    continue
                
                # Get or create file record
                file_record = self._get_or_create_file(session, path, current_commit)
                if file_record:
                    files_to_analyze.append(file_record)
            
            session.commit()
            return files_to_analyze
    
    def _should_include_file(self, path: str) -> bool:
        """Check if file should be included based on patterns"""
        # Check include patterns
        included = False
        for pattern in self.config.paths.include:
            if fnmatch.fnmatch(path, pattern):
                included = True
                break
        
        if not included:
            return False
        
        # Check exclude patterns
        for pattern in self.config.paths.exclude:
            if fnmatch.fnmatch(path, pattern):
                return False
        
        return True
    
    def _get_or_create_file(self, session, path: str, current_commit: str) -> Optional[File]:
        """Get existing file record or create new one"""
        try:
            # Get file SHA
            file_sha = self.repo.get_file_sha(path, current_commit)
            if not file_sha:
                logger.warning(f"Could not get SHA for {path}")
                return None
            
            # Check if file exists in database
            file_record = session.query(File).filter(File.path == path).first()
            
            if file_record:
                # Check if file changed
                if file_record.sha == file_sha:
                    logger.debug(f"File {path} unchanged, skipping")
                    return None
                
                # Update existing record
                file_record.sha = file_sha
                file_record.last_seen_commit = current_commit
                file_record.status = "active"
            else:
                # Create new file record
                # Extract title from file content
                title = self._extract_file_title(path)
                
                file_record = File(
                    path=path,
                    sha=file_sha,
                    title=title,
                    last_seen_commit=current_commit,
                    status="active"
                )
                session.add(file_record)
                session.flush()  # Get ID
            
            logger.debug(f"File {path} needs analysis (SHA: {file_sha[:8]})")
            return file_record
            
        except Exception as e:
            logger.error(f"Error processing file {path}: {e}")
            return None
    
    def _mark_file_deleted(self, session, path: str):
        """Mark a file as deleted"""
        file_record = session.query(File).filter(File.path == path).first()
        if file_record:
            file_record.status = "deleted"
            logger.info(f"Marked file {path} as deleted")
    
    def _extract_file_title(self, path: str) -> Optional[str]:
        """Extract title from file content"""
        try:
            content = self.repo.get_file_content(path)
            if not content:
                return None
            
            # Simple title extraction
            lines = content.split('\n')
            
            # Look for frontmatter title
            if lines[0].strip() == '---':
                for line in lines[1:10]:  # Check first 10 lines
                    if line.strip() == '---':
                        break
                    if line.strip().startswith('title:'):
                        title = line.split('title:', 1)[1].strip()
                        return title.strip('"\'')
            
            # Look for first H1
            for line in lines[:20]:  # Check first 20 lines
                if line.strip().startswith('# '):
                    return line.strip()[2:]
            
            # Fallback: use filename
            return Path(path).stem.replace('-', ' ').replace('_', ' ').title()
            
        except Exception as e:
            logger.warning(f"Could not extract title from {path}: {e}")
            return None
    
    def get_file_content(self, path: str) -> Optional[str]:
        """Get content of a file"""
        return self.repo.get_file_content(path)
    
    def get_file_lines(self, path: str, start_line: int = None, end_line: int = None) -> Optional[List[str]]:
        """Get specific lines from a file"""
        content = self.get_file_content(path)
        if not content:
            return None
        
        lines = content.split('\n')
        
        if start_line is not None and end_line is not None:
            # Convert to 0-based indexing
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            return lines[start_idx:end_idx]
        
        return lines