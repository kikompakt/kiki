"""
Chat-Orchestrator für Intelligentes KI-Kursstudio
Dynamisches Assistant-Management aus Datenbank

NEUE FEATURES:
- Dynamische Assistant-Verwaltung aus DB
- Flexible Tool-Call-Routing
- User-konfigurierbare Workflows
- MEMORY MANAGEMENT: TTL-basiertes Cleanup-System mit Singleton-Pattern
- TYPE SAFETY: Umfassende Type-Hints für bessere Code-Qualität
"""

import os
import json
import time
import sqlite3
import threading
import gc
import logging
import base64
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List

from openai import OpenAI
from dotenv import load_dotenv
from quality_assessment import assess_course_quality

# .env-Datei laden
load_dotenv()

# OpenAI Client initialisieren (Singleton Pattern)
_openai_client = None

def get_openai_client() -> OpenAI:
    """Singleton Pattern für OpenAI Client - verhindert Memory-Leak durch zu viele Instanzen"""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _openai_client

# Global orchestrator instance für Web-App Integration mit Cleanup-System
active_orchestrators: Dict[str, 'DynamicChatOrchestrator'] = {}
orchestrator_last_activity: Dict[str, datetime] = {}

# Memory Management Konfiguration
ORCHESTRATOR_TTL_MINUTES = 30  # Time-to-live für inaktive Orchestrators
MAX_CONCURRENT_ORCHESTRATORS = 50  # Maximum gleichzeitige Orchestrators
CLEANUP_INTERVAL_MINUTES = 10  # Cleanup-Interval

logger = logging.getLogger(__name__)

def cleanup_inactive_orchestrators():
    """
    MEMORY MANAGEMENT: Bereinigt inaktive Orchestrators zur Memory-Optimierung
    Wird automatisch vom Scheduler aufgerufen
    """
    global active_orchestrators, orchestrator_last_activity
    
    now = datetime.now()
    ttl_threshold = now - timedelta(minutes=ORCHESTRATOR_TTL_MINUTES)
    cleanup_count = 0
    
    # Identifiziere inaktive Orchestrators
    inactive_keys = []
    for key, last_activity in orchestrator_last_activity.items():
        if last_activity < ttl_threshold:
            inactive_keys.append(key)
    
    # Bereinige inaktive Orchestrators
    for key in inactive_keys:
        if key in active_orchestrators:
            try:
                # Orchestrator cleanup
                orchestrator = active_orchestrators[key]
                orchestrator._cleanup()
                del active_orchestrators[key]
                del orchestrator_last_activity[key]
                cleanup_count += 1
            except Exception as e:
                logger.warning(f"Orchestrator cleanup error für {key}: {e}")
    
    # Force Garbage Collection bei größeren Cleanups
    if cleanup_count > 5:
        gc.collect()
    
    logger.info(f"🧹 Memory Cleanup: {cleanup_count} inaktive Orchestrators bereinigt. Aktiv: {len(active_orchestrators)}")
    
    # Limit enforcement: Bei zu vielen aktiven Orchestrators älteste entfernen
    if len(active_orchestrators) > MAX_CONCURRENT_ORCHESTRATORS:
        sorted_by_activity = sorted(orchestrator_last_activity.items(), key=lambda x: x[1])
        excess_count = len(active_orchestrators) - MAX_CONCURRENT_ORCHESTRATORS
        
        for key, _ in sorted_by_activity[:excess_count]:
            if key in active_orchestrators:
                try:
                    active_orchestrators[key]._cleanup()
                    del active_orchestrators[key]
                    del orchestrator_last_activity[key]
                except Exception as e:
                    logger.warning(f"Force cleanup error für {key}: {e}")
        
        gc.collect()
        logger.info(f"🚨 Force cleanup: {excess_count} Orchestrators entfernt. Limit: {MAX_CONCURRENT_ORCHESTRATORS}")

def get_or_create_orchestrator(project_id: str, session_id: str, socketio) -> 'DynamicChatOrchestrator':
    """
    MEMORY MANAGEMENT: Factory-Function für Orchestrators mit Activity-Tracking
    """
    orchestrator_key = f"{project_id}_{session_id}"
    
    # Update activity timestamp
    orchestrator_last_activity[orchestrator_key] = datetime.now()
    
    # Return existing orchestrator
    if orchestrator_key in active_orchestrators:
        return active_orchestrators[orchestrator_key]
    
    # Create new orchestrator
    orchestrator = DynamicChatOrchestrator(
        socketio=socketio,
        project_id=project_id,
        session_id=session_id
    )
    
    active_orchestrators[orchestrator_key] = orchestrator
    logger.info(f"🤖 Neuer Orchestrator erstellt: {orchestrator_key}. Aktiv: {len(active_orchestrators)}")
    
    # Trigger cleanup if nearing limit
    if len(active_orchestrators) > MAX_CONCURRENT_ORCHESTRATORS * 0.8:
        threading.Thread(target=cleanup_inactive_orchestrators, daemon=True).start()
    
    return orchestrator

class DynamicChatOrchestrator:
    """
    NEUE DYNAMISCHE VERSION: Chat-Orchestrator mit DB-basiertem Assistant-Management
    
    Features:
    - SocketIO Integration für Live-Updates
    - Dynamische Assistant-Verwaltung aus Datenbank
    - Flexible Tool-Call-Routing
    - User-konfigurierbare Workflows
    - MEMORY MANAGEMENT: TTL-basiertes Cleanup-System
    """
    
    def __init__(self, socketio, project_id: Optional[str] = None, session_id: Optional[str] = None):
        self.socketio = socketio
        self.project_id = project_id
        self.session_id = session_id
        self.client = get_openai_client()  # Singleton Client verwenden
        self.supervisor_assistant = None
        self.assistants: Dict[str, Dict[str, Any]] = {}  # Cache für alle verfügbaren Assistants
        self.thread = None
        self.current_run = None
        self.is_processing = False
        
        # Memory tracking
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        
        # Chat-spezifische Einstellungen
        self.chat_mode = "collaborative"  # collaborative oder autonomous
        self.response_callbacks = []
        
        # Final content tracking
        self.course_content_stages: Dict[str, str] = {}  # Track content through each stage
        self.final_course_content = ""  # The complete final course
        
        # Assistants beim Start laden
        self._load_assistants_from_db()
        
        # Activity tracking aktualisieren
        self._update_activity()
    
    def _update_activity(self):
        """Aktualisiert Activity-Timestamp für Memory-Management"""
        self.last_activity = datetime.now()
        orchestrator_key = f"{self.project_id}_{self.session_id}"
        orchestrator_last_activity[orchestrator_key] = self.last_activity
    
    def _cleanup(self):
        """
        MEMORY MANAGEMENT: Bereinigt Orchestrator-Ressourcen
        """
        try:
            # OpenAI Thread cleanup
            if self.current_run:
                try:
                    self.client.beta.threads.runs.cancel(
                        thread_id=self.thread.id, 
                        run_id=self.current_run.id
                    )
                except:
                    pass  # Silent fail für cleanup
            
            # Clear references
            self.thread = None
            self.current_run = None
            self.assistants.clear()
            self.course_content_stages.clear()
            self.response_callbacks.clear()
            
            # SocketIO cleanup
            if self.socketio and self.session_id:
                try:
                    self.socketio.emit('orchestrator_cleanup', {
                        'message': 'Session bereinigt für Memory-Optimierung'
                    }, room=f'session_{self.session_id}')
                except:
                    pass
            
            logger.info(f"🧹 Orchestrator cleanup abgeschlossen für {self.project_id}_{self.session_id}")
            
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
    
    def _load_assistants_from_db(self):
        """Lädt alle aktiven Assistants aus der SQLAlchemy-Datenbank (PostgreSQL/SQLite)."""
        try:
            # Lazy import to avoid circular dependency
            from models import db, Assistant  # noqa: E402
            from flask import current_app
            
            # CRITICAL FIX: Ensure we're in Flask app context
            with current_app.app_context():
                assistants = Assistant.query.filter_by(is_active=True).order_by(Assistant.order_index.asc()).all()
                
                # Cache assistants
                for assistant in assistants:
                    assistant_data = {
                        'id': assistant.id,
                        'name': assistant.name,
                        'assistant_id': assistant.assistant_id,
                        'role': assistant.role,
                        'description': assistant.description,
                        'instructions': assistant.instructions,
                        'model': assistant.model,
                        'temperature': assistant.temperature,
                        'top_p': assistant.top_p,
                        'max_tokens': assistant.max_tokens,
                        'frequency_penalty': assistant.frequency_penalty,
                        'presence_penalty': assistant.presence_penalty,
                        'retry_attempts': assistant.retry_attempts,
                        'timeout_seconds': assistant.timeout_seconds,
                        'enabled_tools': json.loads(assistant.enabled_tools) if assistant.enabled_tools else []
                    }
                    self.assistants[assistant.role] = assistant_data
                    
                    # Mark supervisor assistant
                    if assistant.role == 'supervisor':
                        self.supervisor_assistant_id = assistant.assistant_id
                        self.emit_status(f"✅ Supervisor Assistant geladen: {self.supervisor_assistant_id}")
                
                if not self.assistants:
                    self.emit_status("⚠️ Keine aktiven Assistants in der Datenbank gefunden")
                    
        except Exception as e:
            logger.error(f"Assistant-Load-Error: {e}")
            self.emit_error(f"Assistant-Load-Error: {e}")
            # FALLBACK: Create a basic supervisor assistant if DB fails
            self._create_fallback_supervisor()
    
    def _create_fallback_supervisor(self):
        """Creates fallback assistants when database is not available"""
        logger.info("🔄 Creating fallback assistants (no database access)")
        
        # Create comprehensive fallback assistant data
        fallback_assistants = {
            'supervisor': {
                'id': 1,
                'name': 'Fallback Supervisor',
                'assistant_id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',
                'role': 'supervisor',
                'description': 'Fallback Supervisor für lokale Entwicklung',
                'instructions': self._get_supervisor_instructions(),
                'model': 'gpt-4o',
                'temperature': 0.7,
                'top_p': 1.0,
                'max_tokens': 2000,
                'frequency_penalty': 0.0,
                'presence_penalty': 0.0,
                'retry_attempts': 3,
                'timeout_seconds': 300,
                'enabled_tools': ['create_content','optimize_didactics','critically_review','request_user_feedback','knowledge_lookup']
            },
            'content_creator': {
                'id': 2,
                'name': 'Fallback Content Creator',
                'assistant_id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',  # Use same assistant ID
                'role': 'content_creator',
                'description': 'Fallback Content Creator für Kursinhalte',
                'instructions': '''Du bist ein Experte für die Erstellung von hochwertigen Lerninhalten.
                
DEINE AUFGABE: Erstelle strukturierte, professionelle Kursinhalte basierend auf dem gegebenen Thema.
Erstelle immer vollständige, sofort einsetzbare Kursinhalte mit klaren Lernzielen, logischem Aufbau und praktischen Beispielen.''',
                'model': 'gpt-4o',
                'temperature': 0.3,
                'max_tokens': 3000
            },
            'didactic_expert': {
                'id': 3,
                'name': 'Fallback Didactic Expert',
                'assistant_id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',
                'role': 'didactic_expert',
                'description': 'Fallback Didactic Expert für didaktische Optimierung',
                'instructions': '''Du bist ein Didaktik-Experte für die Optimierung von Lerninhalten.
                
DEINE AUFGABE: Optimiere vorhandene Kursinhalte didaktisch und methodisch.
Gib den vollständig optimierten Kursinhalt aus (nicht nur Verbesserungsvorschläge)!''',
                'model': 'gpt-4o',
                'temperature': 0.4,
                'max_tokens': 3000
            },
            'quality_checker': {
                'id': 4,
                'name': 'Fallback Quality Checker',
                'assistant_id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',
                'role': 'quality_checker',
                'description': 'Fallback Quality Checker für finale Prüfung',
                'instructions': '''Du bist ein Qualitäts-Experte für die finale Prüfung von Kursinhalten.
                
DEINE AUFGABE: Führe eine kritische Qualitätsprüfung durch und korrigiere Mängel.
Gib den vollständig korrigierten und qualitätsgesicherten Kurs aus!''',
                'model': 'gpt-4o',
                'temperature': 0.2,
                'max_tokens': 3000
            }
        }
        
        # Load all fallback assistants
        for role, assistant_data in fallback_assistants.items():
            self.assistants[role] = assistant_data
            logger.info(f"✅ Fallback {role} assistant created")
        
        self.supervisor_assistant_id = fallback_assistants['supervisor']['assistant_id']
        
        logger.info(f"✅ All fallback assistants created: {list(fallback_assistants.keys())}")
        self.emit_status(f"✅ Fallback Assistants geladen: {len(fallback_assistants)} Rollen verfügbar")

    def get_or_create_assistant(self):
        """
        NEUE DYNAMISCHE VERSION: Verwendet Supervisor aus Datenbank mit Tool-Setup
        """
        if not hasattr(self, 'supervisor_assistant_id'):
            self.emit_error("❌ Kein Supervisor-Assistant in der Datenbank konfiguriert")
            return False
            
        try:
            # Supervisor Assistant aus Datenbank laden
            self.supervisor_assistant = self.client.beta.assistants.retrieve(self.supervisor_assistant_id)
            
            # CRITICAL FIX: Stelle sicher, dass Tools konfiguriert sind
            required_tools = self._get_required_tools()
            current_tools = self.supervisor_assistant.tools or []
            
            # Prüfe ob Tools fehlen oder veraltet sind ODER Instructions aktualisiert werden müssen
            needs_update = not self._tools_are_current(current_tools, required_tools)
            current_instructions = getattr(self.supervisor_assistant, 'instructions', '')
            new_instructions = self._get_supervisor_instructions()
            
            # Force update if instructions changed or tools outdated
            if needs_update or current_instructions != new_instructions:
                self.emit_status("🔧 Aktualisiere Supervisor (Tools & Instructions)...")
                
                # Update Assistant mit korrekten Tools und Instructions
                self.supervisor_assistant = self.client.beta.assistants.update(
                    assistant_id=self.supervisor_assistant_id,
                    tools=required_tools,
                    instructions=new_instructions
                )
                
                self.emit_status("✅ Supervisor vollständig aktualisiert")
            
            self.emit_status(f"✅ Supervisor Assistant geladen: {self.supervisor_assistant_id}")
            return True
            
        except Exception as e:
            self.emit_error(f"❌ Fehler beim Laden des Supervisor Assistants: {e}")
            return False
    
    def get_api_parameters_for_assistant(self, role):
        """Extrahiert OpenAI API-Parameter für spezifischen Assistant-Role."""
        assistant = self.assistants.get(role, {})
        
        # Standard-Parameter falls Assistant nicht gefunden
        defaults = {
            'temperature': 0.7,
            'top_p': 1.0, 
            'max_tokens': 2000,
            'frequency_penalty': 0.0,
            'presence_penalty': 0.0
        }
        
        # Erweiterte Parameter aus DB laden
        api_params = {
            'temperature': assistant.get('temperature', defaults['temperature']),
            'top_p': assistant.get('top_p', defaults['top_p']),
            'max_tokens': assistant.get('max_tokens', defaults['max_tokens']),
            'frequency_penalty': assistant.get('frequency_penalty', defaults['frequency_penalty']),
            'presence_penalty': assistant.get('presence_penalty', defaults['presence_penalty'])
        }
        
        # Workflow-Parameter auch verfügbar machen
        workflow_params = {
            'retry_attempts': assistant.get('retry_attempts', 3),
            'timeout_seconds': assistant.get('timeout_seconds', 180),
            'error_handling': assistant.get('error_handling', 'graceful'),
            'response_limit': assistant.get('response_limit', 30),
            'context_window': assistant.get('context_window', 128000)
        }
        
        return api_params, workflow_params
    
    def _get_required_tools(self):
        """Definiert die erforderlichen Tool-Calls für Multi-Agenten-System"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_content",
                    "description": "Erstellt einen ersten Rohentwurf für ein gegebenes Thema mit Content Creator Agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "Das Thema, zu dem der Inhalt erstellt werden soll."
                            },
                            "instructions": {
                                "type": "string", 
                                "description": "Spezifische Anweisungen für die Inhaltserstellung."
                            },
                            "content_type": {
                                "type": "string",
                                "description": "Der Typ des zu erstellenden Inhalts: 'outline' für Inhaltsverzeichnis oder 'full_content' für vollständigen Inhalt.",
                                "enum": ["outline", "full_content"]
                            }
                        },
                        "required": ["topic", "instructions", "content_type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "optimize_didactics",
                    "description": "Optimiert vorhandenen Inhalt didaktisch mit Didactic Expert Agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Der zu optimierende Inhalt."
                            }
                        },
                        "required": ["content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "critically_review",
                    "description": "Prüft Inhalt kritisch auf Logik, Fakten und Konsistenz mit Quality Checker Agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Der zu prüfende Inhalt."
                            },
                            "review_type": {
                                "type": "string",
                                "description": "Der Typ der Prüfung: 'outline' für Inhaltsverzeichnis-Review oder 'full_content' für vollständige Inhaltsprüfung.",
                                "enum": ["outline", "full_content"]
                            }
                        },
                        "required": ["content", "review_type"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "request_outline_approval",
                    "description": "Zeigt dem User das geprüfte Inhaltsverzeichnis und fragt nach Freigabe für die Volltext-Erstellung. User kann Änderungen vorschlagen.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "outline": {
                                "type": "string",
                                "description": "Das detaillierte Inhaltsverzeichnis mit Kapiteln, Lernzielen und groben Beschreibungen."
                            },
                            "quality_feedback": {
                                "type": "string",
                                "description": "Das Feedback vom Quality Checker zum Outline."
                            },
                            "topic": {
                                "type": "string",
                                "description": "Das Kursthema."
                            }
                        },
                        "required": ["outline", "quality_feedback", "topic"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "request_user_feedback", 
                    "description": "Fordert finales Feedback vom User für den vollständig erstellten Kursinhalt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Der finale Kursinhalt für den Feedback benötigt wird."
                            },
                            "question": {
                                "type": "string",
                                "description": "Die spezifische Frage an den User."
                            },
                            "stage": {
                                "type": "string",
                                "description": "Das Stadium des Workflows (z.B. 'final_approval')."
                            }
                        },
                        "required": ["content", "question", "stage"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "knowledge_lookup",
                    "description": "Durchsucht die projektspezifische Wissensbasis nach relevanten Informationen.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Die Suchanfrage für die Wissensbasis."
                            },
                            "context": {
                                "type": "string",
                                "description": "Zusätzlicher Kontext für die Suche."
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]
    
    def _tools_are_current(self, current_tools, required_tools):
        """Prüft ob die aktuellen Tools mit den erforderlichen übereinstimmen"""
        if len(current_tools) != len(required_tools):
            return False
        
        # Einfache Prüfung: Schaue nach den Function-Namen
        current_names = set()
        for tool in current_tools:
            if tool.type == "function" and hasattr(tool, 'function'):
                current_names.add(tool.function.name)
        
        required_names = set()
        for tool in required_tools:
            if tool["type"] == "function":
                required_names.add(tool["function"]["name"])
        
        return current_names == required_names
    
    def _get_supervisor_instructions(self):
        """Einfache, klare Instructions für den Supervisor-Assistant"""
        return """Du bist ein intelligenter KI-Supervisor für automatische Kurserstellung.

DEINE AUFGABE: Erkenne die Nutzerintention und handle entsprechend:

🎯 BEI EXPLIZITEN KURSANFRAGEN:
Wenn der User eindeutig einen Kurs erstellen möchte (erkennbar an Wörtern wie "Kurs", "erstelle", "Training", "Schulung", "Lerninhalt"):

Führe automatisch diese 3 Schritte aus:
1. create_content(topic="[Thema]", instructions="Erstelle einen professionellen Kurs")
2. optimize_didactics(content="[Ergebnis von Schritt 1]")  
3. critically_review(content="[Ergebnis von Schritt 2]")

WICHTIG für Kurserstellung:
- Führe ALLE 3 Schritte automatisch aus
- Verwende die Tool-Outputs direkt weiter
- Frage NICHT nach Bestätigung zwischen den Schritten
- Nach Schritt 3 sagst du: "Kurs wurde erfolgreich erstellt!"

💬 BEI ANDEREN ANFRAGEN:
- Allgemeine Fragen: Beantworte freundlich und kompetent
- Unklare Themen: Stelle Rückfragen ("Zu welchem Thema soll der Kurs erstellt werden?")
- Begrüßungen: Antworte höflich und erkläre deine Fähigkeiten

BEISPIELE:
✅ "Erstelle einen Kurs über Python" → Starte Workflow
✅ "Ich brauche ein Training zu Vertrieb" → Starte Workflow  
❌ "Was kannst du?" → Erkläre Fähigkeiten (KEIN Workflow)
❌ "Wie funktioniert das?" → Beantworte Frage (KEIN Workflow)

Analysiere die Nutzeranfrage sorgfältig und handle situationsgerecht!"""
    
    def create_thread(self):
        """Erstellt einen neuen Chat-Thread."""
        try:
            self.thread = self.client.beta.threads.create()
            self.emit_status(f"✅ Chat-Thread erstellt: {self.thread.id}")
            return True
        except Exception as e:
            self.emit_error(f"❌ Thread-Erstellung fehlgeschlagen: {e}")
            return False
    
    def process_message(self, message: str, user_id: int = 1):
        """
        MAIN METHOD: Verarbeitet User-Nachrichten mit dynamischen DB-Assistants
        MEMORY OPTIMIZED: Activity-Tracking für TTL-Management
        """
        logger.info(f"🎯 PROCESS_MESSAGE START: user_id={user_id}, message='{message}'")
        
        self._update_activity()  # Track activity für Memory-Management
        
        if self.is_processing:
            logger.warning(f"⏳ Already processing for user {user_id}")
            self.emit_message("⏳ Ein anderer Prozess läuft bereits. Bitte warten Sie einen Moment.", "assistant")
            return
        
        # INTENT DETECTION: Check if this is a simple greeting or small talk
        intent = self._detect_intent(message)
        if intent in ['greeting', 'small_talk']:
            logger.info(f"🤝 Intent detected as {intent}, sending direct response")
            self._handle_simple_response(message, intent)
            return
        
        # CRITICAL: Supervisor-Assistant sicherstellen
        logger.info(f"🔍 Loading supervisor assistant for user {user_id}")
        if not self.get_or_create_assistant():
            logger.error(f"❌ Failed to load supervisor assistant for user {user_id}")
            self.emit_error("❌ Supervisor-Assistant konnte nicht geladen werden")
            return
        
        logger.info(f"✅ Supervisor assistant loaded for user {user_id}")
        
        self.is_processing = True
        self.emit_status("🤖 KI-Agent arbeitet...")
        
        try:
            # Thread erstellen falls nicht vorhanden
            if not self.thread:
                logger.info(f"🧵 Creating new thread for user {user_id}")
                self.thread = self.client.beta.threads.create()
                self.emit_status("✅ Neuer Thread erstellt")
                logger.info(f"✅ Thread created: {self.thread.id}")
            else:
                logger.info(f"🔄 Using existing thread: {self.thread.id}")
            
            # Nachricht zum Thread hinzufügen
            logger.info(f"📝 Adding message to thread for user {user_id}")
            self.client.beta.threads.messages.create(
                thread_id=self.thread.id,
                role="user",
                content=message
            )
            logger.info(f"✅ Message added to thread")
            
            # Run starten
            logger.info(f"🚀 Starting run with assistant: {self.supervisor_assistant.id}")
            self.current_run = self.client.beta.threads.runs.create(
                thread_id=self.thread.id,
                assistant_id=self.supervisor_assistant.id
            )
            logger.info(f"✅ Run created: {self.current_run.id}")
            
            # Monitoring starten
            logger.info(f"👁️ Starting run monitoring for user {user_id}")
            self._monitor_run()
            logger.info(f"✅ Run monitoring completed for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error in process_message for user {user_id}: {e}")
            logger.error(f"❌ Exception details: {type(e).__name__}: {str(e)}")
            self.emit_error(f"❌ Fehler bei der Nachrichtenverarbeitung: {e}")
        finally:
            self.is_processing = False
            self._update_activity()
            logger.info(f"🏁 PROCESS_MESSAGE END: user_id={user_id}")
    
    def force_recovery(self):
        """Erzwingt Recovery bei hängenden Runs mit sofortigem Neustart"""
        self._update_activity()
        
        try:
            if self.current_run:
                self.emit_status("🔄 Stoppe hängenden Run...")
                try:
                    self.client.beta.threads.runs.cancel(thread_id=self.thread.id, run_id=self.current_run.id)
                    self.emit_status("✅ Alter Run erfolgreich gestoppt")
                except Exception as cancel_error:
                    self.emit_status(f"⚠️ Run-Cancel Fehler (wird ignoriert): {cancel_error}")
                
                # Status zurücksetzen
                self.current_run = None
                time.sleep(1)  # Kurze Pause
                
                self.emit_status("🔄 Starte neuen Run für Recovery...")
                
                # Neuen Run erstellen
                try:
                    self.current_run = self.client.beta.threads.runs.create(
                        thread_id=self.thread.id,
                        assistant_id=self.supervisor_assistant.id
                    )
                    
                    self.emit_status("✅ Recovery-Run erstellt - Monitoring wird fortgesetzt...")
                    # Continue monitoring the new run
                    self._monitor_run()
                    
                except Exception as new_run_error:
                    self.emit_error(f"❌ Recovery-Run Fehler: {new_run_error}")
                    self.emit_message("Recovery fehlgeschlagen. Bitte senden Sie Ihre Nachricht erneut oder nutzen Sie 'reset' für einen kompletten Neustart.", "assistant")
                
            else:
                self.emit_status("ℹ️ Kein aktiver Run gefunden. System ist bereit für neue Nachrichten.")
                
        except Exception as e:
            self.emit_error(f"❌ Recovery-Fehler: {e}")
            self.emit_message("System-Recovery fehlgeschlagen. Bitte nutzen Sie 'reset' für einen manuellen Neustart oder senden Sie Ihre Nachricht erneut.", "assistant")
        finally:
            self.is_processing = False
            self._update_activity()
    
    def _process_message_async(self, message, user_data):
        """Asynchrone Nachrichtenverarbeitung"""
        self.is_processing = True
        
        try:
            # Initialisierung falls nötig
            if not self.supervisor_assistant:
                if not self.get_or_create_assistant():
                    return
                    
            if not self.thread:
                if not self.create_thread():
                    return
            
            # User-Nachricht zum Thread hinzufügen
            self.client.beta.threads.messages.create(
                thread_id=self.thread.id,
                role="user",
                content=message
            )
            
            # Run starten
            self.current_run = self.client.beta.threads.runs.create(
                thread_id=self.thread.id,
                assistant_id=self.supervisor_assistant.id
            )
            
            # Run-Status überwachen
            self._monitor_run()
            
        except Exception as e:
            self.emit_error(f"❌ Verarbeitungsfehler: {e}")
        finally:
            self.is_processing = False
    
    def _monitor_run(self):
        """Überwacht den Run-Status und verarbeitet Tool-Calls mit erweiterten Workflow-Parametern"""
        
        # Workflow-Parameter für Supervisor aus DB laden
        _, workflow_params = self.get_api_parameters_for_assistant('supervisor')
        max_iterations = workflow_params.get('retry_attempts', 3) * 15  # Mehr Iterations bei höheren Retry-Werten
        timeout_seconds = workflow_params.get('timeout_seconds', 180)
        error_handling = workflow_params.get('error_handling', 'graceful')
        
        iteration = 0
        stuck_count = 0  # Counter für hängende Runs
        last_status = None
        queued_count = 0  # Special counter for queued status
        start_time = time.time()
        
        self.emit_status(f"🔄 Monitoring mit Timeout: {timeout_seconds}s, Max-Iterations: {max_iterations}, Error-Handling: {error_handling}")
        
        while iteration < max_iterations:
            try:
                # Timeout-Check basierend auf DB-Parameter
                if time.time() - start_time > timeout_seconds:
                    self.emit_status(f"⏰ Timeout nach {timeout_seconds}s erreicht")
                    if error_handling == 'graceful':
                        self.emit_error("Entschuldigung, die Verarbeitung dauert zu lange. Bitte versuchen Sie es erneut.")
                        return
                    elif error_handling == 'retry':
                        self.emit_status("🔄 Automatischer Restart nach Timeout...")
                        self.force_recovery()
                        return
                    else:  # strict
                        self.emit_error("❌ Verarbeitung wegen Timeout abgebrochen.")
                        return

                run = self.client.beta.threads.runs.retrieve(
                    thread_id=self.thread.id,
                    run_id=self.current_run.id
                )
                
                # Stuck-Detection: Wenn Status länger als X Iterationen gleich bleibt
                if run.status == last_status:
                    stuck_count += 1
                else:
                    stuck_count = 0
                    last_status = run.status
                
                # Special handling for queued status - much more aggressive
                if run.status == "queued":
                    queued_count += 1
                    self.emit_status(f"⏳ In Warteschlange... ({queued_count}/15)")
                    
                    # AGGRESSIVE: Cancel after 15 iterations for queued (30 seconds)
                    if queued_count >= 15:
                        self.emit_status("🚨 Run hängt in Queue - Force Recovery...")
                        self.force_recovery()
                        return
                else:
                    queued_count = 0
                
                # General stuck detection (reduced to 6 iterations = 12s)
                if stuck_count >= 6 and run.status in ["queued", "in_progress"]:
                    self.emit_status(f"🚨 Run hängt bei Status '{run.status}' - Automatische Recovery...")
                    self.force_recovery()
                    return
                
                if run.status == "completed":
                    # Run erfolgreich abgeschlossen, finale Antwort abrufen
                    messages = self.client.beta.threads.messages.list(
                        thread_id=self.thread.id,
                        limit=1
                    )
                    
                    # Prüfen, ob eine Nachricht vorhanden ist
                    if messages.data and messages.data[0].content:
                        response = messages.data[0].content[0].text.value
                        
                        # === HIER IST DIE WICHTIGE ÄNDERUNG ZUR DIAGNOSE ===
                        print(f"DEBUG: Sende folgende Antwort an das Frontend: '{response}'")
                        
                        # CRITICAL NEW FEATURE: Save course content if workflow completed successfully
                        if self._is_course_creation_complete(response):
                            logger.info("🎓 Course creation detected as complete, saving to database...")
                            self._save_course_to_database(response)
                        
                        self.emit_message(response, "assistant")
                    else:
                        # Dieser Fall wird eintreten, wenn die KI nichts antwortet
                        print("DEBUG: Keine Text-Antwort von OpenAI erhalten. Die Antwort war leer.")
                        
                    break
                    
                elif run.status == "requires_action":
                    # Tool-Calls verarbeiten
                    self._handle_tool_calls(run)
                    # CRITICAL FIX: Nach Tool-Handling direkt weitermachen
                    continue
                    
                elif run.status in ["failed", "cancelled", "expired"]:
                    # ENHANCED ERROR HANDLING: Get detailed error information
                    error_message = f"❌ Verarbeitung fehlgeschlagen: {run.status}"
                    
                    # Try to get detailed error information
                    try:
                        if hasattr(run, 'last_error') and run.last_error:
                            error_details = f"Error Code: {run.last_error.code}, Message: {run.last_error.message}"
                            logger.error(f"🚨 OPENAI RUN ERROR DETAILS: {error_details}")
                            error_message += f"\nDetails: {error_details}"
                        
                        # Also check run steps for more detailed errors
                        run_steps = self.client.beta.threads.runs.steps.list(
                            thread_id=self.thread.id,
                            run_id=self.current_run.id
                        )
                        
                        for step in run_steps.data:
                            if step.status == "failed" and hasattr(step, 'last_error') and step.last_error:
                                step_error = f"Step Error - Code: {step.last_error.code}, Message: {step.last_error.message}"
                                logger.error(f"🚨 OPENAI STEP ERROR: {step_error}")
                                if "Details:" not in error_message:
                                    error_message += f"\nStep Details: {step_error}"
                                    
                    except Exception as error_fetch_error:
                        logger.error(f"❌ Could not fetch detailed error info: {error_fetch_error}")
                    
                    self.emit_error(error_message)
                    logger.error(f"🚨 FULL RUN FAILURE: Status={run.status}, RunID={run.id}, ThreadID={self.thread.id}")
                    break
                    
                elif run.status in ["queued", "in_progress"]:
                    # Status-Updates für laufende Verarbeitung (but not for queued - handled above)
                    if run.status != "queued":
                        self.emit_status(f"⏳ Verarbeitung läuft... (Status: {run.status}, Iteration: {iteration})")
                    
                time.sleep(2)  # Längere Wartezeit für Tool-intensive Workflows
                iteration += 1
                
            except Exception as e:
                # Bei JSON-Parsing-Fehlern: Kurz warten und weiter versuchen
                if "Extra data" in str(e) or "JSON" in str(e):
                    self.emit_status("⚠️ API-Response-Fehler, versuche erneut...")
                    time.sleep(1)
                    continue
                else:
                    self.emit_error(f"❌ Run-Monitoring Fehler: {e}")
                    break
        
        # Timeout-Protection
        if iteration >= max_iterations:
            self.emit_error(f"⏰ Timeout: Verarbeitung nach {max_iterations} Iterationen abgebrochen. Bitte versuchen Sie es erneut.")
    
    def _handle_tool_calls(self, run):
        """NEUE DYNAMISCHE VERSION: Verarbeitet Tool-Calls mit DB-Assistant-Routing"""
        tool_outputs = []
        
        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            
            self.emit_status(f"🔧 Führe {function_name} aus...")
            
            # Emit tool call details to frontend
            self.emit_workflow_update({
                'type': 'tool_call_start',
                'function': function_name,
                'arguments': arguments,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
            
            try:
                # NEUE DYNAMISCHE TOOL-ROUTING
                if function_name == "create_content":
                    content_type = arguments.get("content_type", "full_content")
                    phase_info = "Outline-Erstellung" if content_type == "outline" else "Volltext-Erstellung"
                    self.emit_status(f"🖊️ {phase_info} läuft...")
                    result = self._call_assistant_by_role("content_creator", arguments)
                    
                elif function_name == "optimize_didactics":
                    self.emit_status(f"🎓 Didaktische Optimierung läuft...")
                    result = self._call_assistant_by_role("didactic_expert", arguments)
                    
                elif function_name == "critically_review":
                    review_type = arguments.get("review_type", "full_content")
                    review_info = "Outline-Qualitätsprüfung" if review_type == "outline" else "Finale Qualitätsprüfung"
                    self.emit_status(f"🔍 {review_info} läuft...")
                    result = self._call_assistant_by_role("quality_checker", arguments)
                    
                    try:
                        # Quality Assessment für Scoring
                        quality_result = assess_course_quality(result)
                        
                        # FIXED: Convert 0-100 scale to 0-10 scale
                        overall_score_100 = quality_result.get('overall_score', 0)
                        overall_score_10 = round(overall_score_100 / 10, 1)
                        
                        result = result + f"\n\n📊 Quality Score: {overall_score_10}/10"
                        
                        # Quality Gate Check with correct 0-10 scale
                        if overall_score_10 < 7.0:
                            self.emit_status(f"⚠️ Quality Gate: Score {overall_score_10}/10 - Verbesserung empfohlen")
                        else:
                            self.emit_status(f"✅ Quality Gate: Score {overall_score_10}/10 - Qualitätsziel erreicht")
                            
                    except Exception as e:
                        self.emit_status(f"⚠️ Quality Gate Check Fehler: {e}")
                      
                elif function_name == "request_outline_approval":
                    result = self.request_outline_approval(arguments.get("outline", ""), arguments.get("quality_feedback", ""), arguments.get("topic", ""))
                elif function_name == "request_user_feedback":
                    result = self.request_user_feedback(arguments.get("content", ""), arguments.get("question", ""), arguments.get("stage", ""))
                elif function_name == "knowledge_lookup":
                    self.emit_status(f"📚 Wissensbasis-Suche läuft...")
                    result = self.knowledge_lookup(arguments.get("query", ""), arguments.get("context", ""))
                else:
                    result = f"❌ Unbekannte Tool-Funktion: {function_name}"
                
                # Emit tool call result to frontend
                self.emit_workflow_update({
                    'type': 'tool_call_result',
                    'function': function_name,
                    'result': result if function_name in ['request_outline_approval', 'request_user_feedback', 'knowledge_lookup'] else 'Content generated successfully',
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                
                # Limitiere Output-Größe für Stabilität
                if len(str(result)) > 3000:
                    result = str(result)[:3000] + "... [Inhalt gekürzt für Tool-Output]"
                
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": str(result)
                })
                
                self.emit_status(f"✅ {function_name} abgeschlossen")
                
            except Exception as tool_error:
                error_msg = f"Tool-Fehler in {function_name}: {str(tool_error)}"
                self.emit_error(error_msg)
                
                # Emit error to workflow
                self.emit_workflow_update({
                    'type': 'tool_call_error',
                    'function': function_name,
                    'error': error_msg,
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": error_msg
                })
        
        # Tool-Outputs an OpenAI senden
        try:
            self.emit_status(f"📤 Sende {len(tool_outputs)} Tool-Outputs an OpenAI...")
            
            self.client.beta.threads.runs.submit_tool_outputs(
                thread_id=self.thread.id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            
            # Nach Tool-Outputs weiter überwachen
            self.emit_status("🔄 Tool-Ausführung abgeschlossen, warte auf finale Antwort...")
            
        except Exception as e:
            self.emit_error(f"❌ Tool-Output Submission Fehler: {e}")
            # Bei Tool-Output-Fehlern: Versuche Recovery
            self.emit_status("🔄 Versuche Recovery nach Tool-Output-Fehler...")
            time.sleep(2)
    
    def _call_assistant_by_role(self, role, arguments):
        """NEUE FUNKTION: Ruft Assistant basierend auf Rolle aus Datenbank auf"""
        
        # CRITICAL FIX: Fallback to supervisor if specific role is not available
        if role not in self.assistants:
            logger.warning(f"⚠️ Assistant role '{role}' not found in database, falling back to supervisor")
            if 'supervisor' in self.assistants:
                assistant_data = self.assistants['supervisor']
                logger.info(f"✅ Using supervisor assistant as fallback for {role}")
            else:
                logger.error(f"❌ No supervisor assistant available as fallback for {role}")
                return f"Assistant mit Rolle '{role}' nicht in Datenbank konfiguriert und kein Supervisor-Fallback verfügbar."
        else:
            assistant_data = self.assistants[role]
        
        try:
            self.emit_status(f"🤖 {assistant_data['name']} arbeitet (Rolle: {role})...")
            
            # Emit agent communication details
            self.emit_workflow_update({
                'type': 'agent_start',
                'agent': assistant_data['name'],
                'role': role,
                'model': assistant_data['model'],
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
            
            # Je nach Tool-Call die entsprechende Prompt erstellen
            if role == "content_creator":
                prompt = self._create_content_prompt(arguments)
            elif role == "didactic_expert":
                prompt = self._create_didactic_prompt(arguments)
            elif role == "quality_checker":
                prompt = self._create_quality_prompt(arguments)
            else:
                # Generic prompt for any role
                prompt = f"Als {role}: {str(arguments)}"
            
            # Emit the prompt being sent to agent
            self.emit_workflow_update({
                'type': 'agent_prompt',
                'agent': assistant_data['name'],
                'prompt': prompt[:200] + "..." if len(prompt) > 200 else prompt,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
            
            # ENHANCED ERROR HANDLING: More detailed OpenAI API call
            logger.info(f"🚀 Making OpenAI API call for {role} with model {assistant_data['model']}")
            
            # Assistant über OpenAI API aufrufen
            response = self.client.chat.completions.create(
                model=assistant_data['model'],
                messages=[
                    {"role": "system", "content": assistant_data['instructions']},
                    {"role": "user", "content": prompt}
                ],
                temperature=assistant_data.get('temperature', 0.3),
                max_tokens=assistant_data.get('max_tokens', 3000)
            )
            
            result = response.choices[0].message.content
            logger.info(f"✅ OpenAI API call successful for {role}, response length: {len(result)}")
            
            # Emit agent response summary
            self.emit_workflow_update({
                'type': 'agent_response',
                'agent': assistant_data['name'],
                'response': result[:300] + "..." if len(result) > 300 else result,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
            
            self.emit_status(f"✅ {assistant_data['name']} abgeschlossen")
            return result
            
        except Exception as e:
            logger.error(f"❌ OpenAI API call failed for {role}: {type(e).__name__}: {str(e)}")
            self.emit_error(f"⚠️ {assistant_data['name']} Fehler: {e}")
            return f"{assistant_data['name']} ist momentan nicht verfügbar. Fehler: {str(e)}"
    
    def _create_content_prompt(self, arguments):
        """Erstellt OPTIMIERTEN Prompt für Content Creator mit Quality-Focus"""
        topic = arguments.get("topic", "")
        instructions = arguments.get("instructions", "")
        
        return f"""🎯 AUFTRAG: Erstelle einen STRUKTUR-OPTIMIERTEN, hochwertigen Kursentwurf für "{topic}".

📋 QUALITY-REQUIREMENTS (Ziel: >7.5/10 Score):

🏗️ OBLIGATORISCHE STRUKTUR-ELEMENTE:
✅ Nummerierte Hauptkapitel (1., 2., 3., 4., 5.)
✅ Klare Unterkapitel mit Nummerierung (1.1, 1.2, etc.)
✅ Maximal 3 Hierarchie-Ebenen
✅ Logische Progression: Grundlagen → Anwendung → Vertiefung

📚 LERNZIELE (OBLIGATORISCH für Score >5.0):
✅ 3-5 konkrete Lernziele pro Hauptkapitel
✅ Format: "Nach diesem Kapitel können Sie..."
✅ Messbare, spezifische Outcomes
✅ SMART-Kriterien befolgen

🎓 DIDAKTISCHE STRUKTUR:
✅ Einführung mit Motivation und Überblick
✅ Jeder Abschnitt: Ziel → Inhalt → Beispiel → Checkpoint
✅ Mindestens 1 praktisches Beispiel pro Hauptkonzept  
✅ Kurze Zusammenfassung am Ende jedes Kapitels
✅ Wissencheck-Fragen nach jedem Hauptkapitel

📝 CONTENT-STANDARDS:
✅ Deutsche Sprache, professionelle Tonalität
✅ Konsistente Terminologie (Glossar-ready)
✅ Verständlich für Einsteiger bis Fortgeschrittene
✅ Actionable Content mit klaren Handlungsempfehlungen

🔍 QUALITÄTS-CHECKPOINTS:
✅ Jeder Abschnitt <500 Wörter für bessere Lesbarkeit
✅ Bullet Points für komplexe Listen
✅ Hervorhebungen für Schlüsselbegriffe
✅ Call-to-Action am Ende jedes Abschnitts

ADDITIONAL INSTRUCTIONS:
{instructions}

⚡ WICHTIG: Nutze knowledge_lookup ZUERST bei hochgeladenen Dateien für domain-spezifisches Wissen!

🎯 ERFOLGSKRITERIUM: Struktur-Score >8.0, Didaktik-Score >7.0, Gesamt-Score >7.5"""
    
    def _create_didactic_prompt(self, arguments):
        """Erstellt VERSTÄRKTEN Prompt für Didactic Expert mit Quality-Enforcement"""
        content = arguments.get("content", "")
        
        return f"""🎓 DIDAKTISCHE OPTIMIERUNG: Transformiere den Kurs von 4.0 auf >7.0 Didaktik-Score!

EINGANGSMATERIAL:
{content}

🚀 OPTIMIERUNGS-ZIELE (Score-Verbesserung):

📚 LERNZIEL-OPTIMIERUNG (Struktur-Boost):
✅ Prüfe: Sind 3-5 Lernziele pro Kapitel vorhanden?
✅ Erweitere fehlende Lernziele im Format: "Nach diesem Kapitel können Sie..."
✅ Konkretisiere vage Ziele zu messbaren Outcomes
✅ Verknüpfe Lernziele mit praktischen Anwendungen

🔍 BEISPIEL-INTEGRATION (Didaktik-Boost):
✅ MINIMUM: 2 konkrete Beispiele pro Hauptkonzept
✅ Mix aus: Real-World Cases, Code-Snippets, Step-by-Step Demos
✅ Progressiver Schwierigkeitsgrad: Einfach → Komplex
✅ Direkte Verbindung zu Lernzielen herstellen

📝 ZUSAMMENFASSUNGS-STRUKTUR:
✅ Kapitel-Zusammenfassung: 3-5 Kernpunkte als Bullet Points
✅ Lessons Learned: "Das Wichtigste in Kürze"  
✅ Next Steps: Klare Handlungsempfehlungen
✅ Checkpoint-Fragen: 2-3 Selbsttest-Fragen

🎯 INTERAKTIVE ELEMENTE:
✅ Reflexions-Prompts: "Überlegen Sie..." 
✅ Praxis-Aufgaben: "Probieren Sie aus..."
✅ Checklisten für komplexe Prozesse
✅ "Häufige Fehler"-Boxen mit Lösungen

📊 VERSTÄNDLICHKEITS-OPTIMIERUNG:
✅ Komplexe Begriffe sofort erklären (Glossar-ready)
✅ Lange Sätze aufteilen (max. 20 Wörter/Satz)
✅ Fachbegriffe konsistent verwenden
✅ Logische Übergänge zwischen Abschnitten

🎨 STRUKTUR-VERBESSERUNG:
✅ Einheitliche Kapitel-Templates verwenden
✅ Visueller Flow: Intro → Content → Example → Summary → Action
✅ Konsistente Formatierung und Hervorhebungen
✅ Klare Hierarchie beibehalten

🎯 ERFOLGSKRITERIUM: Didaktik-Score von 4.0 auf >7.0 steigern durch systematische Verbesserung aller Dimensionen!"""
    
    def _create_quality_prompt(self, arguments):
        """Erstellt GEHÄRTETEN Prompt für Quality Checker mit automatischen Quality Gates"""
        content = arguments.get("content", "")
        feedback = arguments.get("feedback", "")
        
        if feedback:
            # Regeneration mode with specific feedback
            return f"""🔍 QUALITÄTS-VERBESSERUNG: Korrigiere den Kurs basierend auf spezifischem Feedback!

URSPRÜNGLICHER KURS:
{content}

VERBESSERUNGS-ANWEISUNGEN:
{feedback}

⚡ DEINE AUFGABE:
Korrigiere den Kurs systematisch basierend auf dem Feedback und gib den VOLLSTÄNDIGEN, VERBESSERTEN KURS aus.

🎯 WICHTIG: 
- Gib NUR den korrigierten Kursinhalt aus
- KEIN JSON, keine Bewertung, keine Analyse
- Vollständiger Kurs mit allen Verbesserungen
- Alle Probleme behoben gemäß Feedback

AUSGABE: Der komplette, verbesserte Kurs in Markdown-Format."""

        else:
            # Standard quality check mode
            return f"""🔍 KRITISCHE QUALITÄTSPRÜFUNG: Prüfe und verbessere den Kurs!

ZU PRÜFENDER INHALT:
{content}

🚨 DEINE AUFGABEN:

1. QUALITÄTS-ANALYSE:
✅ Struktur prüfen: Lernziele, Hierarchie, Beispiele
✅ Didaktik bewerten: Verständlichkeit, Progression
✅ Konsistenz validieren: Terminologie, Sprache

2. SOFORTIGE VERBESSERUNG:
✅ Fehlende Lernziele ergänzen (3-5 pro Kapitel)
✅ Beispiele hinzufügen (min. 2 pro Hauptkonzept)
✅ Terminologie vereinheitlichen
✅ Sätze verkürzen (max. 20 Wörter)
✅ Zusammenfassungen ergänzen

⚡ KRITISCH WICHTIG:
Gib den VOLLSTÄNDIGEN, VERBESSERTEN KURS aus - NICHT das Assessment!

AUSGABE: Der komplette, qualitätssichere Kurs in Markdown-Format mit allen Verbesserungen."""
    
    def request_user_feedback(self, content: str, question: str, stage: str) -> str:
        """Bittet User um Feedback im Chat"""
        self.emit_status(f"👤 Feedback benötigt für: {stage}")
        
        # Feedback-Request an Chat senden
        feedback_msg = f"""## 🤔 Ihr Feedback ist gefragt!

**Stadium:** {stage}
**Frage:** {question}

{content[:500]}{'...' if len(content) > 500 else ''}

Bitte geben Sie Ihr Feedback oder bestätigen Sie die Freigabe."""
        
        self.emit_message(feedback_msg, "system")
        return "Warte auf User-Feedback im Chat..."
    
    def request_outline_approval(self, outline: str, quality_feedback: str, topic: str) -> str:
        """Bittet User um Freigabe für das Inhaltsverzeichnis"""
        self.emit_status(f"�� Freigabe für Inhaltsverzeichnis benötigt für: '{topic}'")
        
        approval_msg = f"""## 🤔 Ihre Freigabe ist gefragt!

**Thema:** {topic}
**Inhaltsverzeichnis:**
{outline}

**Feedback vom Quality Checker:**
{quality_feedback}

Bitte geben Sie Ihre Freigabe oder vorschlagen Sie Änderungen."""
        
        self.emit_message(approval_msg, "system")
        return "Warte auf User-Freigabe im Chat..."
    
    def knowledge_lookup(self, query: str, context: str = "") -> str:
        """Sucht in der projektspezifischen Wissensbasis"""
        self.emit_status(f"📚 Durchsuche Wissensbasis nach: '{query}'...")
        
        try:
            from knowledge_manager import knowledge_lookup
            result = knowledge_lookup(query, self.project_id, context)
            self.emit_status("✅ Wissenssuche abgeschlossen")
            return result
        except Exception as e:
            self.emit_error(f"⚠️ Wissensbasis-Fehler: {e}")
            return f"Die Wissensbasis für '{query}' ist momentan nicht verfügbar. Ich erstelle den Inhalt basierend auf allgemeinem Wissen."
    
    def _room(self):
        """Bestimmt den korrekten SocketIO-Raum."""
        if self.session_id:
            return f'session_{self.session_id}'
        if self.project_id:
            return f'project_{self.project_id}'
        return None
    
    # SocketIO Hilfsfunktionen (unverändert)
    def emit_message(self, message, sender="assistant", metadata=None):
        """Sendet Nachricht an Chat"""
        room = self._room()
        logger.info(f"📡 EMIT MESSAGE to room {room}: {message[:100]}...")
        self.socketio.emit('new_message', {
            'sender': 'KI-Assistant' if sender == 'assistant' else sender,
            'message': message,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'type': sender,
            'metadata': metadata or {}
        }, room=room)
    
    def emit_status(self, status):
        """Sendet Status-Update"""
        room = self._room()
        logger.info(f"📡 EMIT STATUS to room {room}: {status}")
        self.socketio.emit('status_update', {
            'status': status,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }, room=room)
    
    def emit_error(self, error):
        """Sendet Fehler-Nachricht"""
        room = self._room()
        logger.error(f"📡 EMIT ERROR to room {room}: {error}")
        self.socketio.emit('error_message', {
            'error': error,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }, room=room)
    
    def set_chat_mode(self, mode):
        """Setzt den Chat-Modus (collaborative/autonomous)"""
        self.chat_mode = mode
        self.emit_status(f"🔧 Modus geändert zu: {mode}")

    def _safe_encode(self, text: str) -> str:
        """Encodes large text blocks as BASE64 to avoid JSON issues"""
        return "BASE64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")

    def _safe_decode(self, text: str) -> str:
        if text.startswith("BASE64:"):
            try:
                return base64.b64decode(text[7:].encode("ascii")).decode("utf-8", errors="ignore")
            except Exception:
                return text  # fallback
        return text

    def _emit_course_content_update(self, stage, content):
        """Sendet Kursinhalt-Updates an das Frontend für das Ergebnis-Fenster"""
        if self.socketio and self.session_id:
            # Decode content if it's base64 encoded
            display_content = self._safe_decode(content) if content.startswith('BASE64:') else content
            
            self.socketio.emit('course_content_update', {
                'stage': stage,
                'content': display_content,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }, room=f'session_{self.session_id}')

    def emit_workflow_update(self, data):
        """Sendet Workflow-Updates an das Frontend"""
        if self.socketio and self.session_id:
            self.socketio.emit('workflow_update', data, room=f'session_{self.session_id}')

    def _generate_improvement_instructions(self, quality_scores):
        """Generiert spezifische Verbesserungs-Anweisungen basierend auf Quality-Scores"""
        improvements = []
        
        # Extract individual scores
        structure_score = quality_scores.get('component_scores', {}).get('structure', {}).get('score', 0)
        readability_score = quality_scores.get('component_scores', {}).get('readability', {}).get('score', 0) 
        consistency_score = quality_scores.get('component_scores', {}).get('consistency', {}).get('score', 0)
        overall_score = quality_scores.get('overall_score', 0)
        
        # Structure improvements
        if structure_score < 7.0:
            improvements.append(f"""
🏗️ STRUKTUR-VERBESSERUNG (aktuell: {structure_score:.1f}/10):
- Füge 3-5 konkrete Lernziele pro Hauptkapitel hinzu
- Erweitere Beispiele: MINIMUM 2 pro Hauptkonzept
- Ergänze Zusammenfassungen am Ende jeder Sektion
- Verbessere Nummerierung und Hierarchie-Struktur
""")
        
        # Readability improvements  
        if readability_score < 7.0:
            improvements.append(f"""
📖 LESBARKEITS-VERBESSERUNG (aktuell: {readability_score:.1f}/10):
- Teile lange Sätze auf (max. 20 Wörter)
- Erkläre Fachbegriffe beim ersten Auftreten
- Vereinfache komplexe Formulierungen
- Füge mehr Zwischenüberschriften ein
""")
        
        # Consistency improvements
        if consistency_score < 7.0:
            improvements.append(f"""
🎯 KONSISTENZ-VERBESSERUNG (aktuell: {consistency_score:.1f}/10):
- Verwende Fachbegriffe durchgehend einheitlich
- Standardisiere Format und Tonalität  
- Korrigiere widersprüchliche Aussagen
- Vereinheitliche Beispiel-Struktur
""")
        
        # Overall quality enforcement
        if overall_score < 7.0:
            improvements.append(f"""
⚠️ QUALITÄTS-GATE: Gesamt-Score {overall_score:.1f}/10 nicht ausreichend!
ZIEL: Mindestens 7.5/10 für Production-Release erforderlich.
Führe ALLE oben genannten Verbesserungen systematisch durch.
""")
        
        return "\n".join(improvements) if improvements else "✅ Qualität ausreichend - keine Verbesserungen erforderlich."

    def _is_course_creation_complete(self, response: str) -> bool:
        """Prüft, ob die KI-Antwort ein Indikator für das Abschluss des Kurserstellungsprozesses ist."""
        # More comprehensive completion indicators
        completion_indicators = [
            "Kurs wurde erfolgreich erstellt",
            "Der Kurs ist jetzt bereit",
            "Kurserstellung abgeschlossen",
            "Ihr Kurs ist fertig",
            "Der komplette Kurs"
        ]
        
        return any(indicator in response for indicator in completion_indicators)

    def _save_course_to_database(self, content: str):
        """Speichert den erstellten Kursinhalt in der Datenbank."""
        try:
            from models import db, Course, CourseSection
            from flask import current_app
            import json
            import re
            
            # CRITICAL FIX: Ensure we're in Flask app context
            with current_app.app_context():
                
                # Extract course metadata from content
                title = self._extract_course_title(content)
                description = self._extract_course_description(content)
                topic = self._extract_course_topic(content)
                
                logger.info(f"🎓 Saving course: '{title}' for user {self.session_id}")
                
                # Create new course record
                new_course = Course(
                    user_id=int(self.session_id) if self.session_id else 1,  # Fallback to user 1
                    project_id=int(self.project_id) if self.project_id and self.project_id != 'default' else None,
                    title=title,
                    description=description,
                    course_topic=topic,
                    full_content=content,
                    content_length=len(content),
                    status='draft'  # Set as draft initially
                )
                
                db.session.add(new_course)
                db.session.flush()  # Get the course ID
                
                # Extract and save course sections if possible
                sections = self._extract_course_sections(content)
                for i, section in enumerate(sections):
                    course_section = CourseSection(
                        course_id=new_course.id,
                        section_title=section.get('title', f'Kapitel {i+1}'),
                        section_content=section.get('content', ''),
                        section_order=i + 1,
                        section_type='chapter'
                    )
                    db.session.add(course_section)
                
                db.session.commit()
                
                logger.info(f"✅ Course saved with ID {new_course.id}: '{title}' ({len(sections)} sections)")
                
                # Store course ID for follow-up messages
                self.last_saved_course_id = new_course.id
                self.last_saved_course_title = title
                
                # Send helpful completion message to user
                completion_message = f"""✅ **Kurs erfolgreich gespeichert!**

**📚 {title}**
- **Kapitel:** {len(sections)}
- **Umfang:** {len(content):,} Zeichen
- **Status:** Entwurf

**🔗 Wo finde ich meinen Kurs?**
➜ [Zu "Meine Kurse"](/courses) - Alle gespeicherten Kurse
➜ [Diesen Kurs anzeigen](/courses/{new_course.id}) - Direkt zum Kurs

**📥 Aktionen:**
- Download als Textdatei
- In Zwischenablage kopieren
- Kurs bearbeiten oder veröffentlichen

Ihr Kurs wurde sicher in der Datenbank gespeichert und ist jederzeit abrufbar!"""

                # Emit completion message
                self.emit_message(completion_message, "assistant")
                
                # Emit course completion event to frontend
                self.emit_workflow_update({
                    'type': 'course_saved',
                    'course_id': new_course.id,
                    'title': title,
                    'status': 'saved',
                    'sections_count': len(sections),
                    'content_length': len(content),
                    'course_url': f'/courses/{new_course.id}'
                })
                
        except Exception as e:
            logger.error(f"❌ Error saving course to database: {type(e).__name__}: {str(e)}")
            self.emit_error(f"❌ Fehler beim Speichern des Kurses: {str(e)}")
            
    def _extract_course_title(self, content: str) -> str:
        """Extract course title from content"""
        # Look for markdown h1 or common title patterns
        title_patterns = [
            r'^#\s+(.+?)$',  # Markdown H1
            r'^\*\*(.+?)\*\*$',  # Bold title
            r'^(.+?)\s*(?:Kurs|Course)',  # Text before "Kurs" or "Course"
        ]
        
        lines = content.split('\n')
        for line in lines[:10]:  # Check first 10 lines
            line = line.strip()
            if not line:
                continue
            for pattern in title_patterns:
                match = re.search(pattern, line, re.MULTILINE)
                if match:
                    return match.group(1).strip()
        
        # Fallback: use first non-empty line or generate title
        for line in lines[:5]:
            if line.strip():
                return line.strip()[:100]  # Max 100 chars
                
        return f"KI-Kurs erstellt am {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    def _extract_course_description(self, content: str) -> str:
        """Extract course description from content"""
        lines = content.split('\n')
        description_lines = []
        
        # Look for description after title
        found_title = False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if not found_title and (line.startswith('#') or line.startswith('**')):
                found_title = True
                continue
            if found_title and len(description_lines) < 3:
                if not line.startswith('#') and not line.startswith('**'):
                    description_lines.append(line)
                else:
                    break
        
        return ' '.join(description_lines)[:500] if description_lines else "KI-generierter Kurs"
    
    def _extract_course_topic(self, content: str) -> str:
        """Extract course topic from content"""
        # This could be enhanced to extract from the original user input
        # For now, try to extract from the content
        if hasattr(self, '_original_topic') and self._original_topic:
            return self._original_topic
        
        # Try to extract from title
        title = self._extract_course_title(content)
        if 'AI' in title or 'KI' in title or 'Agent' in title:
            return 'AI & Machine Learning'
        elif 'Python' in title or 'Programm' in title:
            return 'Programming'
        elif 'Business' in title or 'Marketing' in title:
            return 'Business'
        else:
            return 'Allgemein'
    
    def _extract_course_sections(self, content: str) -> list:
        """Extract course sections from content"""
        sections = []
        lines = content.split('\n')
        current_section = None
        current_content = []
        
        for line in lines:
            line = line.strip()
            
            # Detect section headers (markdown H2, H3, or numbered)
            if (line.startswith('##') or 
                re.match(r'^\d+\.', line) or 
                re.match(r'^[A-Z][^.]*:$', line)):
                
                # Save previous section
                if current_section:
                    sections.append({
                        'title': current_section,
                        'content': '\n'.join(current_content).strip()
                    })
                
                # Start new section
                current_section = line.replace('#', '').strip()
                current_content = []
            else:
                if current_section and line:
                    current_content.append(line)
        
        # Save last section
        if current_section:
            sections.append({
                'title': current_section,
                'content': '\n'.join(current_content).strip()
            })
        
        return sections
    
    def _detect_intent(self, message: str) -> str:
        """
        Simple intent detection to categorize user messages
        Returns: 'greeting', 'small_talk', 'course_request', 'other'
        """
        message_lower = message.lower().strip()
        message_len = len(message)
        
        # Greeting patterns
        greeting_patterns = [
            'hallo', 'hi', 'hey', 'guten tag', 'guten morgen', 'guten abend',
            'servus', 'moin', 'hallöchen', 'grüß gott', 'grüß dich'
        ]
        
        # Small talk patterns
        small_talk_patterns = [
            'wie geht', 'was machst du', 'was kannst du', 'wer bist du',
            'danke', 'dankeschön', 'vielen dank', 'super', 'toll', 'prima',
            'ok', 'okay', 'alles klar', 'verstehe', 'gut'
        ]
        
        # Course request patterns  
        course_patterns = [
            'kurs', 'erstell', 'training', 'schulung', 'lerninhalt',
            'lektion', 'tutorial', 'workshop', 'seminar', 'modul'
        ]
        
        # Check for greetings (prioritize short messages)
        if message_len <= 20:
            for pattern in greeting_patterns:
                if pattern in message_lower:
                    return 'greeting'
        
        # Check for small talk
        for pattern in small_talk_patterns:
            if pattern in message_lower:
                return 'small_talk'
        
        # Check for course requests
        for pattern in course_patterns:
            if pattern in message_lower:
                return 'course_request'
        
        # Default classification based on length and content
        if message_len <= 30 and not any(p in message_lower for p in course_patterns):
            return 'small_talk'
        
        return 'other'
    
    def _handle_simple_response(self, message: str, intent: str):
        """
        Handle simple responses for greetings and small talk without triggering workflow
        """
        self._update_activity()
        
        if intent == 'greeting':
            responses = [
                "Hallo! Schön, Sie zu sehen. Wie kann ich Ihnen heute helfen?",
                "Hi! Ich bin Ihr KI-Assistent für die Kurserstellung. Was kann ich für Sie tun?",
                "Guten Tag! Möchten Sie einen neuen Kurs erstellen oder haben Sie Fragen?",
                "Hallo! Ich freue mich, Ihnen bei der Kurserstellung helfen zu können."
            ]
        elif intent == 'small_talk':
            if any(word in message.lower() for word in ['danke', 'dankeschön', 'vielen dank']):
                responses = [
                    "Gerne! Falls Sie weitere Fragen haben, bin ich da.",
                    "Sehr gerne! Kann ich Ihnen noch bei etwas anderem helfen?",
                    "Freut mich, dass ich helfen konnte!"
                ]
            elif any(word in message.lower() for word in ['wie geht', 'was machst du', 'was kannst du']):
                responses = [
                    "Ich bin Ihr KI-Assistent für die automatische Kurserstellung. Ich kann professionelle Lerninhalte zu jedem Thema erstellen.",
                    "Mir geht es gut, danke! Ich helfe dabei, hochwertige Online-Kurse zu entwickeln. Haben Sie ein bestimmtes Thema im Kopf?",
                    "Ich spezialisiere mich auf die Erstellung von strukturierten Lerninhalten mit didaktischer Optimierung."
                ]
            else:
                responses = [
                    "Das freut mich! Möchten Sie einen Kurs zu einem bestimmten Thema erstellen?",
                    "Schön! Womit kann ich Ihnen konkret helfen?",
                    "Wenn Sie Fragen haben oder einen Kurs erstellen möchten, sagen Sie einfach Bescheid!"
                ]
        else:
            responses = ["Wie kann ich Ihnen helfen?"]
        
        # Select first response (can be randomized later)
        response = responses[0]
        
        # Send response directly without workflow
        self.emit_message(response, "assistant")
        logger.info(f"📤 Simple response sent for {intent}: {response[:50]}...")

# Legacy-Kompatibilität für bestehenden Code
ChatOrchestrator = DynamicChatOrchestrator

# Global orchestrator instance für Web-App Integration
active_orchestrators = {} 