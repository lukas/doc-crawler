import os
import pickle
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import hashlib
from dataclasses import dataclass

try:
    import numpy as np
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    np = None
    faiss = None

import openai

from ..core.config import get_openai_api_key
from ..core.chunker import DocumentChunk

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    chunk_id: str
    similarity_score: float
    chunk_data: Dict[str, Any]


class EmbeddingService:
    """Service for creating and querying document embeddings using FAISS"""
    
    def __init__(self, model_name: str = "text-embedding-3-small", 
                 index_path: str = ".cache/faiss", dimensions: int = 1536):
        if not FAISS_AVAILABLE:
            raise ImportError("FAISS and numpy are required for embeddings. Install with: pip install faiss-cpu numpy")
        
        self.model_name = model_name
        self.index_path = Path(index_path)
        self.dimensions = dimensions
        
        # Initialize OpenAI client
        api_key = get_openai_api_key()
        if not api_key:
            raise ValueError("OpenAI API key is required for embeddings")
        
        self.client = openai.AsyncOpenAI(api_key=api_key)
        
        # FAISS index and metadata
        self.index: Optional[faiss.Index] = None
        self.chunk_metadata: Dict[int, Dict[str, Any]] = {}
        self.chunk_id_to_index: Dict[str, int] = {}
        
        # Ensure index directory exists
        self.index_path.mkdir(parents=True, exist_ok=True)
        
        # Load existing index if available
        self._load_index()
    
    def _load_index(self):
        """Load existing FAISS index and metadata from disk"""
        index_file = self.index_path / "index.faiss"
        metadata_file = self.index_path / "metadata.pkl"
        
        try:
            if index_file.exists() and metadata_file.exists():
                # Load FAISS index
                self.index = faiss.read_index(str(index_file))
                
                # Load metadata
                with open(metadata_file, 'rb') as f:
                    data = pickle.load(f)
                    self.chunk_metadata = data['chunk_metadata']
                    self.chunk_id_to_index = data['chunk_id_to_index']
                
                logger.info(f"Loaded existing index with {self.index.ntotal} vectors")
            else:
                # Create new index
                self.index = faiss.IndexFlatIP(self.dimensions)  # Inner product for cosine similarity
                logger.info("Created new FAISS index")
                
        except Exception as e:
            logger.error(f"Error loading index: {e}")
            # Fallback: create new index
            self.index = faiss.IndexFlatIP(self.dimensions)
            self.chunk_metadata = {}
            self.chunk_id_to_index = {}
    
    def _save_index(self):
        """Save FAISS index and metadata to disk"""
        try:
            index_file = self.index_path / "index.faiss"
            metadata_file = self.index_path / "metadata.pkl"
            
            # Save FAISS index
            faiss.write_index(self.index, str(index_file))
            
            # Save metadata
            data = {
                'chunk_metadata': self.chunk_metadata,
                'chunk_id_to_index': self.chunk_id_to_index
            }
            with open(metadata_file, 'wb') as f:
                pickle.dump(data, f)
            
            logger.info(f"Saved index with {self.index.ntotal} vectors")
            
        except Exception as e:
            logger.error(f"Error saving index: {e}")
    
    async def create_embedding(self, text: str) -> np.ndarray:
        """Create embedding for text using OpenAI API"""
        try:
            response = await self.client.embeddings.create(
                model=self.model_name,
                input=text,
                encoding_format="float"
            )
            
            embedding = np.array(response.data[0].embedding, dtype=np.float32)
            
            # Normalize for cosine similarity
            embedding = embedding / np.linalg.norm(embedding)
            
            return embedding
            
        except Exception as e:
            logger.error(f"Error creating embedding: {e}")
            raise
    
    async def add_chunks(self, chunks: List[DocumentChunk], force_rebuild: bool = False):
        """Add document chunks to the index"""
        new_chunks = []
        
        # Check which chunks need to be added/updated
        for chunk in chunks:
            chunk_hash = self._get_chunk_hash(chunk)
            
            # Skip if chunk hasn't changed and we're not forcing rebuild
            if (not force_rebuild and 
                chunk.chunk_id in self.chunk_id_to_index and
                self.chunk_metadata.get(self.chunk_id_to_index[chunk.chunk_id], {}).get('hash') == chunk_hash):
                logger.debug(f"Skipping unchanged chunk: {chunk.chunk_id}")
                continue
            
            new_chunks.append((chunk, chunk_hash))
        
        if not new_chunks:
            logger.info("No new chunks to add")
            return
        
        logger.info(f"Adding {len(new_chunks)} chunks to index")
        
        # Create embeddings for new chunks
        embeddings = []
        chunk_data = []
        
        for chunk, chunk_hash in new_chunks:
            try:
                # Use rendered text for embedding
                embedding = await self.create_embedding(chunk.rendered_text)
                embeddings.append(embedding)
                
                # Prepare metadata
                metadata = {
                    'chunk_id': chunk.chunk_id,
                    'file_path': chunk.file_path,
                    'start_line': chunk.start_line,
                    'end_line': chunk.end_line,
                    'heading_context': chunk.heading_context,
                    'token_count': chunk.token_count,
                    'metadata': chunk.metadata,
                    'hash': chunk_hash,
                    'content_preview': chunk.rendered_text[:200]
                }
                chunk_data.append(metadata)
                
            except Exception as e:
                logger.error(f"Error processing chunk {chunk.chunk_id}: {e}")
                continue
        
        if embeddings:
            # Add to FAISS index
            embeddings_array = np.vstack(embeddings)
            start_index = self.index.ntotal
            
            self.index.add(embeddings_array)
            
            # Update metadata
            for i, metadata in enumerate(chunk_data):
                index_id = start_index + i
                self.chunk_metadata[index_id] = metadata
                self.chunk_id_to_index[metadata['chunk_id']] = index_id
            
            # Save to disk
            self._save_index()
            
            logger.info(f"Successfully added {len(embeddings)} chunks to index")
    
    async def query_similar_chunks(self, query_text: str, k: int = 5, 
                                 file_path_filter: Optional[str] = None) -> List[EmbeddingResult]:
        """Query for similar chunks"""
        try:
            if self.index.ntotal == 0:
                logger.info("Index is empty")
                return []
            
            # Create embedding for query
            query_embedding = await self.create_embedding(query_text)
            query_array = query_embedding.reshape(1, -1)
            
            # Search in FAISS index (get more results for filtering)
            search_k = min(k * 3, self.index.ntotal)
            similarities, indices = self.index.search(query_array, search_k)
            
            results = []
            for similarity, index in zip(similarities[0], indices[0]):
                if index == -1:  # FAISS returns -1 for invalid indices
                    continue
                
                metadata = self.chunk_metadata.get(index, {})
                if not metadata:
                    continue
                
                # Apply file path filter if specified
                if file_path_filter and file_path_filter not in metadata.get('file_path', ''):
                    continue
                
                results.append(EmbeddingResult(
                    chunk_id=metadata['chunk_id'],
                    similarity_score=float(similarity),
                    chunk_data=metadata
                ))
            
            # Return top k results
            results = sorted(results, key=lambda x: x.similarity_score, reverse=True)
            return results[:k]
            
        except Exception as e:
            logger.error(f"Error querying similar chunks: {e}")
            return []
    
    async def query_similar_to_chunk(self, chunk: DocumentChunk, k: int = 5) -> List[EmbeddingResult]:
        """Find chunks similar to a given chunk"""
        return await self.query_similar_chunks(chunk.rendered_text, k)
    
    def remove_chunks(self, chunk_ids: List[str]):
        """Remove chunks from index (by rebuilding without them)"""
        if not chunk_ids:
            return
        
        # Get indices to remove
        indices_to_remove = set()
        for chunk_id in chunk_ids:
            if chunk_id in self.chunk_id_to_index:
                indices_to_remove.add(self.chunk_id_to_index[chunk_id])
        
        if not indices_to_remove:
            logger.info("No chunks to remove")
            return
        
        # Rebuild index without removed chunks
        logger.info(f"Removing {len(indices_to_remove)} chunks from index")
        
        # Get all vectors except those being removed
        all_vectors = []
        new_metadata = {}
        new_chunk_id_to_index = {}
        new_index = 0
        
        for old_index in range(self.index.ntotal):
            if old_index not in indices_to_remove:
                vector = self.index.reconstruct(old_index)
                all_vectors.append(vector)
                
                # Update metadata with new index
                if old_index in self.chunk_metadata:
                    metadata = self.chunk_metadata[old_index]
                    new_metadata[new_index] = metadata
                    new_chunk_id_to_index[metadata['chunk_id']] = new_index
                    new_index += 1
        
        # Create new index
        if all_vectors:
            new_faiss_index = faiss.IndexFlatIP(self.dimensions)
            vectors_array = np.vstack(all_vectors)
            new_faiss_index.add(vectors_array)
            
            self.index = new_faiss_index
            self.chunk_metadata = new_metadata
            self.chunk_id_to_index = new_chunk_id_to_index
        else:
            # Empty index
            self.index = faiss.IndexFlatIP(self.dimensions)
            self.chunk_metadata = {}
            self.chunk_id_to_index = {}
        
        self._save_index()
        logger.info(f"Index rebuilt with {self.index.ntotal} vectors")
    
    def _get_chunk_hash(self, chunk: DocumentChunk) -> str:
        """Get a hash for the chunk to detect changes"""
        content = f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}:{chunk.rendered_text}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the current index"""
        return {
            'total_chunks': self.index.ntotal if self.index else 0,
            'dimensions': self.dimensions,
            'model_name': self.model_name,
            'index_path': str(self.index_path),
            'files_indexed': len(set(
                metadata.get('file_path', '') 
                for metadata in self.chunk_metadata.values()
            )) if self.chunk_metadata else 0
        }
    
    def clear_index(self):
        """Clear the entire index"""
        self.index = faiss.IndexFlatIP(self.dimensions)
        self.chunk_metadata = {}
        self.chunk_id_to_index = {}
        self._save_index()
        logger.info("Index cleared")


# Global embedding service instance
embedding_service: Optional[EmbeddingService] = None


def get_embedding_service(model_name: str = "text-embedding-3-small", 
                         index_path: str = ".cache/faiss") -> EmbeddingService:
    """Get or create global embedding service instance"""
    global embedding_service
    
    if embedding_service is None:
        embedding_service = EmbeddingService(
            model_name=model_name,
            index_path=index_path
        )
    
    return embedding_service