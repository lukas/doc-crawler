import re
import logging
from typing import List, Dict, Any, Optional, Set
from ...core.mdx_parse import MDXDocument
from ...core.schemas import IssueCreate, IssueSeverity
from ...core.catalogs import catalog_loader

logger = logging.getLogger(__name__)


class APICliAnalyzer:
    """Analyzer for checking API/CLI usage against catalogs"""
    
    def __init__(self):
        self.catalog_loader = catalog_loader
    
    def analyze_document(self, doc: MDXDocument, file_id: int, run_id: int) -> List[IssueCreate]:
        """Analyze API/CLI usage in a document"""
        issues = []
        
        try:
            # Extract code symbols from document
            symbols = doc.extract_code_symbols()
            
            # Check API calls
            api_issues = self._check_api_calls(symbols, doc, file_id, run_id)
            issues.extend(api_issues)
            
            # Check CLI commands
            cli_issues = self._check_cli_commands(symbols, doc, file_id, run_id)
            issues.extend(cli_issues)
            
        except Exception as e:
            logger.error(f"Error analyzing API/CLI in {doc.filepath}: {e}")
        
        return issues
    
    def _check_api_calls(self, symbols: List[Dict[str, Any]], doc: MDXDocument, 
                        file_id: int, run_id: int) -> List[IssueCreate]:
        """Check API calls against catalog"""
        issues = []
        
        api_symbols = [s for s in symbols if s['type'] in ['api_call', 'inline_api']]
        
        for symbol_info in api_symbols:
            symbol = symbol_info['symbol']
            
            # Check if symbol exists in catalog
            catalog_info = self.catalog_loader.get_api_info(symbol)
            
            if not catalog_info:
                # Symbol not found in catalog
                issue = self._create_unknown_api_issue(symbol_info, doc, file_id, run_id)
                if issue:
                    issues.append(issue)
            else:
                # Check if deprecated
                deprecation_info = self.catalog_loader.is_deprecated(symbol, "api")
                if deprecation_info:
                    issue = self._create_deprecated_api_issue(
                        symbol_info, catalog_info, deprecation_info, doc, file_id, run_id
                    )
                    if issue:
                        issues.append(issue)
        
        return issues
    
    def _check_cli_commands(self, symbols: List[Dict[str, Any]], doc: MDXDocument,
                          file_id: int, run_id: int) -> List[IssueCreate]:
        """Check CLI commands against catalog"""
        issues = []
        
        cli_symbols = [s for s in symbols if s['type'] == 'cli_command']
        
        for symbol_info in cli_symbols:
            # Reconstruct full command
            base_command = f"wandb {symbol_info['command']}"
            
            # Check if command exists in catalog
            catalog_info = self.catalog_loader.get_cli_info(base_command)
            
            if not catalog_info:
                # Command not found in catalog
                issue = self._create_unknown_cli_issue(symbol_info, doc, file_id, run_id)
                if issue:
                    issues.append(issue)
            else:
                # Check if deprecated
                deprecation_info = self.catalog_loader.is_deprecated(base_command, "cli")
                if deprecation_info:
                    issue = self._create_deprecated_cli_issue(
                        symbol_info, catalog_info, deprecation_info, doc, file_id, run_id
                    )
                    if issue:
                        issues.append(issue)
        
        return issues
    
    def _create_unknown_api_issue(self, symbol_info: Dict[str, Any], doc: MDXDocument,
                                 file_id: int, run_id: int) -> Optional[IssueCreate]:
        """Create issue for unknown API symbol"""
        try:
            symbol = symbol_info['symbol']
            
            # Find similar symbols
            similar = self.catalog_loader.find_similar_api_symbols(symbol)
            
            title = f"Unknown API symbol: {symbol}"
            description = f"The API symbol '{symbol}' is not found in the W&B API catalog."
            
            if similar:
                description += f" Did you mean: {', '.join(similar)}?"
            
            evidence = {
                'symbol': symbol,
                'symbol_type': symbol_info['type'],
                'language': symbol_info.get('language', 'unknown'),
                'similar_symbols': similar,
                'all_valid_symbols': self.catalog_loader.get_all_api_symbols()[:20]  # Limit for size
            }
            
            # Get context around the symbol
            context = self._get_symbol_context(doc, symbol_info['line'])
            
            return IssueCreate(
                file_id=file_id,
                rule_code="API_UNKNOWN",
                severity=IssueSeverity.MEDIUM,
                title=title,
                description=description,
                snippet=context,
                line_start=symbol_info['line'],
                line_end=symbol_info['line'],
                evidence=evidence,
                provenance=["rule"],
                can_auto_apply=False,  # Unknown APIs need manual review
                first_seen_run_id=run_id,
                last_seen_run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Error creating unknown API issue: {e}")
            return None
    
    def _create_unknown_cli_issue(self, symbol_info: Dict[str, Any], doc: MDXDocument,
                                 file_id: int, run_id: int) -> Optional[IssueCreate]:
        """Create issue for unknown CLI command"""
        try:
            command = f"wandb {symbol_info['command']}"
            
            # Find similar commands
            similar = self.catalog_loader.find_similar_cli_commands(command)
            
            title = f"Unknown CLI command: {command}"
            description = f"The CLI command '{command}' is not found in the W&B CLI catalog."
            
            if similar:
                description += f" Did you mean: {', '.join(similar)}?"
            
            evidence = {
                'command': command,
                'base_command': symbol_info['command'],
                'similar_commands': similar,
                'all_valid_commands': self.catalog_loader.get_all_cli_commands()[:20]
            }
            
            context = self._get_symbol_context(doc, symbol_info['line'])
            
            return IssueCreate(
                file_id=file_id,
                rule_code="CLI_UNKNOWN",
                severity=IssueSeverity.MEDIUM,
                title=title,
                description=description,
                snippet=context,
                line_start=symbol_info['line'],
                line_end=symbol_info['line'],
                evidence=evidence,
                provenance=["rule"],
                can_auto_apply=False,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Error creating unknown CLI issue: {e}")
            return None
    
    def _create_deprecated_api_issue(self, symbol_info: Dict[str, Any], catalog_info: Dict[str, Any],
                                   deprecation_info: Dict[str, Any], doc: MDXDocument,
                                   file_id: int, run_id: int) -> Optional[IssueCreate]:
        """Create issue for deprecated API symbol"""
        try:
            symbol = symbol_info['symbol']
            
            title = f"Deprecated API: {symbol}"
            description = f"The API symbol '{symbol}' is deprecated."
            
            if deprecation_info.get('reason'):
                description += f" Reason: {deprecation_info['reason']}"
            
            if deprecation_info.get('replacement'):
                description += f" Use '{deprecation_info['replacement']}' instead."
            
            evidence = {
                'symbol': symbol,
                'deprecation_reason': deprecation_info.get('reason'),
                'replacement': deprecation_info.get('replacement'),
                'deprecated_since': deprecation_info.get('deprecated_since'),
                'catalog_info': catalog_info
            }
            
            context = self._get_symbol_context(doc, symbol_info['line'])
            
            # If we have a replacement, we might be able to suggest a patch
            proposed_snippet = None
            if deprecation_info.get('replacement'):
                proposed_snippet = context.replace(symbol, deprecation_info['replacement'])
            
            return IssueCreate(
                file_id=file_id,
                rule_code="API_DEPRECATED",
                severity=IssueSeverity.HIGH,
                title=title,
                description=description,
                snippet=context,
                proposed_snippet=proposed_snippet,
                line_start=symbol_info['line'],
                line_end=symbol_info['line'],
                evidence=evidence,
                provenance=["rule"],
                can_auto_apply=bool(proposed_snippet and proposed_snippet != context),
                first_seen_run_id=run_id,
                last_seen_run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Error creating deprecated API issue: {e}")
            return None
    
    def _create_deprecated_cli_issue(self, symbol_info: Dict[str, Any], catalog_info: Dict[str, Any],
                                   deprecation_info: Dict[str, Any], doc: MDXDocument,
                                   file_id: int, run_id: int) -> Optional[IssueCreate]:
        """Create issue for deprecated CLI command"""
        try:
            command = f"wandb {symbol_info['command']}"
            
            title = f"Deprecated CLI command: {command}"
            description = f"The CLI command '{command}' is deprecated."
            
            if deprecation_info.get('reason'):
                description += f" Reason: {deprecation_info['reason']}"
            
            if deprecation_info.get('replacement'):
                description += f" Use '{deprecation_info['replacement']}' instead."
            
            evidence = {
                'command': command,
                'deprecation_reason': deprecation_info.get('reason'),
                'replacement': deprecation_info.get('replacement'),
                'deprecated_since': deprecation_info.get('deprecated_since'),
                'catalog_info': catalog_info
            }
            
            context = self._get_symbol_context(doc, symbol_info['line'])
            
            # If we have a replacement, suggest a patch
            proposed_snippet = None
            if deprecation_info.get('replacement'):
                proposed_snippet = context.replace(command, deprecation_info['replacement'])
            
            return IssueCreate(
                file_id=file_id,
                rule_code="CLI_DEPRECATED",
                severity=IssueSeverity.HIGH,
                title=title,
                description=description,
                snippet=context,
                proposed_snippet=proposed_snippet,
                line_start=symbol_info['line'],
                line_end=symbol_info['line'],
                evidence=evidence,
                provenance=["rule"],
                can_auto_apply=bool(proposed_snippet and proposed_snippet != context),
                first_seen_run_id=run_id,
                last_seen_run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Error creating deprecated CLI issue: {e}")
            return None
    
    def _get_symbol_context(self, doc: MDXDocument, line_num: int, context_lines: int = 2) -> str:
        """Get context around a symbol"""
        lines = doc.body_content.split('\n')
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        
        return '\n'.join(lines[start:end])


# Convenience function
def analyze_api_cli(doc: MDXDocument, file_id: int, run_id: int, config: Dict[str, Any] = None) -> List[IssueCreate]:
    """Analyze API/CLI usage in a document"""
    analyzer = APICliAnalyzer()
    return analyzer.analyze_document(doc, file_id, run_id)