import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import openai
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, ValidationError

from core.schemas import LLMResponse, LLMSuggestion, Citation
from core.config import get_openai_api_key

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    OPENAI = "openai"
    AZURE = "azure"
    LOCAL = "local"


@dataclass
class LLMConfig:
    provider: LLMProvider
    model: str
    temperature: float = 0.1
    max_output_tokens: int = 1200
    json_mode: bool = True
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 60


class LLMClient:
    """Provider-agnostic LLM client with JSON schema validation"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: Optional[Any] = None
        self._rate_limiter = asyncio.Semaphore(10)  # Basic rate limiting
        
        self._setup_client()
    
    def _setup_client(self):
        """Setup the appropriate client based on provider"""
        if self.config.provider == LLMProvider.OPENAI:
            api_key = self.config.api_key or get_openai_api_key()
            if not api_key:
                raise ValueError("OpenAI API key is required")
            
            self._client = openai.AsyncOpenAI(
                api_key=api_key,
                timeout=self.config.timeout
            )
        elif self.config.provider == LLMProvider.AZURE:
            # Azure OpenAI setup
            api_key = self.config.api_key or get_openai_api_key()
            if not api_key or not self.config.base_url:
                raise ValueError("Azure API key and base URL are required")
            
            self._client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout
            )
        elif self.config.provider == LLMProvider.LOCAL:
            # Local LLM setup (e.g., Ollama)
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url or "http://localhost:11434",
                timeout=self.config.timeout
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.config.provider}")
    
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def generate_suggestions(self, prompt: str, context: Dict[str, Any]) -> LLMResponse:
        """Generate suggestions for document improvement"""
        async with self._rate_limiter:
            try:
                if self.config.provider in [LLMProvider.OPENAI, LLMProvider.AZURE]:
                    return await self._openai_generate(prompt, context)
                elif self.config.provider == LLMProvider.LOCAL:
                    return await self._local_generate(prompt, context)
                else:
                    raise ValueError(f"Unsupported provider: {self.config.provider}")
            
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                # Return empty response on failure
                return LLMResponse(suggestions=[], notes=f"Generation failed: {str(e)}")
    
    async def _openai_generate(self, prompt: str, context: Dict[str, Any]) -> LLMResponse:
        """Generate using OpenAI/Azure API"""
        messages = [
            {
                "role": "system",
                "content": self._get_system_prompt()
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        request_kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens
        }
        
        # Enable JSON mode if supported and requested
        if self.config.json_mode and "gpt-4" in self.config.model.lower():
            request_kwargs["response_format"] = {"type": "json_object"}
        
        try:
            response = await self._client.chat.completions.create(**request_kwargs)
            
            content = response.choices[0].message.content
            usage = response.usage
            
            # Log token usage
            logger.info(f"LLM tokens: {usage.prompt_tokens} in, {usage.completion_tokens} out")
            
            # Parse and validate JSON response
            return self._parse_and_validate_response(content)
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    async def _local_generate(self, prompt: str, context: Dict[str, Any]) -> LLMResponse:
        """Generate using local LLM (e.g., Ollama)"""
        try:
            payload = {
                "model": self.config.model,
                "prompt": f"{self._get_system_prompt()}\n\nUser: {prompt}",
                "stream": False,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_output_tokens
                }
            }
            
            response = await self._client.post("/api/generate", json=payload)
            response.raise_for_status()
            
            result = response.json()
            content = result.get("response", "")
            
            return self._parse_and_validate_response(content)
            
        except Exception as e:
            logger.error(f"Local LLM error: {e}")
            raise
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the LLM"""
        return """You are a careful technical editor for the Weights & Biases (W&B) Guides.
Propose MINIMAL, SAFE edits in Markdown source:
- Fix spelling/grammar (code-aware; do not change code).
- Improve clarity without changing meaning.
- Flag accuracy issues ONLY if grounded by provided citations (repo text, catalogs, or explicit facts).
- Respect code fences/inline code; suggest code fixes only when supported by catalogs.
Output VALID JSON conforming to the response schema. Include citations for accuracy claims.
RULES:
- NEVER fabricate facts; if uncertain, emit a "question" suggestion.
- DO NOT change code unless catalogs justify it.
- Keep markdown structure intact.
Return JSON only."""
    
    def _parse_and_validate_response(self, content: str) -> LLMResponse:
        """Parse and validate LLM response"""
        try:
            # Try to extract JSON if it's wrapped in markdown code blocks
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                if end != -1:
                    content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.rfind("```")
                if end != -1 and end > start:
                    content = content[start:end].strip()
            
            # Parse JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON response: {e}")
                logger.debug(f"Content: {content[:500]}...")
                
                # Try to fix common JSON issues
                content = self._fix_common_json_issues(content)
                data = json.loads(content)
            
            # Validate with Pydantic
            response = LLMResponse(**data)
            
            logger.info(f"Successfully parsed {len(response.suggestions)} suggestions")
            return response
            
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Failed to parse/validate LLM response: {e}")
            logger.debug(f"Raw content: {content}")
            
            # Return empty response with error note
            return LLMResponse(
                suggestions=[],
                notes=f"Failed to parse LLM response: {str(e)}"
            )
    
    def _fix_common_json_issues(self, content: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove any text before first {
        first_brace = content.find('{')
        if first_brace > 0:
            content = content[first_brace:]
        
        # Remove any text after last }
        last_brace = content.rfind('}')
        if last_brace != -1 and last_brace < len(content) - 1:
            content = content[:last_brace + 1]
        
        # Fix trailing commas (basic)
        content = content.replace(',]', ']').replace(',}', '}')
        
        return content
    
    def build_context_prompt(self, chunk_text: str, context_text: str, 
                           retrieved_snippets: List[Dict[str, Any]],
                           facts: Dict[str, Any], file_path: str,
                           start_line: int, end_line: int) -> str:
        """Build the complete context prompt for the LLM"""
        
        prompt_parts = [
            f"CURRENT FILE: {file_path}",
            f"LINES: {start_line}-{end_line}",
            "",
            "CHUNK:",
            "<<<",
            chunk_text,
            ">>>",
            "",
            "SURROUNDING CONTEXT (read-only):",
            "<<<",
            context_text,
            ">>>"
        ]
        
        if retrieved_snippets:
            prompt_parts.extend([
                "",
                "RETRIEVED SNIPPETS (read-only):",
            ])
            for snippet in retrieved_snippets:
                prompt_parts.append(f"- {snippet.get('path', 'unknown')} (lines {snippet.get('lines', 'unknown')}): {snippet.get('text', '')[:200]}...")
        
        prompt_parts.extend([
            "",
            "FACTS:",
        ])
        
        for key, value in facts.items():
            if isinstance(value, list):
                prompt_parts.append(f"- {key} = {value}")
            else:
                prompt_parts.append(f"- {key} = {value}")
        
        prompt_parts.extend([
            "",
            "Return JSON only."
        ])
        
        return "\n".join(prompt_parts)
    
    async def close(self):
        """Close the client connection"""
        if hasattr(self._client, 'close'):
            await self._client.close()


# Factory function
def create_llm_client(provider: str, model: str, **kwargs) -> LLMClient:
    """Create an LLM client with the specified configuration"""
    config = LLMConfig(
        provider=LLMProvider(provider),
        model=model,
        **kwargs
    )
    return LLMClient(config)


# Response schema for validation
LLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "rule_code", "severity", "confidence", "title", "description", 
                           "file_path", "line_start", "line_end", "original_snippet", "proposed_snippet", 
                           "citations", "tags"],
                "properties": {
                    "type": {"enum": ["text_edit", "code_edit", "delete", "insert", "question"]},
                    "rule_code": {"enum": ["LLM_SPELL", "LLM_GRAMMAR", "LLM_CLARITY", "LLM_ACCURACY", "LLM_CONSISTENCY", "LLM_UNSURE"]},
                    "severity": {"enum": ["low", "medium", "high", "critical"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "file_path": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "original_snippet": {"type": "string"},
                    "proposed_snippet": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "type": {"enum": ["file", "catalog", "fact"]},
                                "path": {"type": "string"},
                                "line_start": {"type": "integer"},
                                "line_end": {"type": "integer"},
                                "source": {"type": "string"},
                                "key": {"type": "string"},
                                "value": {"type": "string"}
                            }
                        }
                    },
                    "tags": {"type": "array", "items": {"type": "string"}}
                }
            }
        },
        "notes": {"type": "string"}
    },
    "required": ["suggestions"]
}