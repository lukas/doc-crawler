import logging
from typing import List, Dict, Any, Optional
from ...core.version_resolver import VersionResolver
from ...core.mdx_parse import MDXDocument
from ...core.schemas import IssueCreate, IssueSeverity
from ...core.patches import create_unified_diff

logger = logging.getLogger(__name__)


class VersionAnalyzer:
    """Analyzer for checking package version drift in documentation"""
    
    def __init__(self, package_name: str = "wandb", allow_majors_behind: int = 0, 
                 allow_minors_behind: int = 1):
        self.package_name = package_name
        self.allow_majors_behind = allow_majors_behind
        self.allow_minors_behind = allow_minors_behind
        self.resolver = VersionResolver()
    
    async def analyze_document(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Analyze version references in a document"""
        issues = []
        
        try:
            # Get latest version info
            latest_info = await self.resolver.get_latest_version(self.package_name)
            if not latest_info:
                logger.warning(f"Could not fetch latest version info for {self.package_name}")
                return issues
            
            # Extract version references from document
            versions_found = self.resolver.extract_versions_from_text(
                doc.body_content, self.package_name
            )
            
            if not versions_found:
                return issues
            
            # Check each version reference
            for version_ref in versions_found:
                drift_info = self.resolver.check_version_drift(
                    version_ref['version'], 
                    latest_info,
                    self.allow_majors_behind,
                    self.allow_minors_behind
                )
                
                if drift_info['is_outdated']:
                    issue = self._create_version_issue(
                        version_ref, drift_info, latest_info, doc, file_id, run_id
                    )
                    if issue:
                        issues.append(issue)
        
        except Exception as e:
            logger.error(f"Error analyzing versions in {doc.filepath}: {e}")
        
        return issues
    
    def _create_version_issue(self, version_ref: Dict[str, Any], drift_info: Dict[str, Any],
                            latest_info: Dict[str, Any], doc: MDXDocument, 
                            file_id: int, run_id: int) -> Optional[IssueCreate]:
        """Create an issue for outdated version"""
        try:
            # Determine severity based on drift info
            severity_map = {
                'low': IssueSeverity.LOW,
                'medium': IssueSeverity.MEDIUM,
                'high': IssueSeverity.HIGH
            }
            severity = severity_map.get(drift_info.get('severity', 'medium'), IssueSeverity.MEDIUM)
            
            # Determine rule code
            if drift_info['reason'] == 'major_behind':
                rule_code = "SDKVER_MAJOR"
            elif drift_info['reason'] == 'minor_behind':
                rule_code = "SDKVER_MINOR"
            else:
                rule_code = "SDKVER_OLD"
            
            # Create title and description
            found_version = drift_info['found_version']
            latest_version = drift_info['latest_version']
            
            title = f"Outdated {self.package_name} version: {found_version}"
            
            description = f"Documentation references {self.package_name}=={found_version}, but the latest version is {latest_version}."
            
            if drift_info['reason'] == 'major_behind':
                major_diff = drift_info['major_versions_behind']
                description += f" This is {major_diff} major version{'s' if major_diff > 1 else ''} behind."
            elif drift_info['reason'] == 'minor_behind':
                minor_diff = drift_info['minor_versions_behind']
                description += f" This is {minor_diff} minor version{'s' if minor_diff > 1 else ''} behind."
            
            # Add suggestion for update
            suggested_line = self.resolver.suggest_version_update(
                found_version, latest_version, version_ref['line_content']
            )
            
            # Create patch if the suggestion is different
            can_auto_apply = False
            suggested_patch = None
            proposed_snippet = None
            
            if suggested_line != version_ref['line_content']:
                proposed_snippet = suggested_line
                
                # Create unified diff patch
                original_lines = doc.body_content.split('\n')
                line_idx = version_ref['line_number'] - 1
                
                if 0 <= line_idx < len(original_lines):
                    modified_lines = original_lines.copy()
                    modified_lines[line_idx] = suggested_line
                    
                    suggested_patch = create_unified_diff(
                        '\n'.join(original_lines),
                        '\n'.join(modified_lines),
                        doc.filepath,
                        f"{doc.filepath} (updated)"
                    )
                    
                    # Simple version updates can often be auto-applied
                    can_auto_apply = self._is_safe_version_update(
                        version_ref['line_content'], suggested_line
                    )
            
            # Evidence
            evidence = {
                'found_version': found_version,
                'latest_version': latest_version,
                'package_name': self.package_name,
                'versions_behind': drift_info.get('major_versions_behind') or drift_info.get('minor_versions_behind', 0),
                'drift_reason': drift_info['reason'],
                'severity_reason': drift_info.get('severity', 'medium'),
                'line_content': version_ref['line_content'],
                'pypi_url': latest_info.get('pypi_url', ''),
                'latest_release_date': latest_info.get('release_date', '')
            }
            
            return IssueCreate(
                file_id=file_id,
                rule_code=rule_code,
                severity=severity,
                title=title,
                description=description,
                snippet=version_ref['line_content'],
                line_start=version_ref['line_number'],
                line_end=version_ref['line_number'],
                evidence=evidence,
                proposed_snippet=proposed_snippet,
                suggested_patch=suggested_patch,
                provenance=["rule"],
                can_auto_apply=can_auto_apply,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Error creating version issue: {e}")
            return None
    
    def _is_safe_version_update(self, original_line: str, updated_line: str) -> bool:
        """Determine if a version update is safe to auto-apply"""
        # Simple heuristic: if only the version number changed, it's probably safe
        import re
        
        # Remove version numbers and see if the rest is identical
        version_pattern = r'[0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*(?:[a-zA-Z][0-9]*)?'
        
        original_no_version = re.sub(version_pattern, 'VERSION', original_line)
        updated_no_version = re.sub(version_pattern, 'VERSION', updated_line)
        
        return original_no_version == updated_no_version


# Convenience function
async def analyze_versions(doc: MDXDocument, file_id: int, run_id: int, config: Dict[str, Any] = None) -> List[IssueCreate]:
    """Analyze version drift in a document"""
    analyzer_config = config or {}
    
    analyzer = VersionAnalyzer(
        package_name=analyzer_config.get('package', 'wandb'),
        allow_majors_behind=analyzer_config.get('allow_majors_behind', 0),
        allow_minors_behind=analyzer_config.get('allow_minors_behind', 1)
    )
    
    return await analyzer.analyze_document(doc, file_id, run_id)