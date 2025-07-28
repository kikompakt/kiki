"""
KnowledgeManager für Intelligentes KI-Kursstudio
Custom RAG-System mit lokaler Vektor-Datenbank

Features:
- File-Upload: PDF, TXT, DOCX
- Text-Extraktion und intelligente Chunking
- Sentence-Transformers für Embeddings (Open Source)
- ChromaDB für lokale Vector Storage
- Semantic Search und Context-Retrieval
- TYPE SAFETY: Umfassende Type-Hints für bessere Code-Qualität
"""

import os
import sqlite3
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from pathlib import Path
from datetime import datetime
from io import BytesIO

# File Processing
import PyPDF2
import docx

# RAG Components
import chromadb
from sentence_transformers import SentenceTransformer
import numpy as np

# Configuration
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

class KnowledgeManager:
    """
    Vollständiges RAG-System für Kursstudio
    
    Workflow:
    1. File Upload → Text Extraction
    2. Text Chunking → Semantic Segments
    3. Embedding Generation → Vector Creation
    4. Vector Storage → ChromaDB
    5. Semantic Search → Context Retrieval
    """
    
    def __init__(self, db_path: str = "kursstudio.db", vector_db_path: str = "./chroma_db"):
        self.db_path = db_path
        self.vector_db_path = vector_db_path
        self.embedding_model: Optional[SentenceTransformer] = None
        self.chroma_client: Optional[chromadb.PersistentClient] = None
        self.collections: Dict[str, Any] = {}
        
        # Supported file types
        self.supported_extensions: Set[str] = {'.pdf', '.txt', '.docx'}
        self.max_file_size: int = 16 * 1024 * 1024  # 16MB
        
        # Chunking parameters
        self.chunk_size: int = 1000  # Characters per chunk
        self.chunk_overlap: int = 200  # Overlap between chunks
        
        self.initialize_systems()
    
    def initialize_systems(self) -> bool:
        """Initialisiert Embedding-Model und Vector-Datenbank"""
        try:
            # Sentence-Transformer laden (Open Source)
            logger.info("Loading sentence transformer model...")
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("✅ Embedding model loaded successfully")
            
            # ChromaDB initialisieren
            logger.info("Initializing ChromaDB...")
            self.chroma_client = chromadb.PersistentClient(path=self.vector_db_path)
            logger.info("✅ ChromaDB initialized successfully")
            
            return True
            
        except Exception as e:
            logger.warning(f"⚠️ RAG System initialization failed: {e}")
            logger.info("📝 Running in fallback mode - text processing only")
            
            # Fallback mode: No embeddings, but text processing still works
            self.embedding_model = None
            self.chroma_client = None
            return False
    
    def process_uploaded_file(self, file_path: str, project_id: int, user_id: int, filename: str) -> Dict[str, Any]:
        """
        Verarbeitet hochgeladene Datei komplett
        
        Returns:
            dict: Processing results with success status
        """
        try:
            # File validation
            if not self._validate_file(file_path, filename):
                return {"success": False, "error": "File validation failed"}
            
            # Text extraction
            extracted_text = self._extract_text(file_path, filename)
            if not extracted_text:
                return {"success": False, "error": "Text extraction failed"}
            
            # Text chunking
            chunks = self._chunk_text(extracted_text)
            if not chunks:
                return {"success": False, "error": "Text chunking failed"}
            
            # Generate embeddings
            embeddings = self._generate_embeddings(chunks)
            if embeddings is None:
                return {"success": False, "error": "Embedding generation failed"}
            
            # Store in vector database
            collection_name = f"project_{project_id}"
            doc_id = self._store_in_vector_db(collection_name, chunks, embeddings, filename)
            
            # Update SQL database
            file_info = {
                'project_id': project_id,
                'user_id': user_id,
                'filename': filename,
                'file_path': file_path,
                'chunks_count': len(chunks),
                'doc_id': doc_id,
                'processed': True
            }
            
            self._update_file_database(file_info)
            
            logger.info(f"✅ File processed successfully: {filename} ({len(chunks)} chunks)")
            
            return {
                "success": True,
                "filename": filename,
                "chunks_count": len(chunks),
                "doc_id": doc_id,
                "preview": extracted_text[:200] + "..." if len(extracted_text) > 200 else extracted_text
            }
            
        except Exception as e:
            logger.error(f"❌ File processing error: {e}")
            return {"success": False, "error": str(e)}
    
    def search_knowledge(self, query: str, project_id: int, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Semantic Search in der Wissensbasis
        
        Args:
            query: Search query
            project_id: Project ID for context
            top_k: Number of top results
            
        Returns:
            List of relevant text chunks with metadata
        """
        try:
            if not self.embedding_model or not self.chroma_client:
                logger.warning("RAG system not initialized")
                return []
            
            collection_name = f"project_{project_id}"
            
            # Check if collection exists
            try:
                collection = self.chroma_client.get_collection(collection_name)
            except:
                logger.info(f"No knowledge base found for project {project_id}")
                return []
            
            # Generate query embedding
            query_embedding = self.embedding_model.encode([query]).tolist()
            
            # Semantic search
            results = collection.query(
                query_embeddings=query_embedding,
                n_results=min(top_k, 10),
                include=['documents', 'metadatas', 'distances']
            )
            
            # Format results
            formatted_results = []
            for i, (doc, metadata, distance) in enumerate(zip(
                results['documents'][0],
                results['metadatas'][0], 
                results['distances'][0]
            )):
                formatted_results.append({
                    'content': doc,
                    'source': metadata.get('filename', 'Unknown'),
                    'chunk_id': metadata.get('chunk_id', i),
                    'relevance_score': 1 - distance,  # Convert distance to relevance
                    'metadata': metadata
                })
            
            logger.info(f"✅ Knowledge search completed: {len(formatted_results)} results for '{query[:50]}'")
            return formatted_results
            
        except Exception as e:
            logger.error(f"❌ Knowledge search error: {e}")
            return []
    
    def get_project_knowledge_summary(self, project_id: int) -> Dict[str, Any]:
        """Gibt Übersicht über die Wissensbasis eines Projekts"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT filename, file_size, chunks_count, created_at
                    FROM uploaded_files 
                    WHERE project_id = ? AND processed = TRUE
                    ORDER BY created_at DESC
                ''', (project_id,))
                files = cursor.fetchall()
            
            total_chunks = sum(file['chunks_count'] or 0 for file in files)
            
            return {
                'files_count': len(files),
                'total_chunks': total_chunks,
                'files': [dict(file) for file in files]
            }
            
        except Exception as e:
            logger.error(f"Knowledge summary error: {e}")
            return {'files_count': 0, 'total_chunks': 0, 'files': []}
    
    # Internal Processing Methods
    
    def _validate_file(self, file_path: str, filename: str) -> bool:
        """Validiert Datei-Upload mit robuster Type-Safety"""
        try:
            # Check file exists
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return False
            
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                logger.error(f"File too large: {file_size} bytes")
                return False
            
            # Check file extension
            ext = Path(filename).suffix.lower()
            if ext not in self.supported_extensions:
                logger.error(f"Unsupported file type: {ext}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"File validation error: {e}")
            return False
    
    def _extract_text(self, file_path: str, filename: str) -> str:
        """
        Extrahiert Text aus verschiedenen Dateiformaten mit Type-Safety
        
        Args:
            file_path: Vollständiger Pfad zur Datei
            filename: Original-Dateiname für Extension-Detection
            
        Returns:
            Extrahierter Text als String
        """
        try:
            ext = Path(filename).suffix.lower()
            
            if ext == '.txt':
                return self._extract_from_txt(file_path)
            elif ext == '.pdf':
                return self._extract_from_pdf(file_path)
            elif ext == '.docx':
                return self._extract_from_docx(file_path)
            else:
                logger.error(f"Unsupported file extension: {ext}")
                return ""
                
        except Exception as e:
            logger.error(f"Text extraction error: {e}")
            return ""
    
    def _extract_from_txt(self, file_path: str) -> str:
        """Extrahiert Text aus TXT-Datei mit Encoding-Fallback"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except UnicodeDecodeError:
            # Fallback encoding
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    return file.read()
            except Exception as e:
                logger.error(f"TXT extraction fallback failed: {e}")
                return ""
    
    def _extract_from_pdf(self, file_path: str) -> str:
        """Extrahiert Text aus PDF-Datei mit robuster Error-Handling"""
        try:
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:  # Skip empty pages
                        text += page_text + "\n"
            return text
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            return ""
    
    def _extract_from_docx(self, file_path: str) -> str:
        """Extrahiert Text aus DOCX-Datei mit Paragraph-Handling"""
        try:
            doc = docx.Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():  # Skip empty paragraphs
                    text += paragraph.text + "\n"
            return text
        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
            return ""
    
    def _chunk_text(self, text: str) -> List[str]:
        """Intelligente Text-Segmentierung"""
        try:
            if not text.strip():
                return []
            
            # Simple sentence-aware chunking
            sentences = text.replace('\n', ' ').split('. ')
            chunks = []
            current_chunk = ""
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                    
                # Add sentence to current chunk
                test_chunk = current_chunk + ". " + sentence if current_chunk else sentence
                
                if len(test_chunk) <= self.chunk_size:
                    current_chunk = test_chunk
                else:
                    # Save current chunk and start new one
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence
            
            # Add final chunk
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            
            # Ensure minimum quality chunks
            quality_chunks = [chunk for chunk in chunks if len(chunk.strip()) > 50]
            
            logger.info(f"Text chunking: {len(quality_chunks)} chunks created")
            return quality_chunks
            
        except Exception as e:
            logger.error(f"Text chunking error: {e}")
            return []
    
    def _generate_embeddings(self, chunks: List[str]) -> Optional[List[List[float]]]:
        """Generiert Embeddings für Text-Chunks"""
        try:
            if not self.embedding_model:
                logger.error("Embedding model not initialized")
                return None
            
            embeddings = self.embedding_model.encode(chunks).tolist()
            logger.info(f"Generated {len(embeddings)} embeddings")
            return embeddings
            
        except Exception as e:
            logger.error(f"Embedding generation error: {e}")
            return None
    
    def _store_in_vector_db(self, collection_name: str, chunks: List[str], embeddings: List[List[float]], filename: str) -> str:
        """Speichert Chunks und Embeddings in ChromaDB"""
        try:
            # Get or create collection
            try:
                collection = self.chroma_client.get_collection(collection_name)
            except:
                collection = self.chroma_client.create_collection(collection_name)
            
            # Create unique IDs and metadata
            doc_id = hashlib.md5(f"{filename}_{datetime.now()}".encode()).hexdigest()[:12]
            
            ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [
                {
                    'filename': filename,
                    'chunk_id': i,
                    'doc_id': doc_id,
                    'created_at': datetime.now().isoformat()
                }
                for i in range(len(chunks))
            ]
            
            # Store in ChromaDB
            collection.add(
                documents=chunks,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"✅ Stored {len(chunks)} chunks in vector DB (collection: {collection_name})")
            return doc_id
            
        except Exception as e:
            logger.error(f"Vector DB storage error: {e}")
            raise
    
    def _update_file_database(self, file_info: Dict[str, Any]):
        """Aktualisiert SQL-Datenbank mit File-Informationen"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE uploaded_files 
                    SET processed = ?, chunks_count = ?, doc_id = ?
                    WHERE project_id = ? AND filename = ?
                ''', (
                    file_info['processed'],
                    file_info['chunks_count'],
                    file_info['doc_id'],
                    file_info['project_id'],
                    file_info['filename']
                ))
                conn.commit()
                
                if cursor.rowcount == 0:
                    # Insert new record if update didn't affect any rows
                    cursor.execute('''
                        INSERT INTO uploaded_files 
                        (project_id, user_id, filename, file_path, file_type, file_size, processed, chunks_count, doc_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        file_info['project_id'],
                        file_info['user_id'],
                        file_info['filename'],
                        file_info['file_path'],
                        Path(file_info['filename']).suffix,
                        os.path.getsize(file_info['file_path']),
                        file_info['processed'],
                        file_info['chunks_count'],
                        file_info['doc_id']
                    ))
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"Database update error: {e}")
            raise

# Global instance for app integration
knowledge_manager = None

def get_knowledge_manager():
    """Singleton pattern for KnowledgeManager"""
    global knowledge_manager
    if knowledge_manager is None:
        knowledge_manager = KnowledgeManager()
    return knowledge_manager

# Knowledge lookup tool for orchestrator
def knowledge_lookup(query: str, project_id: int, context: str = "") -> str:
    """
    Tool-Funktion für Orchestrator
    Führt semantische Suche durch und formatiert Ergebnisse
    """
    try:
        km = get_knowledge_manager()
        results = km.search_knowledge(query, project_id, top_k=3)
        
        if not results:
            return f"Keine relevanten Informationen für '{query}' in der Wissensbasis gefunden."
        
        # Format results for orchestrator
        formatted_response = f"## 📚 WISSENSBASIERTE INFORMATIONEN für '{query}':\n\n"
        
        for i, result in enumerate(results, 1):
            formatted_response += f"### Quelle {i}: {result['source']}\n"
            formatted_response += f"**Relevanz:** {result['relevance_score']:.2f}\n"
            formatted_response += f"**Inhalt:** {result['content']}\n\n"
        
        formatted_response += "---\n*Diese Informationen wurden aus der hochgeladenen Wissensbasis extrahiert.*"
        
        return formatted_response
        
    except Exception as e:
        logger.error(f"Knowledge lookup error: {e}")
        return f"Fehler beim Zugriff auf die Wissensbasis: {e}" 