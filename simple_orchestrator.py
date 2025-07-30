"""
Vereinfachter Chat-Orchestrator für Kiki Chat
Direkte Integration mit spezifizierten OpenAI Assistenten

Unterstützte Assistenten:
- Supervisor (asst_19FlW2QtTAIb7Z96f3ukfSre) - gpt-4.1-nano
- Der Autor (asst_UCpHRYdDK2uPsb7no8Zw5Z0p) - gpt-4.1-nano  
- Der Pädagoge (asst_tmj7Nz75MSwjPSrBf4KV2EIt) - gpt-4.1-nano
- Der Prüfer (asst_qH5a6MsVByLHP2ZLQ8gT8jg0) - gpt-4.1-nano
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Any

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ==============================================
# OPENAI CLIENT & ASSISTANT CONFIGURATION
# ==============================================

class SimpleOrchestrator:
    """
    Vereinfachter Orchestrator für direkte OpenAI Assistant Integration
    
    Features:
    - Direkte Tool-Call-Unterstützung
    - Vereinfachter 3-Schritt-Workflow
    - SocketIO Integration
    - Automatische Qualitätsprüfung
    """
    
    # Assistant Configuration (as specified)
    ASSISTANTS = {
        'supervisor': {
            'id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',
            'name': 'Supervisor', 
            'model': 'gpt-4.1-nano'
        },
        'content_creator': {
            'id': 'asst_UCpHRYdDK2uPsb7no8Zw5Z0p',
            'name': 'Der Autor',
            'model': 'gpt-4.1-nano'
        },
        'didactic_expert': {
            'id': 'asst_tmj7Nz75MSwjPSrBf4KV2EIt', 
            'name': 'Der Pädagoge',
            'model': 'gpt-4.1-nano'
        },
        'quality_checker': {
            'id': 'asst_qH5a6MsVByLHP2ZLQ8gT8jg0',
            'name': 'Der Prüfer',
            'model': 'gpt-4.1-nano'
        }
    }
    
    def __init__(self, project_id: str, session_id: str, socketio):
        self.project_id = project_id
        self.session_id = session_id
        self.socketio = socketio
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        
        self.thread = None
        self.current_run = None
        self.is_processing = False
        
        # Load supervisor assistant
        self.supervisor_assistant = None
        self._load_supervisor()
    
    def _load_supervisor(self):
        """Load and configure supervisor assistant"""
        try:
            supervisor_config = self.ASSISTANTS['supervisor']
            self.supervisor_assistant = self.client.beta.assistants.retrieve(supervisor_config['id'])
            
            # Update tools to ensure they're current
            required_tools = self._get_required_tools()
            
            self.supervisor_assistant = self.client.beta.assistants.update(
                assistant_id=supervisor_config['id'],
                tools=required_tools
            )
            
            self.emit_status(f"✅ Supervisor loaded: {supervisor_config['name']}")
            logger.info(f"Supervisor assistant loaded: {supervisor_config['id']}")
            
        except Exception as e:
            self.emit_error(f"❌ Failed to load supervisor: {e}")
            logger.error(f"Supervisor loading error: {e}")
    
    def _get_required_tools(self):
        """Define required tools for supervisor"""
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
    
    def process_message(self, message: str, user_data: Dict):
        """Main method to process user messages"""
        if self.is_processing:
            self.emit_message("⏳ Ein anderer Prozess läuft bereits. Bitte warten Sie.", "assistant")
            return
        
        if not self.supervisor_assistant:
            self.emit_error("❌ Supervisor assistant not available")
            return
        
        self.is_processing = True
        self.emit_status("🤖 AI-Agent arbeitet...")
        
        try:
            # Create thread if needed
            if not self.thread:
                self.thread = self.client.beta.threads.create()
                self.emit_status("✅ Neuer Thread erstellt")
            
            # Add message to thread
            self.client.beta.threads.messages.create(
                thread_id=self.thread.id,
                role="user",
                content=message
            )
            
            # Start run
            self.current_run = self.client.beta.threads.runs.create(
                thread_id=self.thread.id,
                assistant_id=self.supervisor_assistant.id
            )
            
            # Monitor run
            self._monitor_run()
            
        except Exception as e:
            self.emit_error(f"❌ Processing error: {e}")
            logger.error(f"Message processing error: {e}")
        finally:
            self.is_processing = False
    
    def _monitor_run(self):
        """Monitor run status and handle tool calls"""
        max_iterations = 50
        iteration = 0
        
        while iteration < max_iterations:
            try:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=self.thread.id,
                    run_id=self.current_run.id
                )
                
                if run.status == "completed":
                    # Get final response
                    messages = self.client.beta.threads.messages.list(
                        thread_id=self.thread.id,
                        limit=1
                    )
                    
                    if messages.data and messages.data[0].content:
                        response = messages.data[0].content[0].text.value
                        self.emit_message(response, "assistant")
                    break
                    
                elif run.status == "requires_action":
                    # Handle tool calls
                    self._handle_tool_calls(run)
                    continue
                    
                elif run.status in ["failed", "cancelled", "expired"]:
                    self.emit_error(f"❌ Run failed: {run.status}")
                    break
                    
                elif run.status in ["queued", "in_progress"]:
                    self.emit_status(f"⏳ Processing... ({run.status})")
                
                time.sleep(2)
                iteration += 1
                
            except Exception as e:
                self.emit_error(f"❌ Monitoring error: {e}")
                break
        
        if iteration >= max_iterations:
            self.emit_error("⏰ Processing timeout")
    
    def _handle_tool_calls(self, run):
        """Handle tool calls from supervisor"""
        tool_outputs = []
        
        for tool_call in run.required_action.submit_tool_outputs.tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            
            self.emit_status(f"🔧 Executing {function_name}...")
            
            try:
                if function_name == "create_content":
                    result = self._call_content_creator(arguments)
                elif function_name == "optimize_didactics":
                    result = self._call_didactic_expert(arguments)
                elif function_name == "critically_review":
                    result = self._call_quality_checker(arguments)
                elif function_name == "request_outline_approval":
                    result = self._request_outline_approval(arguments)
                elif function_name == "request_user_feedback":
                    result = self._request_user_feedback(arguments)
                elif function_name == "knowledge_lookup":
                    result = self._knowledge_lookup(arguments)
                else:
                    result = f"❌ Unknown function: {function_name}"
                
                # Limit output size
                if len(str(result)) > 4000:
                    result = str(result)[:4000] + "... [Content truncated]"
                
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": str(result)
                })
                
                self.emit_status(f"✅ {function_name} completed")
                
            except Exception as e:
                error_msg = f"Error in {function_name}: {str(e)}"
                self.emit_error(error_msg)
                
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": error_msg
                })
        
        # Submit tool outputs
        try:
            self.client.beta.threads.runs.submit_tool_outputs(
                thread_id=self.thread.id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
        except Exception as e:
            self.emit_error(f"❌ Tool output submission error: {e}")
    
    def _call_content_creator(self, arguments):
        """Call content creator assistant"""
        assistant_config = self.ASSISTANTS['content_creator']
        topic = arguments.get('topic', '')
        instructions = arguments.get('instructions', '')
        content_type = arguments.get('content_type', 'full_content')
        
        self.emit_status(f"🖊️ {assistant_config['name']} erstellt Inhalte...")
        
        # Check for knowledge base first
        try:
            knowledge_result = self._knowledge_lookup({'query': topic})
            knowledge_context = f"\n\nVerfügbare Wissensbasis:\n{knowledge_result}" if "Keine relevanten" not in knowledge_result else ""
        except:
            knowledge_context = ""
        
        prompt = f"""Thema: {topic}
Anweisungen: {instructions}
Content-Typ: {content_type}
{knowledge_context}

Erstelle professionellen Kursinhalt basierend auf diesen Anforderungen."""
        
        return self._call_assistant(assistant_config['id'], prompt)
    
    def _call_didactic_expert(self, arguments):
        """Call didactic expert assistant"""
        assistant_config = self.ASSISTANTS['didactic_expert']
        content = arguments.get('content', '')
        
        self.emit_status(f"🎓 {assistant_config['name']} optimiert didaktisch...")
        
        prompt = f"""Zu optimierender Kursinhalt:

{content}

Führe eine vollständige didaktische Optimierung durch."""
        
        return self._call_assistant(assistant_config['id'], prompt)
    
    def _call_quality_checker(self, arguments):
        """Call quality checker assistant"""
        assistant_config = self.ASSISTANTS['quality_checker']
        content = arguments.get('content', '')
        review_type = arguments.get('review_type', 'full_content')
        
        self.emit_status(f"🔍 {assistant_config['name']} prüft Qualität...")
        
        prompt = f"""Zu prüfender Inhalt ({review_type}):

{content}

Führe eine kritische Qualitätsprüfung durch und gib das Ergebnis im JSON-Format aus."""
        
        result = self._call_assistant(assistant_config['id'], prompt)
        
        # Try to extract quality score for status update
        try:
            if '{' in result and '}' in result:
                json_start = result.find('{')
                json_end = result.rfind('}') + 1
                quality_data = json.loads(result[json_start:json_end])
                
                overall_score = quality_data.get('scores', {}).get('overall_weighted', 0)
                if overall_score >= 7.0:
                    self.emit_status(f"✅ Quality Score: {overall_score}/10 - Qualitätsziel erreicht")
                else:
                    self.emit_status(f"⚠️ Quality Score: {overall_score}/10 - Verbesserung empfohlen")
        except:
            pass
        
        return result
    
    def _call_assistant(self, assistant_id: str, prompt: str):
        """Generic method to call any assistant"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-4",  # Fallback model if specific model not available
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Assistant call error for {assistant_id}: {e}")
            return f"Assistant {assistant_id} is currently unavailable. Error: {str(e)}"
    
    def _request_outline_approval(self, arguments):
        """Request outline approval from user"""
        outline = arguments.get('outline', '')
        quality_feedback = arguments.get('quality_feedback', '')
        topic = arguments.get('topic', '')
        
        approval_msg = f"""## 📋 Inhaltsverzeichnis zur Freigabe

**Thema:** {topic}

**Vorgeschlagene Gliederung:**
{outline}

**Qualitätsbewertung:**
{quality_feedback}

---
**Bitte bestätigen Sie die Freigabe oder schlagen Sie Änderungen vor.**"""
        
        self.emit_message(approval_msg, "system")
        return "Warte auf User-Freigabe für das Inhaltsverzeichnis..."
    
    def _request_user_feedback(self, arguments):
        """Request user feedback"""
        content = arguments.get('content', '')
        question = arguments.get('question', '')
        stage = arguments.get('stage', '')
        
        feedback_msg = f"""## 🎯 Ihr Feedback ist gefragt!

**Stadium:** {stage}
**Frage:** {question}

**Erstellter Kurs:**
{content[:1000]}{'...' if len(content) > 1000 else ''}

---
**Bitte geben Sie Ihr Feedback oder bestätigen Sie die Freigabe.**"""
        
        self.emit_message(feedback_msg, "system")
        return "Warte auf User-Feedback..."
    
    def _knowledge_lookup(self, arguments):
        """Search knowledge base"""
        query = arguments.get('query', '')
        
        try:
            from knowledge_manager import knowledge_lookup
            result = knowledge_lookup(query, self.project_id)
            return result
        except Exception as e:
            logger.warning(f"Knowledge lookup error: {e}")
            return f"Wissensbasis für '{query}' ist momentan nicht verfügbar."
    
    # SocketIO Helper Methods
    def emit_message(self, message, sender="assistant"):
        """Send message to chat"""
        room = f'session_{self.session_id}'
        self.socketio.emit('new_message', {
            'sender': 'AI-Assistant' if sender == 'assistant' else sender,
            'message': message,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'type': sender
        }, room=room)
    
    def emit_status(self, status):
        """Send status update"""
        room = f'session_{self.session_id}'
        self.socketio.emit('status_update', {
            'status': status,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }, room=room)
    
    def emit_error(self, error):
        """Send error message"""
        room = f'session_{self.session_id}'
        self.socketio.emit('error_message', {
            'error': error,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }, room=room)

# ==============================================
# ORCHESTRATOR MANAGEMENT
# ==============================================

# Global orchestrator instances
active_orchestrators: Dict[str, SimpleOrchestrator] = {}

def get_or_create_orchestrator(project_id: str, session_id: str, socketio) -> SimpleOrchestrator:
    """Get or create orchestrator instance"""
    orchestrator_key = f"{project_id}_{session_id}"
    
    if orchestrator_key not in active_orchestrators:
        orchestrator = SimpleOrchestrator(
            project_id=project_id,
            session_id=session_id,
            socketio=socketio
        )
        active_orchestrators[orchestrator_key] = orchestrator
        logger.info(f"Created new orchestrator: {orchestrator_key}")
    
    return active_orchestrators[orchestrator_key]

def cleanup_inactive_orchestrators():
    """Clean up inactive orchestrators (for memory management)"""
    # Simple cleanup - can be enhanced with TTL logic
    if len(active_orchestrators) > 10:
        # Remove oldest orchestrators
        keys_to_remove = list(active_orchestrators.keys())[:5]
        for key in keys_to_remove:
            del active_orchestrators[key]
        logger.info(f"Cleaned up {len(keys_to_remove)} orchestrators")