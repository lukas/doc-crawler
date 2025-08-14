import httpx
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from packaging import version
import json

logger = logging.getLogger(__name__)


class VersionResolver:
    """Resolves package versions from PyPI and checks for version drift"""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    async def get_latest_version(self, package_name: str) -> Optional[Dict[str, Any]]:
        """Get latest version info for a package from PyPI"""
        if package_name in self._cache:
            return self._cache[package_name]
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                url = f"https://pypi.org/pypi/{package_name}/json"
                response = await client.get(url)
                response.raise_for_status()
                
                data = response.json()
                
                # Extract version info
                latest_version = data['info']['version']
                releases = data['releases']
                
                # Get all version numbers and sort them
                version_list = []
                for ver in releases.keys():
                    try:
                        parsed_ver = version.parse(ver)
                        if not parsed_ver.is_prerelease:  # Skip prereleases
                            version_list.append((ver, parsed_ver))
                    except version.InvalidVersion:
                        continue
                
                version_list.sort(key=lambda x: x[1], reverse=True)
                
                version_info = {
                    'package': package_name,
                    'latest_version': latest_version,
                    'latest_parsed': version.parse(latest_version),
                    'all_versions': [v[0] for v in version_list],
                    'release_date': self._get_release_date(data, latest_version),
                    'summary': data['info']['summary'],
                    'homepage': data['info']['home_page'],
                    'pypi_url': f"https://pypi.org/project/{package_name}/"
                }
                
                self._cache[package_name] = version_info
                return version_info
                
        except Exception as e:
            logger.error(f"Error fetching version info for {package_name}: {e}")
            return None
    
    def _get_release_date(self, pypi_data: Dict, version_str: str) -> Optional[str]:
        """Extract release date for a specific version"""
        try:
            releases = pypi_data.get('releases', {})
            version_releases = releases.get(version_str, [])
            if version_releases:
                return version_releases[0].get('upload_time_iso_8601')
        except (KeyError, IndexError):
            pass
        return None
    
    def check_version_drift(self, found_version: str, latest_info: Dict[str, Any], 
                          allow_majors_behind: int = 0, allow_minors_behind: int = 1) -> Dict[str, Any]:
        """Check if found version is significantly behind latest"""
        try:
            found_parsed = version.parse(found_version)
            latest_parsed = latest_info['latest_parsed']
            
            # Skip prereleases
            if found_parsed.is_prerelease:
                return {'is_outdated': False, 'reason': 'prerelease'}
            
            # Version is newer than latest (shouldn't happen, but handle gracefully)
            if found_parsed > latest_parsed:
                return {
                    'is_outdated': False, 
                    'reason': 'newer_than_latest',
                    'found_version': found_version,
                    'latest_version': latest_info['latest_version']
                }
            
            # Same version
            if found_parsed == latest_parsed:
                return {
                    'is_outdated': False, 
                    'reason': 'current',
                    'found_version': found_version,
                    'latest_version': latest_info['latest_version']
                }
            
            # Check major version difference
            major_diff = latest_parsed.major - found_parsed.major
            if major_diff > allow_majors_behind:
                return {
                    'is_outdated': True,
                    'reason': 'major_behind',
                    'found_version': found_version,
                    'latest_version': latest_info['latest_version'],
                    'major_versions_behind': major_diff,
                    'severity': 'high'
                }
            
            # Check minor version difference (only if major versions match)
            if major_diff == 0:
                minor_diff = latest_parsed.minor - found_parsed.minor
                if minor_diff > allow_minors_behind:
                    return {
                        'is_outdated': True,
                        'reason': 'minor_behind',
                        'found_version': found_version,
                        'latest_version': latest_info['latest_version'],
                        'minor_versions_behind': minor_diff,
                        'severity': 'medium' if minor_diff > 3 else 'low'
                    }
            
            # Version is acceptable
            return {
                'is_outdated': False,
                'reason': 'acceptable',
                'found_version': found_version,
                'latest_version': latest_info['latest_version']
            }
            
        except version.InvalidVersion as e:
            logger.warning(f"Invalid version format '{found_version}': {e}")
            return {
                'is_outdated': False,
                'reason': 'invalid_version',
                'found_version': found_version,
                'error': str(e)
            }
    
    def extract_versions_from_text(self, text: str, package_name: str = "wandb") -> List[Dict[str, Any]]:
        """Extract version references from text"""
        versions_found = []
        lines = text.split('\n')
        
        # Common version patterns
        patterns = [
            # pip install package==version
            rf'pip\s+install\s+{re.escape(package_name)}==([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*(?:[a-zA-Z][0-9]*)?)',
            # requirements.txt style
            rf'{re.escape(package_name)}==([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*(?:[a-zA-Z][0-9]*)?)',
            # Poetry/pipenv style
            rf'"{re.escape(package_name)}"\s*=\s*"([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*)"',
            # Conda install
            rf'conda\s+install\s+{re.escape(package_name)}=([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*)',
            # Version in import comments
            rf'#\s*{re.escape(package_name)}\s+version\s+([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*)',
            # General version mentions
            rf'{re.escape(package_name)}\s+(?:version\s+)?([0-9]+(?:\.[0-9]+)*(?:\.[0-9]+)*)',
        ]
        
        for line_num, line in enumerate(lines, 1):
            for pattern in patterns:
                matches = re.finditer(pattern, line, re.IGNORECASE)
                for match in matches:
                    version_str = match.group(1)
                    versions_found.append({
                        'version': version_str,
                        'line_number': line_num,
                        'line_content': line.strip(),
                        'match_pattern': pattern,
                        'match_start': match.start(),
                        'match_end': match.end()
                    })
        
        return versions_found
    
    def suggest_version_update(self, old_version: str, new_version: str, line_content: str) -> str:
        """Suggest how to update version in a line of text"""
        # Simple replacement - replace old version with new version
        updated_line = line_content.replace(old_version, new_version)
        return updated_line
    
    async def check_package_exists(self, package_name: str) -> bool:
        """Check if a package exists on PyPI"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                url = f"https://pypi.org/pypi/{package_name}/json"
                response = await client.get(url)
                return response.status_code == 200
        except Exception:
            return False