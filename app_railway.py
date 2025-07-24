"""
Intelligentes KI-Kursstudio - Railway Production Version
Optimiert für PostgreSQL-Deployment mit SQLAlchemy
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from chat_orchestrator import DynamicChatOrchestrator
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from models import db, User, Project, Assistant, Workflow, WorkflowStep, ChatSession, ChatMessage

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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global orchestrator storage
orchestrators = {}

# Database initialization and default data
def init_database():
    """Initialize database with tables and default data"""
    with app.app_context():
        try:
            db.create_all()
            init_default_users()
            init_default_assistants()
            init_default_workflows()
            logger.info("Database initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
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
    workflows = db.session.query(
        Workflow,
        db.func.count(WorkflowStep.id).label('step_count')
    ).outerjoin(WorkflowStep).group_by(Workflow.id).all()
    
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
    
    logger.info(f"SocketIO connection: {username} (ID: {user_id})")
    emit('status', {'message': f'Connected as {username}'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    user_id = session.get('user_id')
    if user_id and user_id in orchestrators:
        del orchestrators[user_id]
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
    
    # Get or create orchestrator for this user
    if user_id not in orchestrators:
        orchestrators[user_id] = DynamicChatOrchestrator(
            socketio=socketio,
            session_id=user_id,
            db_path=app.config.get('SQLALCHEMY_DATABASE_URI', 'kursstudio.db')
        )
    
    # Process message
    orchestrator = orchestrators[user_id]
    orchestrator.process_message(message, user_id)

# Chat cleanup scheduler
scheduler = BackgroundScheduler()

def cleanup_chats():
    """Scheduled job to clean up old chats"""
    try:
        retention_days = int(os.environ.get('RETENTION_DAYS', 14))
        logger.info(f"Running chat cleanup job (retention {retention_days} days)...")
        
        with app.app_context():
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            
            # Find old sessions
            old_sessions = ChatSession.query.filter(ChatSession.updated_at < cutoff_date).all()
            
            for session in old_sessions:
                # Delete messages first
                ChatMessage.query.filter_by(session_id=session.id).delete()
                # Delete session
                db.session.delete(session)
            
            db.session.commit()
            
            deleted_count = len(old_sessions)
            logger.info(f"Chat cleanup completed: {deleted_count} sessions deleted")
    
    except Exception as e:
        logger.error(f"Chat cleanup job failed: {e}")

# Schedule cleanup job
scheduler.add_job(
    func=cleanup_chats,
    trigger=IntervalTrigger(days=1),
    id='chat_cleanup_job',
    name='Daily chat cleanup',
    replace_existing=True
)

# Initialize database immediately (wichtig für gunicorn/Railway)
init_database()

# Start scheduler
scheduler.start()
logger.info("Scheduler started")
logger.info("🔧 ROUTES LOADED: Including new_project route fix for Railway")

if __name__ == '__main__':
    # Get port from environment (Railway sets this)
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("Starting Intelligentes KI-Kursstudio (Railway Version)...")
    logger.info(f"Database: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
    logger.info("🚀 VERSION: 2025-01-24-v2 - NEW_PROJECT ROUTE INCLUDED")
    
    # Run the app
    socketio.run(app, host='0.0.0.0', port=port, debug=False) 