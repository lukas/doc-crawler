import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class CatalogLoader:
    """Loads and manages API/CLI catalogs for reference checking"""
    
    def __init__(self, catalogs_dir: str = "configs/catalogs"):
        self.catalogs_dir = Path(catalogs_dir)
        self._api_catalog: Optional[Dict[str, Any]] = None
        self._cli_catalog: Optional[Dict[str, Any]] = None
    
    def load_api_catalog(self) -> Dict[str, Any]:
        """Load the API catalog"""
        if self._api_catalog is None:
            catalog_file = self.catalogs_dir / "wandb_api.json"
            try:
                with open(catalog_file, 'r') as f:
                    self._api_catalog = json.load(f)
                logger.info(f"Loaded API catalog with {len(self._api_catalog)} entries")
            except Exception as e:
                logger.error(f"Error loading API catalog from {catalog_file}: {e}")
                self._api_catalog = {}
        
        return self._api_catalog
    
    def load_cli_catalog(self) -> Dict[str, Any]:
        """Load the CLI catalog"""
        if self._cli_catalog is None:
            catalog_file = self.catalogs_dir / "wandb_cli.json"
            try:
                with open(catalog_file, 'r') as f:
                    self._cli_catalog = json.load(f)
                logger.info(f"Loaded CLI catalog with {len(self._cli_catalog)} entries")
            except Exception as e:
                logger.error(f"Error loading CLI catalog from {catalog_file}: {e}")
                self._cli_catalog = {}
        
        return self._cli_catalog
    
    def get_api_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get information about an API symbol"""
        catalog = self.load_api_catalog()
        return catalog.get(symbol)
    
    def get_cli_info(self, command: str) -> Optional[Dict[str, Any]]:
        """Get information about a CLI command"""
        catalog = self.load_cli_catalog()
        return catalog.get(command)
    
    def get_all_api_symbols(self) -> List[str]:
        """Get all available API symbols"""
        catalog = self.load_api_catalog()
        return list(catalog.keys())
    
    def get_all_cli_commands(self) -> List[str]:
        """Get all available CLI commands"""
        catalog = self.load_cli_catalog()
        return list(catalog.keys())
    
    def find_similar_api_symbols(self, symbol: str, max_results: int = 5) -> List[str]:
        """Find similar API symbols (fuzzy matching)"""
        all_symbols = self.get_all_api_symbols()
        
        # Simple similarity based on common substrings
        similar = []
        symbol_lower = symbol.lower()
        
        for catalog_symbol in all_symbols:
            catalog_lower = catalog_symbol.lower()
            
            # Exact match
            if symbol_lower == catalog_lower:
                similar.insert(0, catalog_symbol)
            # Contains or is contained
            elif symbol_lower in catalog_lower or catalog_lower in symbol_lower:
                similar.append(catalog_symbol)
            # Starts with same prefix
            elif (len(symbol_lower) > 3 and catalog_lower.startswith(symbol_lower[:4])) or \
                 (len(catalog_lower) > 3 and symbol_lower.startswith(catalog_lower[:4])):
                similar.append(catalog_symbol)
        
        return similar[:max_results]
    
    def find_similar_cli_commands(self, command: str, max_results: int = 5) -> List[str]:
        """Find similar CLI commands"""
        all_commands = self.get_all_cli_commands()
        
        similar = []
        command_lower = command.lower()
        
        for catalog_command in all_commands:
            catalog_lower = catalog_command.lower()
            
            # Exact match
            if command_lower == catalog_lower:
                similar.insert(0, catalog_command)
            # Contains or is contained
            elif command_lower in catalog_lower or catalog_lower in command_lower:
                similar.append(catalog_command)
            # Same first word
            elif (command_lower.split()[0] == catalog_lower.split()[0] if 
                  ' ' in command_lower and ' ' in catalog_lower else False):
                similar.append(catalog_command)
        
        return similar[:max_results]
    
    def is_deprecated(self, symbol_or_command: str, symbol_type: str = "api") -> Optional[Dict[str, Any]]:
        """Check if a symbol or command is deprecated"""
        if symbol_type == "api":
            info = self.get_api_info(symbol_or_command)
        else:
            info = self.get_cli_info(symbol_or_command)
        
        if info and info.get('deprecated'):
            return {
                'is_deprecated': True,
                'reason': info.get('deprecation_reason', 'No reason provided'),
                'replacement': info.get('replacement'),
                'deprecated_since': info.get('deprecated_since')
            }
        
        return None
    
    def get_usage_examples(self, symbol_or_command: str, symbol_type: str = "api") -> List[str]:
        """Get usage examples for a symbol or command"""
        if symbol_type == "api":
            info = self.get_api_info(symbol_or_command)
        else:
            info = self.get_cli_info(symbol_or_command)
        
        if info:
            return info.get('examples', [])
        
        return []
    
    def validate_parameters(self, symbol: str, used_params: List[str]) -> Dict[str, Any]:
        """Validate parameters used with an API symbol"""
        info = self.get_api_info(symbol)
        if not info:
            return {'valid': False, 'reason': 'Symbol not found'}
        
        valid_params = info.get('parameters', [])
        if not valid_params:
            return {'valid': True, 'warnings': []}
        
        warnings = []
        unknown_params = []
        
        for param in used_params:
            if param not in valid_params:
                unknown_params.append(param)
        
        if unknown_params:
            warnings.append(f"Unknown parameters: {', '.join(unknown_params)}")
            similar_params = []
            for param in unknown_params:
                for valid_param in valid_params:
                    if param.lower() in valid_param.lower() or valid_param.lower() in param.lower():
                        similar_params.append(f"{param} -> {valid_param}")
                        break
            
            if similar_params:
                warnings.append(f"Did you mean: {', '.join(similar_params)}")
        
        return {
            'valid': len(unknown_params) == 0,
            'warnings': warnings,
            'unknown_parameters': unknown_params,
            'valid_parameters': valid_params
        }
    
    def reload_catalogs(self):
        """Reload catalogs from disk"""
        self._api_catalog = None
        self._cli_catalog = None
        logger.info("Catalogs reloaded")


# Global catalog loader instance
catalog_loader = CatalogLoader()