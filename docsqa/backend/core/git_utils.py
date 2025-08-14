import os
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from git import Repo, InvalidGitRepositoryError
import logging

logger = logging.getLogger(__name__)


class GitRepository:
    def __init__(self, repo_path: str, repo_url: str, branch: str = "main"):
        self.repo_path = Path(repo_path)
        self.repo_url = repo_url
        self.branch = branch
        self._repo: Optional[Repo] = None
    
    @property
    def repo(self) -> Repo:
        """Get the Git repository instance"""
        if self._repo is None:
            try:
                self._repo = Repo(self.repo_path)
            except InvalidGitRepositoryError:
                raise ValueError(f"Invalid Git repository at {self.repo_path}")
        return self._repo
    
    def clone_or_update(self) -> str:
        """Clone repository if it doesn't exist, otherwise update it. Returns HEAD commit SHA."""
        if not self.repo_path.exists():
            logger.info(f"Cloning repository {self.repo_url} to {self.repo_path}")
            self._repo = Repo.clone_from(self.repo_url, self.repo_path)
        else:
            logger.info(f"Updating existing repository at {self.repo_path}")
            self._repo = Repo(self.repo_path)
        
        # Fetch latest changes and reset to origin/branch
        origin = self.repo.remote('origin')
        origin.fetch()
        
        # Checkout and reset to origin/branch
        if self.branch not in [head.name for head in self.repo.heads]:
            # Create local branch tracking origin
            self.repo.create_head(self.branch, f'origin/{self.branch}')
        
        self.repo.git.checkout(self.branch)
        self.repo.git.reset('--hard', f'origin/{self.branch}')
        
        return self.repo.head.commit.hexsha
    
    def get_changed_files(self, from_commit: str, to_commit: str = "HEAD") -> List[Dict[str, str]]:
        """Get list of changed files between two commits"""
        try:
            # Use git diff --name-status to get changed files
            diff_output = self.repo.git.diff('--name-status', f'{from_commit}..{to_commit}')
            
            changed_files = []
            for line in diff_output.split('\n'):
                if not line.strip():
                    continue
                
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    status = parts[0]
                    filepath = parts[1]
                    
                    # Handle renames (R100 or similar)
                    if status.startswith('R') and len(parts) >= 3:
                        old_filepath = filepath
                        filepath = parts[2]
                        changed_files.append({
                            'status': status,
                            'path': filepath,
                            'old_path': old_filepath
                        })
                    else:
                        changed_files.append({
                            'status': status,
                            'path': filepath
                        })
            
            return changed_files
        except Exception as e:
            logger.error(f"Error getting changed files: {e}")
            return []
    
    def get_file_content(self, filepath: str, commit: str = "HEAD") -> Optional[str]:
        """Get content of a file at a specific commit"""
        try:
            commit_obj = self.repo.commit(commit)
            blob = commit_obj.tree / filepath
            return blob.data_stream.read().decode('utf-8')
        except Exception as e:
            logger.error(f"Error reading file {filepath} at commit {commit}: {e}")
            return None
    
    def get_file_sha(self, filepath: str, commit: str = "HEAD") -> Optional[str]:
        """Get SHA of a file blob at a specific commit"""
        try:
            commit_obj = self.repo.commit(commit)
            blob = commit_obj.tree / filepath
            return blob.hexsha
        except Exception as e:
            logger.error(f"Error getting SHA for file {filepath} at commit {commit}: {e}")
            return None
    
    def get_current_commit(self) -> str:
        """Get current HEAD commit SHA"""
        return self.repo.head.commit.hexsha
    
    def get_commit_info(self, commit_sha: str) -> Dict[str, str]:
        """Get information about a commit"""
        try:
            commit = self.repo.commit(commit_sha)
            return {
                'sha': commit.hexsha,
                'author': str(commit.author),
                'message': commit.message.strip(),
                'date': commit.committed_datetime.isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting commit info for {commit_sha}: {e}")
            return {}
    
    def create_branch(self, branch_name: str, from_commit: str = "HEAD") -> bool:
        """Create a new branch from the specified commit"""
        try:
            # Make sure we're on the main branch first
            self.repo.git.checkout(self.branch)
            
            # Create and checkout new branch
            new_branch = self.repo.create_head(branch_name, from_commit)
            new_branch.checkout()
            return True
        except Exception as e:
            logger.error(f"Error creating branch {branch_name}: {e}")
            return False
    
    def apply_patch(self, patch_content: str) -> bool:
        """Apply a unified diff patch"""
        try:
            # Write patch to temporary file
            patch_file = self.repo_path / 'temp.patch'
            with open(patch_file, 'w') as f:
                f.write(patch_content)
            
            # Apply patch using git apply
            self.repo.git.apply(str(patch_file))
            
            # Remove temporary patch file
            patch_file.unlink()
            return True
        except Exception as e:
            logger.error(f"Error applying patch: {e}")
            if patch_file.exists():
                patch_file.unlink()
            return False
    
    def commit_changes(self, message: str, files: List[str] = None) -> Optional[str]:
        """Commit changes to the repository"""
        try:
            # Add specific files or all changes
            if files:
                for file in files:
                    self.repo.git.add(file)
            else:
                self.repo.git.add('-A')
            
            # Check if there are any changes to commit
            if not self.repo.is_dirty() and not self.repo.untracked_files:
                logger.info("No changes to commit")
                return None
            
            # Commit changes
            commit = self.repo.index.commit(message)
            return commit.hexsha
        except Exception as e:
            logger.error(f"Error committing changes: {e}")
            return None
    
    def push_branch(self, branch_name: str = None) -> bool:
        """Push branch to origin"""
        try:
            branch_to_push = branch_name or self.repo.active_branch.name
            origin = self.repo.remote('origin')
            origin.push(branch_to_push)
            return True
        except Exception as e:
            logger.error(f"Error pushing branch {branch_to_push}: {e}")
            return False
    
    def list_files_matching_patterns(self, include_patterns: List[str], exclude_patterns: List[str] = None) -> List[str]:
        """List files in the repository matching the given patterns"""
        try:
            all_files = []
            
            # Get all tracked files
            for item in self.repo.head.commit.tree.traverse():
                if item.type == 'blob':  # It's a file, not a directory
                    all_files.append(item.path)
            
            # Filter by include patterns
            matching_files = []
            for file_path in all_files:
                # Check include patterns
                for pattern in include_patterns:
                    if self._match_pattern(file_path, pattern):
                        matching_files.append(file_path)
                        break
            
            # Filter out exclude patterns
            if exclude_patterns:
                filtered_files = []
                for file_path in matching_files:
                    exclude = False
                    for pattern in exclude_patterns:
                        if self._match_pattern(file_path, pattern):
                            exclude = True
                            break
                    if not exclude:
                        filtered_files.append(file_path)
                return filtered_files
            
            return matching_files
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []
    
    def _match_pattern(self, filepath: str, pattern: str) -> bool:
        """Simple glob-style pattern matching"""
        import fnmatch
        return fnmatch.fnmatch(filepath, pattern)