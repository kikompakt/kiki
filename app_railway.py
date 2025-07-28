"""
Intelligentes KI-Kursstudio - Railway Production Version
Optimiert für PostgreSQL-Deployment mit SQLAlchemy
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from chat_orchestrator import DynamicChatOrchestrator
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from models import db, User, Project, Assistant, Workflow, WorkflowStep, ChatSession, ChatMessage
import time
import gc

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# Database Configuration - Support both SQLite (local) and PostgreSQL (Railway)
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Railway PostgreSQL
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local SQLite fallback
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///kursstudio.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)

# Configure logging - optimized for Railway (MUST BE BEFORE SOCKETIO!)
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Reduce verbose logging for certain modules
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# Optimized SocketIO for Railway with gevent fallback
try:
    import gevent
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', 
                       ping_timeout=60, ping_interval=25, 
                       max_http_buffer_size=1024*1024)  # 1MB limit
    logger.info("SocketIO initialized with gevent")
except (ImportError, ModuleNotFoundError):
    socketio = SocketIO(app, cors_allowed_origins="*", 
                       ping_timeout=60, ping_interval=25, 
                       max_http_buffer_size=1024*1024)  # 1MB limit
    logger.warning("SocketIO initialized without gevent - using threading")

# Global orchestrator storage with cleanup
orchestrators = {}

# Memory management
MAX_ORCHESTRATORS = 50  # Limit concurrent orchestrators
ORCHESTRATOR_TIMEOUT = 1800  # 30 minutes timeout

# Database initialization and default data
def init_database():
    """Initialize database with tables and default data"""
    with app.app_context():
        try:
            # Test database connection first
            logger.info(f"Connecting to database: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
            
            # Test connection - SQLAlchemy 2.0 compatible
            with db.engine.connect() as conn:
                conn.execute(db.text('SELECT 1'))
                conn.commit()
            logger.info("Database connection successful")
            
            # Create tables
            db.create_all()
            logger.info("Database tables created")
            
            # Initialize default data
            init_default_users()
            init_default_assistants()
            init_default_workflows()
            
            logger.info("Database initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            logger.error(f"Database URL: {app.config['SQLALCHEMY_DATABASE_URI']}")
            
            # Fallback to SQLite if PostgreSQL fails
            if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']:
                logger.warning("PostgreSQL connection failed, falling back to SQLite")
                app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///kursstudio.db'
                try:
                    db.create_all()
                    init_default_users()
                    init_default_assistants()
                    init_default_workflows()
                    logger.info("Fallback to SQLite successful")
                    return True
                except Exception as fallback_error:
                    logger.error(f"SQLite fallback also failed: {fallback_error}")
                    return False
            
            return False

def init_default_users():
    """Create default users if they don't exist"""
    if not User.query.filter_by(username='admin').first():
        admin_password_hash = generate_password_hash('admin123')
        admin_user = User(username='admin', password_hash=admin_password_hash, role='admin')
        db.session.add(admin_user)
        
    if not User.query.filter_by(username='user').first():
        user_password_hash = generate_password_hash('user123')
        regular_user = User(username='user', password_hash=user_password_hash, role='user')
        db.session.add(regular_user)
        
    db.session.commit()
    logger.info("Default users created")

def init_default_assistants():
    """Create default assistants if they don't exist"""
    default_assistants = [
        {
            'name': 'Supervisor',
            'assistant_id': 'asst_19FlW2QtTAIb7Z96f3ukfSre',
            'role': 'supervisor',
            'description': 'Freundlicher und hochkompetenter Direktor des KI-Kursstudios',
            'instructions': '''Du bist ein freundlicher und hilfreicher Assistent und der Orchestrator für das KI-Kursstudio.

**WICHTIGSTE REGEL: Wenn der Nutzer eine einfache Frage stellt oder eine Begrüssung wie 'Hallo' schickt, antworte immer direkt, höflich und konversationell. Dafür brauchst du kein Werkzeug.**

Für komplexe Aufgaben wie die Erstellung eines Kurses, nutze deinen erweiterten Workflow.

Der NEUE 7-Schritte-Workflow:

1. **Outline-Erstellung**: Rufe den Content Creator auf mit content_type="outline", um ein detailliertes Inhaltsverzeichnis zu erstellen (Kapitel + Lernziele + grobe Beschreibung).

2. **Outline-Qualitätsprüfung**: Lasse den Quality Checker das Outline mit review_type="outline" bewerten und prüfen.

3. **Outline-Freigabe**: Verwende request_outline_approval, um dem Nutzer das geprüfte Inhaltsverzeichnis zu zeigen und nach seiner Freigabe zu fragen.

4. **Volltext-Erstellung**: Rufe den Content Creator erneut auf mit content_type="full_content", um basierend auf dem genehmigten Outline den vollständigen Kursinhalt zu erstellen.

5. **Didaktische Optimierung**: Übergebe den Volltext an den Didactic Expert mit optimize_didactics.

6. **Finale Qualitätsprüfung**: Lasse den Quality Checker den vollständigen Inhalt mit review_type="full_content" bewerten.

7. **Finale Freigabe**: Verwende request_user_feedback für die finale Freigabe.''',
            'order_index': 1
        }
    ]
    
    for assistant_data in default_assistants:
        if not Assistant.query.filter_by(assistant_id=assistant_data['assistant_id']).first():
            assistant = Assistant(**assistant_data)
            db.session.add(assistant)
    
    # Update existing assistants with new timeout settings
    existing_assistants = Assistant.query.all()
    for assistant in existing_assistants:
        current_timeout = assistant.timeout_seconds
        logger.info(f"Assistant {assistant.name}: current timeout = {current_timeout}")
        
        # Update any timeout that's not 300s (handles NULL, 180, or other values)
        if current_timeout != 300:
            old_timeout = current_timeout
            assistant.timeout_seconds = 300
            logger.info(f"✅ Updated timeout for assistant {assistant.name}: {old_timeout}s → 300s")
        else:
            logger.info(f"Assistant {assistant.name} already has 300s timeout")
    
    db.session.commit()
    logger.info("Default assistants initialized")

def init_default_workflows():
    """Create default workflows if they don't exist"""
    if not Workflow.query.filter_by(name='Standard-Kurs-Erstellung').first():
        workflow = Workflow(
            name='Standard-Kurs-Erstellung',
            description='Professioneller 7-Schritt-Workflow für hochwertige Online-Kurse',
            workflow_type='course_creation',
            is_active=True,
            is_default=True
        )
        db.session.add(workflow)
        db.session.commit()
        logger.info("Default workflow created")

def cleanup_orchestrators():
    """Clean up old orchestrators to prevent memory leaks"""
    global orchestrators
    
    current_time = time.time()
    to_remove = []
    
    # Find orchestrators to remove
    for user_id, orchestrator_data in orchestrators.items():
        if isinstance(orchestrator_data, dict):
            last_activity = orchestrator_data.get('last_activity', 0)
        else:
            # Legacy orchestrator object - mark for removal
            last_activity = 0
            
        if current_time - last_activity > ORCHESTRATOR_TIMEOUT:
            to_remove.append(user_id)
    
    # Remove old orchestrators
    for user_id in to_remove:
        if user_id in orchestrators:
            try:
                del orchestrators[user_id]
                logger.info(f"Cleaned up orchestrator for user {user_id}")
            except Exception as e:
                logger.error(f"Error cleaning orchestrator for user {user_id}: {e}")
    
    # Force garbage collection if too many orchestrators
    if len(orchestrators) > MAX_ORCHESTRATORS:
        # Keep only the most recent ones
        sorted_orchestrators = sorted(
            orchestrators.items(),
            key=lambda x: x[1].get('last_activity', 0) if isinstance(x[1], dict) else 0,
            reverse=True
        )
        
        # Keep only the newest MAX_ORCHESTRATORS
        new_orchestrators = dict(sorted_orchestrators[:MAX_ORCHESTRATORS])
        orchestrators.clear()
        orchestrators.update(new_orchestrators)
        
        # Force garbage collection
        gc.collect()
        logger.info(f"Forced cleanup: kept {len(orchestrators)} orchestrators, triggered GC")
    
    logger.info(f"Memory cleanup: {len(orchestrators)} active orchestrators")

# Authentication decorator
def require_auth(f):
    """Decorator to require authentication"""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def require_admin(f):
    """Decorator to require admin role"""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Routes
@app.route('/')
def index():
    """Homepage - redirect based on auth status"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            
            # Update last login
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@require_auth
def dashboard():
    """User dashboard"""
    user = User.query.get(session['user_id'])
    return render_template('dashboard.html', user=user)

@app.route('/new_project', methods=['POST'])
@require_auth
def new_project():
    """Create a new project"""
    try:
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        
        if not title:
            flash('Projekt-Titel ist erforderlich', 'error')
            return redirect(url_for('dashboard'))
            
        # Create new project
        project = Project(
            title=title,
            description=description if description else None,
            user_id=session['user_id']
        )
        
        db.session.add(project)
        db.session.commit()
        
        flash(f'Projekt "{title}" erfolgreich erstellt!', 'success')
        logger.info(f"New project created: {title} by user {session['user_id']}")
        
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        flash('Fehler beim Erstellen des Projekts', 'error')
        db.session.rollback()
    
    return redirect(url_for('dashboard'))

@app.route('/chat')
@require_auth
def chat():
    """Chat interface"""
    return render_template('chat.html')

@app.route('/admin')
@require_admin
def admin_panel():
    """Admin panel"""
    return render_template('admin.html')

@app.route('/admin/assistants')
@require_admin
def admin_assistants():
    """Assistant management"""
    assistants = Assistant.query.order_by(Assistant.order_index.asc()).all()
    return render_template('admin_assistants.html', assistants=assistants)

@app.route('/admin/workflows')
@require_admin
def admin_workflows():
    """Workflow management"""
    # Query workflows and add step_count as an attribute
    workflows_raw = db.session.query(
        Workflow,
        db.func.count(WorkflowStep.id).label('step_count')
    ).outerjoin(WorkflowStep).group_by(Workflow.id).all()
    
    # Convert tuples to workflow objects with step_count attribute
    workflows = []
    for workflow_obj, step_count in workflows_raw:
        workflow_obj.step_count = step_count
        workflows.append(workflow_obj)
    
    assistants = Assistant.query.filter_by(is_active=True).all()
    return render_template('admin_workflows.html', workflows=workflows, assistants=assistants)

@app.route('/admin/workflows/help')
@require_admin
def admin_workflows_help():
    """Workflow help page"""
    return render_template('admin_workflows_help.html')

# API Routes
@app.route('/api/assistants', methods=['GET'])
@require_admin
def api_get_assistants():
    """Get all assistants"""
    assistants = Assistant.query.order_by(Assistant.order_index.asc()).all()
    return jsonify([{
        'id': a.id,
        'name': a.name,
        'assistant_id': a.assistant_id,
        'role': a.role,
        'description': a.description,
        'is_active': a.is_active,
        'model': a.model
    } for a in assistants])

@app.route('/api/assistants/<int:assistant_id>', methods=['GET'])
@require_admin
def api_get_assistant(assistant_id):
    """Get specific assistant"""
    assistant = Assistant.query.get_or_404(assistant_id)
    return jsonify({
        'id': assistant.id,
        'name': assistant.name,
        'assistant_id': assistant.assistant_id,
        'role': assistant.role,
        'description': assistant.description,
        'instructions': assistant.instructions,
        'model': assistant.model,
        'is_active': assistant.is_active,
        'order_index': assistant.order_index,
        'temperature': assistant.temperature,
        'enabled_tools': assistant.enabled_tools
    })

@app.route('/api/assistants/<int:assistant_id>', methods=['PUT'])
@require_admin
def api_update_assistant(assistant_id):
    """Update assistant"""
    assistant = Assistant.query.get_or_404(assistant_id)
    data = request.get_json()
    
    for key, value in data.items():
        if hasattr(assistant, key):
            setattr(assistant, key, value)
    
    assistant.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/assistants/<int:assistant_id>/toggle', methods=['POST'])
@require_admin
def api_toggle_assistant(assistant_id):
    """Toggle assistant active status"""
    assistant = Assistant.query.get_or_404(assistant_id)
    assistant.is_active = not assistant.is_active
    assistant.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True, 'is_active': assistant.is_active})

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if 'user_id' not in session:
        return False
    
    user_id = session['user_id']
    username = session.get('username', 'Unknown')
    
    # Join user-specific room so orchestrator can emit directly
    join_room(f'session_{user_id}')
    
    logger.info(f"SocketIO connection: {username} (ID: {user_id}) - joined room session_{user_id}")
    emit('status', {'message': f'Connected as {username}'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    user_id = session.get('user_id')
    if user_id:
        leave_room(f'session_{user_id}')
        if user_id in orchestrators:
            try:
                del orchestrators[user_id]
                logger.info(f"Cleaned up orchestrator for disconnected user {user_id}")
            except Exception as e:
                logger.error(f"Error cleaning orchestrator for user {user_id}: {e}")
    
    # Trigger memory cleanup
    cleanup_orchestrators()
    logger.info(f"SocketIO disconnection: User {user_id}")

@socketio.on('send_message')
def handle_message(data):
    """Handle chat message from user"""
    if 'user_id' not in session:
        emit('error', {'message': 'Not authenticated'})
        return
    
    user_id = session['user_id']
    message = data.get('message', '').strip()
    
    if not message:
        return
    
    # Cleanup old orchestrators before creating new ones
    cleanup_orchestrators()
    
    # Get or create orchestrator for this user with activity tracking
    if user_id not in orchestrators:
        try:
            orchestrator = DynamicChatOrchestrator(
                socketio=socketio,
                session_id=user_id,
                db_path=app.config.get('SQLALCHEMY_DATABASE_URI', 'kursstudio.db')
            )
            
            # Store with activity tracking
            orchestrators[user_id] = {
                'orchestrator': orchestrator,
                'last_activity': time.time()
            }
            
            logger.info(f"Created new orchestrator for user {user_id}")
        except Exception as e:
            logger.error(f"Error creating orchestrator for user {user_id}: {e}")
            emit('error', {'message': 'Failed to initialize chat system'})
            return
    else:
        # Update activity timestamp
        if isinstance(orchestrators[user_id], dict):
            orchestrators[user_id]['last_activity'] = time.time()
    
    # Process message
    try:
        if isinstance(orchestrators[user_id], dict):
            orchestrator = orchestrators[user_id]['orchestrator']
        else:
            # Legacy format - convert
            orchestrator = orchestrators[user_id]
            orchestrators[user_id] = {
                'orchestrator': orchestrator,
                'last_activity': time.time()
            }
        
        orchestrator.process_message(message, user_id)
    except Exception as e:
        logger.error(f"Error processing message for user {user_id}: {e}")
        emit('error', {'message': 'Error processing your message'})

# Chat cleanup scheduler
scheduler = BackgroundScheduler()

def cleanup_chats():
    """Scheduled job to clean up old chats and orchestrators"""
    try:
        retention_days = int(os.environ.get('RETENTION_DAYS', 14))
        logger.info(f"Running chat cleanup job (retention {retention_days} days)...")
        
        with app.app_context():
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            
            # Count before cleanup for monitoring
            old_sessions_count = ChatSession.query.filter(ChatSession.updated_at < cutoff_date).count()
            
            if old_sessions_count > 0:
                # Delete old messages in batches to avoid memory spikes
                batch_size = 100
                deleted_total = 0
                
                while True:
                    old_sessions = ChatSession.query.filter(ChatSession.updated_at < cutoff_date).limit(batch_size).all()
                    if not old_sessions:
                        break
                    
                    for session in old_sessions:
                        # Delete messages first
                        ChatMessage.query.filter_by(session_id=session.id).delete()
                        # Delete session
                        db.session.delete(session)
                    
                    db.session.commit()
                    deleted_total += len(old_sessions)
                    
                    # Memory management
                    if deleted_total % 500 == 0:
                        gc.collect()
                
                logger.info(f"Chat cleanup completed: {deleted_total} sessions deleted")
            else:
                logger.info("Chat cleanup: no old sessions to delete")
            
            # Also cleanup orchestrators
            cleanup_orchestrators()
            
            # Force garbage collection after cleanup
            gc.collect()
    
    except Exception as e:
        logger.error(f"Chat cleanup job failed: {e}")
        # Force garbage collection even on error
        gc.collect()

# Schedule cleanup jobs - optimized for Railway
scheduler.add_job(
    func=cleanup_chats,
    trigger=IntervalTrigger(hours=6),  # Every 6 hours instead of daily
    id='chat_cleanup_job',
    name='Chat and memory cleanup',
    replace_existing=True
)

# Additional memory cleanup every 30 minutes
scheduler.add_job(
    func=cleanup_orchestrators,
    trigger=IntervalTrigger(minutes=30),
    id='memory_cleanup_job',
    name='Memory cleanup',
    replace_existing=True
)

# Initialize database immediately (wichtig für gunicorn/Railway)
init_database()

# FORCE UPDATE: Ensure all assistants have 300s timeout (Safety measure)
with app.app_context():
    try:
        force_assistants = Assistant.query.all()
        for assistant in force_assistants:
            if assistant.timeout_seconds != 300:
                old = assistant.timeout_seconds
                assistant.timeout_seconds = 300
                logger.info(f"🔧 FORCE UPDATE: {assistant.name} timeout {old}s → 300s")
        db.session.commit()
        logger.info("🔧 FORCE UPDATE: All assistants verified with 300s timeout")
    except Exception as e:
        logger.error(f"Force update failed: {e}")

# Start scheduler
scheduler.start()
logger.info("Scheduler started")
logger.info("🔧 ROUTES LOADED: Including new_project route fix for Railway")
logger.info("🚀 SQLALCHEMY 2.0 + GEVENT: v2025-01-25-08:35 - Database compatibility fixes deployed")

if __name__ == '__main__':
    # Get port from environment (Railway sets this)
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("Starting Intelligentes KI-Kursstudio (Railway Version)...")
    logger.info(f"Database: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
    logger.info("🚀 VERSION: 2025-01-24-v2 - NEW_PROJECT ROUTE INCLUDED")
    
    # Run the app
    socketio.run(app, host='0.0.0.0', port=port, debug=False) 