"""Tests for configuration system"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from docsqa.backend.core.config import Settings, Config


def test_config_loading():
    """Test that configuration loads correctly"""
    settings = Settings()
    config = settings.config
    
    assert isinstance(config, Config)
    assert config.repo.url == "https://github.com/wandb/docs.git"
    assert config.repo.branch == "main"
    assert config.server.host == "0.0.0.0"
    assert config.server.port == 8080


def test_environment_variable_override():
    """Test that environment variables override config values"""
    # Set environment variable
    test_db_url = "sqlite:///test.db"
    os.environ["DATABASE_URL"] = test_db_url
    
    try:
        settings = Settings()
        config = settings.config
        # The env var should override the config file
        assert config.db.url == test_db_url
    finally:
        # Clean up
        del os.environ["DATABASE_URL"]


def test_config_with_custom_file():
    """Test loading config from custom file"""
    # Create a temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        test_config = {
            'repo': {
                'url': 'https://github.com/test/repo.git',
                'branch': 'test'
            },
            'db': {
                'url': 'sqlite:///test.db'
            },
            'server': {
                'host': '127.0.0.1',
                'port': 9000
            }
        }
        yaml.dump(test_config, f)
        f.flush()
        
        try:
            settings = Settings(config_path=f.name)
            config = settings.config
            
            assert config.repo.url == 'https://github.com/test/repo.git'
            assert config.repo.branch == 'test'
            assert config.db.url == 'sqlite:///test.db'
            assert config.server.host == '127.0.0.1'
            assert config.server.port == 9000
            
        finally:
            os.unlink(f.name)


def test_config_reload():
    """Test that config can be reloaded"""
    settings = Settings()
    original_url = settings.config.repo.url
    
    # Reload should work without error
    settings.reload()
    assert settings.config.repo.url == original_url


def test_missing_config_file():
    """Test handling of missing config file"""
    with pytest.raises(FileNotFoundError):
        Settings(config_path="/nonexistent/config.yml")