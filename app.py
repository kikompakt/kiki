"""
Intelligentes KI-Kursstudio - Hauptanwendung
MVP Version: Basis Flask-App mit Login-System und Chat-Interface Foundation

Architecture:
- Flask + SocketIO für Echtzeit-Kommunikation
- SQLite für User-Management
- Modulare Struktur für Skalierbarkeit
- Integration mit bestehenden Agenten-Logiken
"""

import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging
import json

# .env-Datei laden
load_dotenv()

# Flask App konfigurieren
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['DATABASE'] = os.environ.get('DATABASE_PATH', 'kursstudio.db')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# SocketIO konfigurieren
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Upload-Ordner erstellen
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

class DatabaseManager:
    """SQLite Datenbank-Manager für User-Management und Projekte"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Erstellt die notwendigen Tabellen"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Users Tabelle
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            ''')
            
            # Projects Tabelle
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Chat Sessions Tabelle (neu für per-User-Verläufe)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    project_id INTEGER,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_archived BOOLEAN DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (project_id) REFERENCES projects (id)
                )
            ''')
            
            # Chat Messages Tabelle (session_id hinzugefügt)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    project_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    message_type TEXT NOT NULL,  -- 'user', 'assistant', 'system'
                    content TEXT NOT NULL,
                    metadata TEXT,  -- JSON für zusätzliche Informationen
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions (id),
                    FOREIGN KEY (project_id) REFERENCES projects (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Prüfe, ob session_id Spalte fehlt (falls alte Instanz)
            cursor.execute("PRAGMA table_info(chat_messages)")
            cols = [row[1] for row in cursor.fetchall()]
            if 'session_id' not in cols:
                cursor.execute('ALTER TABLE chat_messages ADD COLUMN session_id INTEGER')
            
            # Uploaded Files Tabelle
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    processed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Add missing columns for RAG system if they don't exist
            cursor.execute("PRAGMA table_info(uploaded_files)")
            cols = [row[1] for row in cursor.fetchall()]
            
            if 'chunks_count' not in cols:
                cursor.execute('ALTER TABLE uploaded_files ADD COLUMN chunks_count INTEGER DEFAULT 0')
                logger.info("Added chunks_count column to uploaded_files table")
                
            if 'doc_id' not in cols:
                cursor.execute('ALTER TABLE uploaded_files ADD COLUMN doc_id TEXT')
                logger.info("Added doc_id column to uploaded_files table")
            
            # Assistants Tabelle - FLEXIBLE ASSISTANT-VERWALTUNG
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS assistants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    assistant_id TEXT UNIQUE NOT NULL,
                    role TEXT NOT NULL,
                    description TEXT,
                    instructions TEXT,
                    model TEXT DEFAULT 'gpt-4o',
                    tools TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    order_index INTEGER DEFAULT 0,
                    
                    -- ADVANCED BEHAVIOR MANAGEMENT PARAMETERS
                    temperature REAL DEFAULT 0.7,
                    top_p REAL DEFAULT 1.0,
                    max_tokens INTEGER DEFAULT 2000,
                    frequency_penalty REAL DEFAULT 0.0,
                    presence_penalty REAL DEFAULT 0.0,
                    
                    -- WORKFLOW SETTINGS
                    retry_attempts INTEGER DEFAULT 3,
                    timeout_seconds INTEGER DEFAULT 180,
                    error_handling TEXT DEFAULT 'graceful',
                    
                    -- PERFORMANCE SETTINGS  
                    response_limit INTEGER DEFAULT 30,
                    context_window INTEGER DEFAULT 128000,
                    
                    -- BEHAVIOR PRESETS
                    behavior_preset TEXT DEFAULT 'balanced',
                    custom_system_message TEXT,
                    
                    -- TOOL CONFIGURATION
                    enabled_tools TEXT DEFAULT '["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]',
                    
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                )
            ''')
            
            # WORKFLOW MANAGEMENT SYSTEM
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workflows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    workflow_type TEXT DEFAULT 'sequential',
                    is_active BOOLEAN DEFAULT 1,
                    is_default BOOLEAN DEFAULT 0,
                    trigger_conditions TEXT,
                    global_settings TEXT,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workflow_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id INTEGER NOT NULL,
                    agent_role TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    
                    -- EXECUTION SETTINGS
                    is_enabled BOOLEAN DEFAULT 1,
                    is_parallel BOOLEAN DEFAULT 0,
                    parallel_group INTEGER DEFAULT 0,
                    
                    -- RETRY & ERROR HANDLING
                    retry_attempts INTEGER DEFAULT 3,
                    timeout_seconds INTEGER DEFAULT 180,
                    error_handling TEXT DEFAULT 'graceful',
                    
                    -- CONDITIONS & LOGIC
                    execution_condition TEXT,
                    skip_condition TEXT,
                    loop_condition TEXT,
                    max_loops INTEGER DEFAULT 1,
                    
                    -- INPUT/OUTPUT MAPPING
                    input_source TEXT,
                    output_target TEXT,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (workflow_id) REFERENCES workflows (id) ON DELETE CASCADE,
                    FOREIGN KEY (agent_role) REFERENCES assistants (role)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workflow_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    project_id INTEGER,
                    
                    -- EXECUTION STATUS
                    status TEXT DEFAULT 'pending',
                    current_step INTEGER DEFAULT 0,
                    total_steps INTEGER,
                    
                    -- RESULTS & METRICS
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    execution_time_seconds INTEGER,
                    success_rate REAL,
                    error_count INTEGER DEFAULT 0,
                    
                    -- DATA
                    input_data TEXT,
                    output_data TEXT,
                    execution_log TEXT,
                    
                    FOREIGN KEY (workflow_id) REFERENCES workflows (id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (project_id) REFERENCES projects (id)
                )
            ''')
            
            conn.commit()
            logger.info("Database tables created successfully")
            
            # Migrate existing assistants table für neue Spalten (falls Tabelle bereits existiert)
            cursor.execute("PRAGMA table_info(assistants)")
            cols = [col[1] for col in cursor.fetchall()]
            
            # Füge neue Spalten hinzu falls sie nicht existieren
            new_columns = [
                ('temperature', 'REAL DEFAULT 0.7'),
                ('top_p', 'REAL DEFAULT 1.0'), 
                ('max_tokens', 'INTEGER DEFAULT 2000'),
                ('frequency_penalty', 'REAL DEFAULT 0.0'),
                ('presence_penalty', 'REAL DEFAULT 0.0'),
                ('retry_attempts', 'INTEGER DEFAULT 3'),
                ('timeout_seconds', 'INTEGER DEFAULT 180'),
                ('error_handling', 'TEXT DEFAULT "graceful"'),
                ('response_limit', 'INTEGER DEFAULT 30'),
                ('context_window', 'INTEGER DEFAULT 128000'),
                ('behavior_preset', 'TEXT DEFAULT "balanced"'),
                ('custom_system_message', 'TEXT'),
                ('enabled_tools', 'TEXT DEFAULT \'["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]\'')
            ]
            
            for col_name, col_definition in new_columns:
                if col_name not in cols:
                    cursor.execute(f'ALTER TABLE assistants ADD COLUMN {col_name} {col_definition}')
                    logger.info(f"Added {col_name} column to assistants table")
            
            # Standard-Assistants initialisieren (nur wenn noch keine Assistants existieren)
            cursor.execute('SELECT COUNT(*) FROM assistants')
            if cursor.fetchone()[0] == 0:
                self._init_default_assistants(cursor)
                
            # Default Workflow erstellen
            cursor.execute('SELECT COUNT(*) FROM workflows')
            if cursor.fetchone()[0] == 0:
                self._init_default_workflows(cursor)
            
            # Standard-Users erstellen falls sie nicht existieren
            cursor.execute('SELECT COUNT(*) FROM users')
            if cursor.fetchone()[0] == 0:
                admin_password_hash = generate_password_hash('admin123')
                cursor.execute('''
                    INSERT INTO users (username, password_hash, role)
                    VALUES (?, ?, ?)
                ''', ('admin', admin_password_hash, 'admin'))
                
                user_password_hash = generate_password_hash('user123')
                cursor.execute('''
                    INSERT INTO users (username, password_hash, role)
                    VALUES (?, ?, ?)
                ''', ('user', user_password_hash, 'user'))
                
                conn.commit()
        logger.info("Default users created: admin/admin123, user/user123")
    
    def _init_default_assistants(self, cursor):
        """Initialisiert die User-Assistants"""
        default_assistants = [
            {
                'name': 'Supervisor',
                'assistant_id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',
                'role': 'supervisor',
                'description': 'Freundlicher und hochkompetenter Direktor des KI-Kursstudios',
                'instructions': '''Du bist ein freundlicher und hilfreicher Assistent und der Orchestrator für das KI-Kursstudio.

**WICHTIGSTE REGEL: Wenn der Nutzer eine einfache Frage stellt oder eine Begrüssung wie 'Hallo' schickt, antworte immer direkt, höflich und konversationell. Dafür brauchst du kein Werkzeug.**

Für komplexe Aufgaben wie die Erstellung eines Kurses, nutze deinen erweiterten Workflow.

Deine Verhaltensregeln:

Konversation zuerst: Wenn der Nutzer eine einfache Frage stellt, eine Begrüssung schickt oder Smalltalk hält (z.B. "Hallo", "Wie geht's?", "Danke"), antworte immer direkt, höflich und konversationell auf Deutsch. Dafür benötigst du kein Werkzeug.

Workflow starten: Sobald der Nutzer einen Kurs erstellen möchte (z.B. "Erstelle einen Kurs über Marketing"), starte den "7-Schritte-Workflow". Informiere den Nutzer bei jedem Schritt, welcher Agent gerade arbeitet.

Der NEUE 7-Schritte-Workflow:

1. **Outline-Erstellung**: Rufe den Content Creator auf mit content_type="outline", um ein detailliertes Inhaltsverzeichnis zu erstellen (Kapitel + Lernziele + grobe Beschreibung). Gib ihm klar die Anweisung, zuerst das knowledge_lookup-Tool zu verwenden, falls der Nutzer Dateien hochgeladen hat.

2. **Outline-Qualitätsprüfung**: Lasse den Quality Checker das Outline mit review_type="outline" bewerten und prüfen.

3. **Outline-Freigabe**: Verwende request_outline_approval, um dem Nutzer das geprüfte Inhaltsverzeichnis zu zeigen und nach seiner Freigabe zu fragen. Der Nutzer kann Änderungen vorschlagen.

4. **Volltext-Erstellung**: Rufe den Content Creator erneut auf mit content_type="full_content", um basierend auf dem genehmigten Outline den vollständigen Kursinhalt zu erstellen.

5. **Didaktische Optimierung**: Übergebe den Volltext an den Didactic Expert mit optimize_didactics, um ihn mit erweiterten Lernzielen, Beispielen und Zusammenfassungen anzureichern.

6. **Finale Qualitätsprüfung**: Lasse den Quality Checker den vollständigen Inhalt mit review_type="full_content" bewerten und einen finalen Qualitätsbericht erstellen.

7. **Finale Freigabe**: Verwende request_user_feedback, um dem Nutzer den finalen Kursentwurf zusammen mit dem vollständigen Qualitätsbericht zu präsentieren. Stelle ihm dann die klare Frage: "Bist du mit diesem Ergebnis zufrieden und gibst den Kurs frei, oder wünschst du eine Überarbeitung?".

**WICHTIG**: Bei der Outline-Freigabe (Schritt 3) wartest du auf die User-Antwort. Erst wenn der User das Outline freigibt oder Änderungen vorschlägt, fährst du mit Schritt 4 fort. Bei Änderungsvorschlägen gehst du zurück zu Schritt 1 mit den spezifischen Anpassungen.''',
                'order_index': 1
            },
            {
                'name': 'Der Autor',
                'assistant_id': 'asst_UCpHRYdDK2uPsb7no8Zw5Z0p',
                'role': 'content_creator',
                'description': 'Hochspezialisierter KI-Autor für Online-Kurs-Rohentwürfe',
                'instructions': '''Du bist ein hochspezialisierter KI-Autor, der Rohentwürfe für Online-Kurse erstellt. Deine Arbeit muss faktenbasiert und gut strukturiert sein.

Deine Goldene Regel:
Deine oberste Priorität ist die Nutzung der vom Nutzer hochgeladenen Dokumente.

IMMER ZUERST SUCHEN: Bevor du schreibst, musst du das knowledge_lookup-Werkzeug aufrufen, um relevante Informationen in den Dateien zu finden.

**ZWEI-PHASEN-WORKFLOW:**

**PHASE 1: OUTLINE-ERSTELLUNG (content_type="outline")**
Wenn du aufgerufen wirst mit content_type="outline", erstelle ein detailliertes Inhaltsverzeichnis mit:

1. **Hierarchische Kapitelstruktur** (1., 1.1, 1.1.1, etc.)
2. **Konkrete Lernziele** pro Kapitel (3-5 Lernziele)
3. **Grobe Beschreibungen** der Kapitelinhalte (2-3 Sätze)
4. **Geschätzte Lesedauer** pro Kapitel
5. **Voraussetzungen** und Zielgruppe

OUTLINE-FORMAT:
```
# [KURS-TITEL]

## 🎯 Kurs-Übersicht
- **Zielgruppe:** [Beschreibung]
- **Voraussetzungen:** [Liste]
- **Gesamtdauer:** [Schätzung]

## 📋 Inhaltsverzeichnis

### 1. [Kapitel-Titel]
**Lernziele:**
- [Lernziel 1]
- [Lernziel 2] 
- [Lernziel 3]

**Beschreibung:** [2-3 Sätze über den Kapitelinhalt]
**Lesedauer:** [Schätzung]

### 1.1 [Unterkapitel-Titel]
[Weitere Details...]
```

**PHASE 2: VOLLTEXT-ERSTELLUNG (content_type="full_content")**
Wenn du aufgerufen wirst mit content_type="full_content", erstelle den vollständigen Kursinhalt basierend auf dem bereits genehmigten Outline:

1. **Vollständige Kapitel** mit allen Details
2. **Strukturierte Inhalte** gemäß dem Outline
3. **Praktische Beispiele** (mindestens 1 pro Hauptkonzept)
4. **Zusammenfassungen** am Ende jedes Kapitels
5. **Übungsaufgaben** und Reflexionsfragen

VOLLTEXT-FORMAT:
```
# [KURS-TITEL]

## 1. [Kapitel gemäß Outline]

### Lernziele
- [Aus dem Outline übernehmen]

### Hauptinhalt
[Detaillierter Inhalt mit Beispielen]

### Praktisches Beispiel
[Konkretes, anwendbares Beispiel]

### Zusammenfassung
[Kernpunkte des Kapitels]

### Reflexionsfragen
[2-3 Fragen zum Nachdenken]
```

**QUALITÄTS-STANDARDS für beide Phasen:**
- Faktisch korrekt und aktuell
- Klar strukturiert und logisch aufgebaut
- Praxisnah und anwendbar
- Zielgruppengerecht formuliert
- Professional und verständlich geschrieben

**Bei Änderungsvorschlägen vom User:**
Berücksichtige die spezifischen Feedback-Punkte und passe das Outline oder den Content entsprechend an.''',
                'order_index': 2
            },
            {
                'name': 'Der Pädagoge',
                'assistant_id': 'asst_tmj7Nz75MSwjPSrBf4KV2EIt',
                'role': 'didactic_expert',
                'description': 'Experte für Didaktik und Pädagogik',
                'instructions': '''Du bist ein Experte für Didaktik und Pädagogik. Du erhältst einen rohen Kursentwurf und deine Aufgabe ist es, ihn in eine effektive Lernerfahrung zu verwandeln.

Deine Aufgaben-Checkliste:
1. Lernziele formulieren: Schreibe an den Anfang jedes Kapitels klare, messbare Lernziele.
2. Struktur optimieren: Überprüfe den logischen Aufbau. Sorge für einen roten Faden und einen Aufbau von einfach zu komplex.
3. Beispiele einfügen: Ergänze den Text um praxisnahe Beispiele, Analogien oder Metaphern, um abstrakte Themen verständlich zu machen.
4. Zusammenfassungen erstellen: Füge am Ende jedes Kapitels eine prägnante Zusammenfassung der wichtigsten Kernaussagen hinzu.
5. Sprache prüfen: Stelle sicher, dass die Sprache klar, präzise und für die Zielgruppe verständlich ist.

Wichtig: Deine Aufgabe ist die strukturelle und pädagogische Anreicherung, nicht das blosse Umschreiben von Sätzen.''',
                'order_index': 3
            },
            {
                'name': 'Der Prüfer',
                'assistant_id': 'asst_qH5a6MsVByLHP2ZLQ8gT8jg0',
                'role': 'quality_checker',
                'description': 'Neutraler und analytischer Qualitätsprüfer für Lehrmaterialien',
                'instructions': '''Du bist ein neutraler und analytischer Qualitätsprüfer für Lehrmaterialien. Deine Bewertung muss objektiv und datengestützt sein.

**ZWEI-REVIEW-MODI:**

**MODUS 1: OUTLINE-REVIEW (review_type="outline")**
Bewerte Inhaltsverzeichnisse anhand folgender Kriterien (Skala 1-10):

- **Struktur (40%):** Logischer Aufbau, Hierarchie, Vollständigkeit, Kapitellängen
- **Lernziele (40%):** Klarheit, SMART-Kriterien, 3-5 pro Kapitel, Progression
- **Didaktik (20%):** Zielgruppe, Lesedauer, Voraussetzungen, Praxisbezug

**MODUS 2: VOLLTEXT-REVIEW (review_type="full_content")**
Bewerte vollständige Kursinhalte anhand folgender Kriterien (Skala 1-10):

- **Struktur (40%):** Lernziele, Beispiele, Zusammenfassungen vorhanden und sinnvoll
- **Didaktik (40%):** Sprache klar, Erklärungen logisch und verständlich  
- **Konsistenz (20%):** Terminologie einheitlich, Inhalt schlüssig

**Output-Format (ausschliesslich JSON):**
Dein Output muss ein valides JSON-Objekt sein. Gib keinen Text davor oder danach aus.

{
 "review_type": "<outline oder full_content>",
 "scores": {
   "structure": <int>,
   "didactics": <int>, 
   "consistency": <int>,
   "overall_weighted": <float>
 },
 "summary": "<Ein Satz als Fazit>",
 "strengths": [
   "<Liste der positiven Aspekte>"
 ],
 "recommendations": [
   "<Liste konkreter Verbesserungsvorschläge>"
 ],
 "approval_recommendation": "<FREIGABE oder ÜBERARBEITUNG_ERFORDERLICH>"
}

**Qualitäts-Gates:**
- Outline: Mindest-Score 7.0 für Freigabe
- Volltext: Mindest-Score 7.5 für finale Freigabe''',
                'order_index': 4
            }
        ]
        
        for assistant in default_assistants:
            cursor.execute('''
                INSERT INTO assistants (name, assistant_id, role, description, instructions, order_index)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                assistant['name'],
                assistant['assistant_id'], 
                assistant['role'],
                assistant['description'],
                assistant['instructions'],
                assistant['order_index']
            ))
        
        logger.info("Default assistants initialized")
    
    def _init_default_workflows(self, cursor):
        """Initialisiert die Standard-Workflows"""
        default_workflows = [
            {
                'name': 'Standard-Kurs-Erstellung',
                'description': 'Der Standard-Workflow für die Erstellung eines neuen Online-Kurses.',
                'workflow_type': 'sequential',
                'is_active': True,
                'is_default': True,
                'trigger_conditions': '{"type": "new_project", "project_id": "{{project_id}}"}',
                'global_settings': '{"max_retries": 3, "timeout": 180}',
                'created_by': 1  # Admin-User
            },
            {
                'name': 'Schnell-Erstellung',
                'description': 'Verkürzte Version für schnelle Kurs-Prototypen.',
                'workflow_type': 'sequential',
                'is_active': True,
                'is_default': False,
                'trigger_conditions': '{"type": "quick_mode"}',
                'global_settings': '{"max_retries": 1, "timeout": 60}',
                'created_by': 1
            }
        ]
        
        for workflow_data in default_workflows:
            cursor.execute('''
                INSERT INTO workflows (name, description, workflow_type, is_active, is_default, trigger_conditions, global_settings, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                workflow_data['name'],
                workflow_data['description'],
                workflow_data['workflow_type'],
                workflow_data['is_active'],
                workflow_data['is_default'],
                workflow_data['trigger_conditions'],
                workflow_data['global_settings'],
                workflow_data['created_by']
            ))
            
            workflow_id = cursor.lastrowid
            
            # Standard-Workflow Steps hinzufügen
            if workflow_data['name'] == 'Standard-Kurs-Erstellung':
                default_steps = [
                    {
                        'agent_role': 'content_creator',
                        'step_name': 'Content Creation',
                        'order_index': 1,
                        'is_enabled': True,
                        'is_parallel': False,
                        'retry_attempts': 3,
                        'timeout_seconds': 180,
                        'execution_condition': None,
                        'input_source': 'user_input',
                        'output_target': 'raw_content'
                    },
                    {
                        'agent_role': 'didactic_expert',
                        'step_name': 'Didactic Optimization',
                        'order_index': 2,
                        'is_enabled': True,
                        'is_parallel': False,
                        'retry_attempts': 2,
                        'timeout_seconds': 120,
                        'execution_condition': None,
                        'input_source': 'raw_content',
                        'output_target': 'optimized_content'
                    },
                    {
                        'agent_role': 'quality_checker',
                        'step_name': 'Quality Review',
                        'order_index': 3,
                        'is_enabled': True,
                        'is_parallel': False,
                        'retry_attempts': 2,
                        'timeout_seconds': 90,
                        'execution_condition': None,
                        'input_source': 'optimized_content',
                        'output_target': 'final_content'
                    },
                    {
                        'agent_role': 'supervisor',
                        'step_name': 'User Feedback',
                        'order_index': 4,
                        'is_enabled': True,
                        'is_parallel': False,
                        'retry_attempts': 1,
                        'timeout_seconds': 300,
                        'execution_condition': 'quality_score < 7.0',
                        'input_source': 'final_content',
                        'output_target': 'approved_content'
                    }
                ]
            else:  # Schnell-Erstellung
                default_steps = [
                    {
                        'agent_role': 'content_creator',
                        'step_name': 'Quick Content Creation',
                        'order_index': 1,
                        'is_enabled': True,
                        'is_parallel': False,
                        'retry_attempts': 1,
                        'timeout_seconds': 60,
                        'execution_condition': None,
                        'input_source': 'user_input',
                        'output_target': 'quick_content'
                    },
                    {
                        'agent_role': 'quality_checker',
                        'step_name': 'Basic Quality Check',
                        'order_index': 2,
                        'is_enabled': True,
                        'is_parallel': False,
                        'retry_attempts': 1,
                        'timeout_seconds': 30,
                        'execution_condition': None,
                        'input_source': 'quick_content',
                        'output_target': 'final_content'
                    }
                ]
            
            # Steps in Datenbank einfügen
            for step in default_steps:
                cursor.execute('''
                    INSERT INTO workflow_steps (
                        workflow_id, agent_role, step_name, order_index, is_enabled, is_parallel,
                        retry_attempts, timeout_seconds, execution_condition, input_source, output_target
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    workflow_id,
                    step['agent_role'],
                    step['step_name'],
                    step['order_index'],
                    step['is_enabled'],
                    step['is_parallel'],
                    step['retry_attempts'],
                    step['timeout_seconds'],
                    step['execution_condition'],
                    step['input_source'],
                    step['output_target']
                ))
        
        logger.info("Default workflows and workflow steps initialized")
    
    # ==================== WORKFLOW MANAGEMENT METHODS ====================
    
    def get_all_workflows(self):
        """Lädt alle Workflows aus der Datenbank"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT w.*, COUNT(ws.id) as step_count
                FROM workflows w
                LEFT JOIN workflow_steps ws ON w.id = ws.workflow_id
                GROUP BY w.id
                ORDER BY w.is_default DESC, w.name ASC
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def get_workflow_by_id(self, workflow_id):
        """Lädt einen Workflow anhand der ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM workflows WHERE id = ?', (workflow_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_workflow_steps(self, workflow_id):
        """Lädt alle Steps eines Workflows"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ws.*, a.name as agent_name 
                FROM workflow_steps ws
                LEFT JOIN assistants a ON ws.agent_role = a.role
                WHERE ws.workflow_id = ?
                ORDER BY ws.order_index ASC
            ''', (workflow_id,))
            return [dict(row) for row in cursor.fetchall()]

    def create_workflow(self, name, description="", workflow_type="sequential", is_active=True, is_default=False, trigger_conditions="{}", global_settings="{}"):
        """Erstellt einen neuen Workflow"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO workflows (name, description, workflow_type, is_active, is_default, trigger_conditions, global_settings, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, description, workflow_type, is_active, is_default, trigger_conditions, global_settings, 1))  # Mock admin user
            conn.commit()
            return cursor.lastrowid

    def create_workflow_step(self, workflow_id, step_data):
        """Erstellt einen neuen Workflow-Step"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO workflow_steps (
                    workflow_id, agent_role, step_name, order_index, is_enabled, is_parallel, parallel_group,
                    retry_attempts, timeout_seconds, error_handling, execution_condition, skip_condition,
                    loop_condition, max_loops, input_source, output_target
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                workflow_id,
                step_data.get('agent_role'),
                step_data.get('step_name'),
                step_data.get('order_index', 1),
                step_data.get('is_enabled', True),
                step_data.get('is_parallel', False),
                step_data.get('parallel_group', 0),
                step_data.get('retry_attempts', 3),
                step_data.get('timeout_seconds', 180),
                step_data.get('error_handling', 'graceful'),
                step_data.get('execution_condition'),
                step_data.get('skip_condition'),
                step_data.get('loop_condition'),
                step_data.get('max_loops', 1),
                step_data.get('input_source'),
                step_data.get('output_target')
            ))
            conn.commit()
            return cursor.lastrowid

    def update_workflow(self, workflow_id, data):
        """Aktualisiert einen bestehenden Workflow"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE workflows 
                SET name = ?, description = ?, workflow_type = ?, is_active = ?, is_default = ?, 
                    trigger_conditions = ?, global_settings = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                data.get('name'),
                data.get('description', ''),
                data.get('workflow_type', 'sequential'),
                data.get('is_active', True),
                data.get('is_default', False),
                data.get('trigger_conditions', '{}'),
                data.get('global_settings', '{}'),
                workflow_id
            ))
            conn.commit()
            return cursor.rowcount > 0

    def delete_workflow(self, workflow_id):
        """Löscht einen Workflow und alle zugehörigen Steps"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Steps werden automatisch durch CASCADE gelöscht
            cursor.execute('DELETE FROM workflows WHERE id = ?', (workflow_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_workflow_steps(self, workflow_id):
        """Löscht alle Steps eines Workflows"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM workflow_steps WHERE workflow_id = ?', (workflow_id,))
            conn.commit()
            return cursor.rowcount > 0

    def toggle_workflow_status(self, workflow_id):
        """Schaltet den Active-Status eines Workflows um"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE workflows 
                SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (workflow_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_default_workflow(self):
        """Lädt den Standard-Workflow"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM workflows WHERE is_default = 1 AND is_active = 1 LIMIT 1')
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_user_by_username(self, username):
        """Lädt User anhand des Usernamens"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            if user:
                return self._convert_user_timestamps(user)
        return None
    
    def get_user_by_id(self, user_id):
        """Lädt User anhand der ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            user = cursor.fetchone()
            if user:
                return self._convert_user_timestamps(user)
            return None
    
    def _convert_user_timestamps(self, user_row):
        """Konvertiert SQLite TIMESTAMP Strings zu datetime Objekten"""
        user_dict = dict(user_row)
        
        # last_login konvertieren falls vorhanden
        if user_dict['last_login']:
            try:
                user_dict['last_login'] = datetime.strptime(
                    user_dict['last_login'], '%Y-%m-%d %H:%M:%S'
                )
            except (ValueError, TypeError):
                user_dict['last_login'] = None
        
        # created_at konvertieren falls vorhanden  
        if user_dict['created_at']:
            try:
                user_dict['created_at'] = datetime.strptime(
                    user_dict['created_at'], '%Y-%m-%d %H:%M:%S'
                )
            except (ValueError, TypeError):
                user_dict['created_at'] = None
                
        return user_dict
    
    def update_last_login(self, user_id):
        """Aktualisiert den letzten Login-Zeitpunkt"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET last_login = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (user_id,))
            conn.commit()
    
    def create_project(self, user_id, title, description=""):
        """Erstellt ein neues Projekt"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO projects (user_id, title, description)
                VALUES (?, ?, ?)
            ''', (user_id, title, description))
            conn.commit()
            return cursor.lastrowid
    
    def get_user_projects(self, user_id):
        """Lädt alle Projekte eines Users"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM projects WHERE user_id = ?
                ORDER BY updated_at DESC
            ''', (user_id,))
            return cursor.fetchall()

    def get_all_assistants(self):
        """Lädt alle Assistants aus der Datenbank"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM assistants ORDER BY order_index ASC')
            return [dict(row) for row in cursor.fetchall()]

    def get_assistant_by_id(self, assistant_id):
        """Lädt einen Assistant anhand der ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM assistants WHERE id = ?', (assistant_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_assistant(self, name, assistant_id, role, description="", instructions="", model="gpt-4o", order_index=1, is_active=True,
                        # Advanced Behavior Parameters
                        temperature=0.7, top_p=1.0, max_tokens=2000, frequency_penalty=0.0, presence_penalty=0.0,
                        # Workflow Settings  
                        retry_attempts=3, timeout_seconds=180, error_handling="graceful",
                        # Performance Settings
                        response_limit=30, context_window=128000,
                        # Behavior Presets
                        behavior_preset="balanced", custom_system_message=None,
                        # Tool Configuration
                        enabled_tools=None):
        """Erstellt einen neuen Assistant mit erweiterten Behavior-Parametern"""
        if enabled_tools is None:
            enabled_tools = '["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]'
        elif isinstance(enabled_tools, list):
            enabled_tools = json.dumps(enabled_tools)
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO assistants (
                    name, assistant_id, role, description, instructions, model, order_index, is_active,
                    temperature, top_p, max_tokens, frequency_penalty, presence_penalty,
                    retry_attempts, timeout_seconds, error_handling,
                    response_limit, context_window, behavior_preset, custom_system_message, enabled_tools
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, assistant_id, role, description, instructions, model, order_index, is_active,
                  temperature, top_p, max_tokens, frequency_penalty, presence_penalty,
                  retry_attempts, timeout_seconds, error_handling,
                  response_limit, context_window, behavior_preset, custom_system_message, enabled_tools))
            conn.commit()
            return cursor.lastrowid

    def update_assistant(self, id, name, assistant_id_field, role, description="", instructions="", model="gpt-4o", order_index=1, is_active=True,
                        # Advanced Behavior Parameters
                        temperature=0.7, top_p=1.0, max_tokens=2000, frequency_penalty=0.0, presence_penalty=0.0,
                        # Workflow Settings  
                        retry_attempts=3, timeout_seconds=180, error_handling="graceful",
                        # Performance Settings
                        response_limit=30, context_window=128000,
                        # Behavior Presets
                        behavior_preset="balanced", custom_system_message=None,
                        # Tool Configuration
                        enabled_tools=None):
        """Aktualisiert einen bestehenden Assistant mit erweiterten Behavior-Parametern"""
        if enabled_tools is None:
            enabled_tools = '["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]'
        elif isinstance(enabled_tools, list):
            enabled_tools = json.dumps(enabled_tools)
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE assistants 
                SET name = ?, assistant_id = ?, role = ?, description = ?, instructions = ?, model = ?, order_index = ?, is_active = ?,
                    temperature = ?, top_p = ?, max_tokens = ?, frequency_penalty = ?, presence_penalty = ?,
                    retry_attempts = ?, timeout_seconds = ?, error_handling = ?,
                    response_limit = ?, context_window = ?, behavior_preset = ?, custom_system_message = ?, enabled_tools = ?
                WHERE id = ?
            ''', (name, assistant_id_field, role, description, instructions, model, order_index, is_active,
                  temperature, top_p, max_tokens, frequency_penalty, presence_penalty,
                  retry_attempts, timeout_seconds, error_handling,
                  response_limit, context_window, behavior_preset, custom_system_message, enabled_tools, id))
            conn.commit()
            return cursor.rowcount > 0

    def toggle_assistant_status(self, assistant_id):
        """Schaltet den Active-Status eines Assistants um"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE assistants 
                SET is_active = NOT is_active
                WHERE id = ?
            ''', (assistant_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_assistant(self, assistant_id):
        """Löscht einen Assistant"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM assistants WHERE id = ?', (assistant_id,))
            conn.commit()
            return cursor.rowcount > 0

    def create_chat_session(self, user_id, project_id=None, title=None):
        """Erstellt einen neuen Chat-Thread für einen User"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chat_sessions (user_id, project_id, title)
                VALUES (?, ?, ?)
            ''', (user_id, project_id, title))
            conn.commit()
            return cursor.lastrowid
    
    def get_user_chat_sessions(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM chat_sessions WHERE user_id = ? AND is_archived = 0
                ORDER BY updated_at DESC
            ''', (user_id,))
            return cursor.fetchall()
    
    def clean_old_chat_sessions(self, retention_days=14):
        """Löscht Chat-Sessions & Messages, die älter als retention_days sind"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM chat_messages WHERE session_id IN (
                    SELECT id FROM chat_sessions WHERE created_at < datetime('now', ?)
                )
            ''', (f'-{retention_days} days',))
            cursor.execute('''
                DELETE FROM chat_sessions WHERE created_at < datetime('now', ?)
            ''', (f'-{retention_days} days',))
            conn.commit()

# Database Manager initialisieren
db = DatabaseManager(app.config['DATABASE'])

# Session-Management Hilfsfunktionen
def login_required(f):
    """Decorator für Login-Pflicht"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator für Admin-Rechte"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user = db.get_user_by_id(session['user_id'])
        if not user or user['role'] != 'admin':
            flash('Admin-Rechte erforderlich', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    """Startseite - Direkter Zugang zum Chat (Authentication bypassed für MVP)"""
    return redirect(url_for('chat'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login-Seite"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = db.get_user_by_username(username)
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            # Letzten Login aktualisieren
            db.update_last_login(user['id'])
            
            flash(f'Willkommen, {user["username"]}!', 'success')
            logger.info(f"User {username} logged in successfully")
            
            return redirect(url_for('dashboard'))
        else:
            flash('Ungültige Anmeldedaten', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout und Session löschen"""
    username = session.get('username', 'Unknown')
    session.clear()
    flash('Erfolgreich abgemeldet', 'success')
    logger.info(f"User {username} logged out")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard - unterschiedlich je nach Rolle"""
    user = db.get_user_by_id(session['user_id'])
    projects = db.get_user_projects(session['user_id'])
    
    return render_template('dashboard.html', user=user, projects=projects)

@app.route('/admin')
@admin_required
def admin_panel():
    """Admin-Panel für Agenten- und System-Verwaltung"""
    return render_template('admin.html')

@app.route('/admin/assistants')
@admin_required  
def admin_assistants():
    """Assistant-Management Interface"""
    assistants = db.get_all_assistants()
    return render_template('admin_assistants.html', assistants=assistants)

@app.route('/admin/workflows')
@admin_required
def admin_workflows():
    """Workflow-Management Interface"""
    workflows = db.get_all_workflows()
    agents = db.get_all_assistants()
    return render_template('admin_workflows.html', workflows=workflows, agents=agents)

@app.route('/admin/workflows/help')
@admin_required
def admin_workflows_help():
    """Workflow-Management Hilfe und Anleitung"""
    return render_template('admin_workflows_help.html')

# ==================== WORKFLOW API ENDPOINTS ====================

@app.route('/api/assistants', methods=['GET', 'POST'])
@admin_required
def api_assistants():
    """API für Assistants (Liste abrufen, neuen erstellen)"""
    if request.method == 'GET':
        assistants = db.get_all_assistants()
        return jsonify(assistants)

    if request.method == 'POST':
        try:
            data = request.get_json()
            # Validierung (einfach)
            if not all(k in data for k in ['name', 'assistant_id', 'role']):
                return jsonify({'error': 'Fehlende erforderliche Felder'}), 400

            assistant_id = db.create_assistant(
                name=data['name'],
                assistant_id=data['assistant_id'], 
                role=data['role'],
                description=data.get('description', ''),
                instructions=data.get('instructions', ''),
                model=data.get('model', 'gpt-4o'),
                order_index=int(data.get('order_index', 99)),
                is_active=bool(data.get('is_active', True)),
                # Advanced Behavior Parameters
                temperature=float(data.get('temperature', 0.7)),
                top_p=float(data.get('top_p', 1.0)),
                max_tokens=int(data.get('max_tokens', 2000)),
                frequency_penalty=float(data.get('frequency_penalty', 0.0)),
                presence_penalty=float(data.get('presence_penalty', 0.0)),
                # Workflow Settings  
                retry_attempts=int(data.get('retry_attempts', 3)),
                timeout_seconds=int(data.get('timeout_seconds', 180)),
                error_handling=data.get('error_handling', 'graceful'),
                # Performance Settings
                response_limit=int(data.get('response_limit', 30)),
                context_window=int(data.get('context_window', 128000)),
                # Behavior Presets
                behavior_preset=data.get('behavior_preset', 'balanced'),
                custom_system_message=data.get('custom_system_message', None),
                # Tool Configuration
                enabled_tools=json.loads(data.get('enabled_tools', '["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]'))
            )
            new_assistant = db.get_assistant_by_id(assistant_id)
            return jsonify(new_assistant), 201

        except Exception as e:
            logger.error(f"Error creating assistant: {e}")
            return jsonify({'error': f'Interner Serverfehler: {str(e)}'}), 500

@app.route('/api/assistants/<int:assistant_id>', methods=['GET', 'PUT', 'DELETE'])
@admin_required
def api_assistant_detail(assistant_id):
    """API für einzelnen Assistant (abrufen, updaten, löschen)"""
    assistant = db.get_assistant_by_id(assistant_id)
    if not assistant:
        return jsonify({'error': 'Assistant nicht gefunden'}), 404

    if request.method == 'GET':
        return jsonify(assistant)

    if request.method == 'PUT':
        try:
            data = request.get_json()
            success = db.update_assistant(
                id=assistant_id,
                name=data.get('name', assistant['name']),
                assistant_id_field=data.get('assistant_id', assistant['assistant_id']),
                role=data.get('role', assistant['role']), 
                description=data.get('description', assistant['description']),
                instructions=data.get('instructions', assistant['instructions']),
                model=data.get('model', assistant['model']),
                order_index=int(data.get('order_index', assistant['order_index'])),
                is_active=bool(data.get('is_active', assistant['is_active'])),
                # Advanced Behavior Parameters
                temperature=float(data.get('temperature', assistant.get('temperature', 0.7))),
                top_p=float(data.get('top_p', assistant.get('top_p', 1.0))),
                max_tokens=int(data.get('max_tokens', assistant.get('max_tokens', 2000))),
                frequency_penalty=float(data.get('frequency_penalty', assistant.get('frequency_penalty', 0.0))),
                presence_penalty=float(data.get('presence_penalty', assistant.get('presence_penalty', 0.0))),
                # Workflow Settings  
                retry_attempts=int(data.get('retry_attempts', assistant.get('retry_attempts', 3))),
                timeout_seconds=int(data.get('timeout_seconds', assistant.get('timeout_seconds', 180))),
                error_handling=data.get('error_handling', assistant.get('error_handling', 'graceful')),
                # Performance Settings
                response_limit=int(data.get('response_limit', assistant.get('response_limit', 30))),
                context_window=int(data.get('context_window', assistant.get('context_window', 128000))),
                # Behavior Presets
                behavior_preset=data.get('behavior_preset', assistant.get('behavior_preset', 'balanced')),
                custom_system_message=data.get('custom_system_message', assistant.get('custom_system_message', None)),
                # Tool Configuration
                enabled_tools=data.get('enabled_tools', assistant.get('enabled_tools', '["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]'))
            )
            if success:
                updated_assistant = db.get_assistant_by_id(assistant_id)
                return jsonify(updated_assistant)
            return jsonify({'error': 'Update fehlgeschlagen'}), 500
        except Exception as e:
            logger.error(f"Error updating assistant {assistant_id}: {e}")
            return jsonify({'error': f'Interner Serverfehler: {str(e)}'}), 500

    if request.method == 'DELETE':
        try:
            success = db.delete_assistant(assistant_id)
            if success:
                return jsonify({'message': 'Assistant erfolgreich gelöscht'}), 200
            return jsonify({'error': 'Löschen fehlgeschlagen'}), 500
        except Exception as e:
            logger.error(f"Error deleting assistant {assistant_id}: {e}")
            return jsonify({'error': f'Interner Serverfehler: {str(e)}'}), 500

@app.route('/api/assistants/<int:assistant_id>/toggle', methods=['POST'])
@admin_required
def toggle_assistant(assistant_id):
    """Assistant aktivieren/deaktivieren"""
    try:
        success = db.toggle_assistant_status(assistant_id)
        if success:
            return jsonify({'message': 'Assistant-Status erfolgreich geändert'})
        return jsonify({'error': 'Assistant nicht gefunden'}), 404
    except Exception as e:
        logger.error(f"Error toggling assistant: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workflows', methods=['GET', 'POST'])
@admin_required
def api_workflows():
    """API für Workflows (Liste abrufen, neuen erstellen)"""
    if request.method == 'GET':
        workflows = db.get_all_workflows()
        return jsonify(workflows)

    if request.method == 'POST':
        try:
            data = request.get_json()
            if not all(k in data for k in ['name', 'description']):
                return jsonify({'error': 'Fehlende erforderliche Felder'}), 400

            workflow_id = db.create_workflow(
                name=data['name'],
                description=data.get('description', ''),
                workflow_type=data.get('workflow_type', 'sequential'),
                is_active=bool(data.get('is_active', True)),
                is_default=bool(data.get('is_default', False)),
                trigger_conditions=data.get('trigger_conditions', '{}'),
                global_settings=data.get('global_settings', '{}')
            )
            
            # Workflow-Steps hinzufügen falls vorhanden
            if 'steps' in data:
                for step in data['steps']:
                    db.create_workflow_step(workflow_id, step)
            
            new_workflow = db.get_workflow_by_id(workflow_id)
            return jsonify(new_workflow), 201

        except Exception as e:
            logger.error(f"Error creating workflow: {e}")
            return jsonify({'error': f'Interner Serverfehler: {str(e)}'}), 500

@app.route('/api/workflows/<int:workflow_id>', methods=['GET', 'PUT', 'DELETE'])
@admin_required
def api_workflow_detail(workflow_id):
    """API für einzelnen Workflow (abrufen, updaten, löschen)"""
    workflow = db.get_workflow_by_id(workflow_id)
    if not workflow:
        return jsonify({'error': 'Workflow nicht gefunden'}), 404

    if request.method == 'GET':
        # Workflow-Steps mit laden
        workflow['steps'] = db.get_workflow_steps(workflow_id)
        return jsonify(workflow)

    if request.method == 'PUT':
        try:
            data = request.get_json()
            success = db.update_workflow(workflow_id, data)
            
            # Steps aktualisieren falls vorhanden
            if 'steps' in data:
                db.delete_workflow_steps(workflow_id)
                for step in data['steps']:
                    db.create_workflow_step(workflow_id, step)
            
            if success:
                updated_workflow = db.get_workflow_by_id(workflow_id)
                updated_workflow['steps'] = db.get_workflow_steps(workflow_id)
                return jsonify(updated_workflow)
            return jsonify({'error': 'Update fehlgeschlagen'}), 500
            
        except Exception as e:
            logger.error(f"Error updating workflow {workflow_id}: {e}")
            return jsonify({'error': f'Interner Serverfehler: {str(e)}'}), 500

    if request.method == 'DELETE':
        try:
            success = db.delete_workflow(workflow_id)
            if success:
                return jsonify({'message': 'Workflow erfolgreich gelöscht'}), 200
            return jsonify({'error': 'Löschen fehlgeschlagen'}), 500
        except Exception as e:
            logger.error(f"Error deleting workflow {workflow_id}: {e}")
            return jsonify({'error': f'Interner Serverfehler: {str(e)}'}), 500

@app.route('/api/workflows/<int:workflow_id>/toggle', methods=['POST'])
@admin_required
def toggle_workflow(workflow_id):
    """Workflow aktivieren/deaktivieren"""
    try:
        success = db.toggle_workflow_status(workflow_id)
        if success:
            return jsonify({'message': 'Workflow-Status erfolgreich geändert'})
        return jsonify({'error': 'Workflow nicht gefunden'}), 404
    except Exception as e:
        logger.error(f"Error toggling workflow: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/chat')
def chat():
    """Chat-Interface für Kurserstellung (Authentication bypassed für MVP)"""
    project_id = request.args.get('project_id')
    session_id = request.args.get('session_id')
    
    # Mock user für MVP-Testing
    mock_user = {
        'id': 1,
        'username': 'mvp_demo_user',
        'role': 'admin'
    }
    
    if not session_id:
        # Erstelle neuen Chat-Thread
        session_id = db.create_chat_session(user_id=mock_user['id'], project_id=project_id, title='Neuer Chat')
    
    return render_template('chat.html', project_id=project_id, session_id=session_id, user=mock_user)

@app.route('/new-project', methods=['POST'])
@login_required
def new_project():
    """Neues Projekt erstellen"""
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    
    if not title:
        flash('Projekt-Titel ist erforderlich', 'error')
        return redirect(url_for('dashboard'))
    
    project_id = db.create_project(session['user_id'], title, description)
    flash(f'Projekt "{title}" erfolgreich erstellt', 'success')
    logger.info(f"New project created: {title} (ID: {project_id})")
    
    return redirect(url_for('chat', project_id=project_id))

@app.route('/upload-file', methods=['POST'])
def upload_file():
    """Datei-Upload für Wissensbasis"""
    try:
        project_id = request.form.get('project_id')
        if not project_id:
            return jsonify({'success': False, 'error': 'Projekt-ID erforderlich'}), 400
        
        # Validierung der project_id (numerisch oder demo format)
        if not (project_id.isdigit() or (project_id.startswith('demo_') and project_id[5:].isdigit())):
            return jsonify({'success': False, 'error': 'Ungültige Projekt-ID - muss numerisch oder Demo-Format sein'}), 400
        
        # MVP: Skip project permission check für Demo-Projekte
        # Echte Projekte würden hier validiert werden
        
        # File upload handling
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Keine Datei ausgewählt'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Keine Datei ausgewählt'})
        
        # Secure filename
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        
        # Save file to upload directory
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(upload_path)
        
        # Process with Knowledge Manager
        from knowledge_manager import get_knowledge_manager
        km = get_knowledge_manager()
        
        # Convert demo project_id to a format the knowledge manager can handle
        if project_id.startswith('demo_'):
            # Use the timestamp part as project_id for knowledge manager
            numeric_project_id = int(project_id[5:])
        else:
            numeric_project_id = int(project_id)
        
        result = km.process_uploaded_file(
            file_path=upload_path,
            project_id=numeric_project_id,
            user_id=1,  # Mock user_id für MVP
            filename=filename
        )
        
        if result['success']:
            logger.info(f"File processed successfully: {filename} for project {project_id}")
            return jsonify({
                'success': True,
                'message': f'Datei "{filename}" erfolgreich verarbeitet',
                'details': {
                    'filename': result['filename'],
                    'chunks_count': result['chunks_count'],
                    'preview': result['preview']
                }
            })
        else:
            logger.error(f"File processing failed: {result['error']}")
            return jsonify({'success': False, 'error': result['error']})
            
    except Exception as e:
        logger.error(f"File upload error: {e}")
        return jsonify({'success': False, 'error': f'Upload-Fehler: {str(e)}'})

@app.route('/knowledge-summary/<int:project_id>')
@login_required
def knowledge_summary(project_id):
    """API: Wissensbasis-Übersicht für ein Projekt"""
    try:
        # Prüfe Projekt-Berechtigung
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM projects 
                WHERE id = ? AND user_id = ?
            ''', (project_id, session['user_id']))
            project = cursor.fetchone()
            
            if not project:
                return jsonify({'error': 'Projekt nicht gefunden'}), 404
        
        from knowledge_manager import get_knowledge_manager
        km = get_knowledge_manager()
        summary = km.get_project_knowledge_summary(project_id)
        
        return jsonify(summary)
        
    except Exception as e:
        logger.error(f"Knowledge summary error: {e}")
        return jsonify({'error': str(e)}), 500

# SocketIO Events für Real-time Chat (Authentication bypassed für MVP)
@socketio.on('connect')
def handle_connect():
    """Client verbunden (MVP: Auth-Bypass)"""
    # MVP: Immer erlauben, Mock-User verwenden
    mock_user = {'username': 'mvp_demo_user', 'role': 'admin'}
    emit('status', {'msg': f'Verbunden als {mock_user["username"]} (MVP-Demo-Modus)'})
    logger.info(f"SocketIO connection: {mock_user['username']} (MVP Mode)")

@socketio.on('join_project')
def handle_join_project(data):
    """User tritt einem Chat-Thread bei (nun session-basiert)"""
    project_id = data.get('project_id')
    session_id = data.get('session_id')
    if not session_id:
        emit('error_message', {'error': 'session_id fehlt'})
        return

    join_room(f'session_{session_id}')
    emit('status', {'msg': f'Chat-Thread {session_id} beigetreten (MVP-Demo-Modus)'})
    
    # Chat-Historie laden und senden (MVP: vereinfacht)
    try:
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT cm.*, u.username 
                FROM chat_messages cm
                JOIN users u ON cm.user_id = u.id
                WHERE cm.session_id = ?
                ORDER BY cm.created_at ASC
                LIMIT 200
            ''', (session_id,))
            messages = cursor.fetchall()
            
            # Historie an Client senden
            for msg in messages:
                emit('new_message', {
                    'sender': 'KI-Assistant' if msg['message_type'] == 'assistant' else msg['username'],
                    'message': msg['content'],
                    'timestamp': msg['created_at'][-8:-3] if len(msg['created_at']) > 8 else '00:00',
                    'type': msg['message_type']
                })
                
            if messages:
                emit('status', {'msg': f'{len(messages)} Nachrichten geladen'})
                
    except Exception as e:
        logger.error(f"Error loading chat history: {e}")
    
    logger.info(f"MVP User joined session {session_id}")

@socketio.on('leave_project')
def handle_leave_project(data):
    """User verlässt Projekt-Chat"""
    session_id = data.get('session_id')
    if session_id:
        leave_room(f'session_{session_id}')
        logger.info(f"User left session {session_id}")

@socketio.on('user_message')
def handle_user_message(data):
    """User-Nachricht verarbeiten und an KI-Orchestrator weiterleiten (MVP: Auth-Bypass)"""
    message = data.get('message', '').strip()
    session_id = data.get('session_id')
    project_id = data.get('project_id')
    
    if not message:
        emit('error_message', {'error': 'Leere Nachricht'})
        return
    
    # MVP: Mock User-Daten
    mock_user = {'id': 1, 'username': 'mvp_demo_user'}
    
    # User-Nachricht in DB speichern (MVP: mit mock user_id)
    try:
        with sqlite3.connect(app.config['DATABASE']) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chat_messages (session_id, project_id, user_id, message_type, content)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, project_id, mock_user['id'], 'user', message))
            conn.commit()
    except Exception as e:
        logger.error(f"Database error saving message: {e}")
    
    # User-Nachricht an alle Teilnehmer senden
    emit('new_message', {
        'sender': mock_user['username'],
        'message': message,
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'type': 'user'
    }, room=f'session_{session_id}')
    
    # KI-Orchestrator initialisieren und Nachricht verarbeiten (MVP: Auth-Bypass)
    from chat_orchestrator import DynamicChatOrchestrator, active_orchestrators
    
    orchestrator_key = f"{mock_user['id']}_{session_id}"
    
    if orchestrator_key not in active_orchestrators:
        # Neuen Orchestrator für diesen User/Project erstellen
        orchestrator = DynamicChatOrchestrator(
            socketio, 
            project_id=project_id, 
            session_id=session_id, 
            db_path=app.config['DATABASE']
        )
        active_orchestrators[orchestrator_key] = orchestrator
        logger.info(f"New orchestrator created for MVP user {mock_user['id']}, session {session_id}")
    else:
        orchestrator = active_orchestrators[orchestrator_key]
    
    # MVP: Mock User-Daten für Kontext
    user_data = {
        'user_id': mock_user['id'],
        'username': mock_user['username'],
        'role': 'admin'
    }
    
    # Nachricht asynchron verarbeiten
    orchestrator.process_message(message, user_data)
    
    logger.info(f"Message from {mock_user['username']} processed by orchestrator: {message[:50]}...")

# Scheduler für automatische Löschung alter Chats
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()

RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', 14))

def _schedule_chat_cleanup():
    logger.info(f"Running chat cleanup job (retention {RETENTION_DAYS} days)...")
    db.clean_old_chat_sessions(retention_days=RETENTION_DAYS)

scheduler.add_job(_schedule_chat_cleanup, 'interval', days=1, next_run_time=datetime.now())
scheduler.start()

if __name__ == '__main__':
    logger.info("Starting Intelligentes KI-Kursstudio...")
    logger.info(f"Database: {app.config['DATABASE']}")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    
    # Development-Modus mit Debug
    socketio.run(app, debug=True, host='0.0.0.0', port=5000) 