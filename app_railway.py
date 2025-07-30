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
from models import db, User, Project, Assistant, Workflow, WorkflowStep, ChatSession, ChatMessage, Course, CourseSection
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
    existing_workflow = Workflow.query.filter_by(name='Standard-Kurs-Erstellung').first()
    
    if not existing_workflow:
        # Create new workflow
        workflow = Workflow(
            name='Standard-Kurs-Erstellung',
            description='Professioneller 7-Schritt-Workflow für hochwertige Online-Kurse',
            workflow_type='sequential',  # Fixed: Use frontend-compatible type
            is_active=True,
            is_default=True
        )
        db.session.add(workflow)
        db.session.flush()  # Get the workflow ID
        logger.info("Creating new default workflow")
    else:
        # Update existing workflow if needed
        workflow = existing_workflow
        if workflow.workflow_type == 'course_creation':
            workflow.workflow_type = 'sequential'
            logger.info("Updated workflow type from course_creation to sequential")
        
        # FORCE RECREATION: Delete existing steps and recreate with correct steps
        existing_steps_count = WorkflowStep.query.filter_by(workflow_id=workflow.id).count()
        if existing_steps_count > 0:
            logger.info(f"FORCE UPDATE: Deleting {existing_steps_count} existing steps to recreate proper workflow")
            WorkflowStep.query.filter_by(workflow_id=workflow.id).delete()
        else:
            logger.info("No existing steps found, creating new ones")
    
    # Create default workflow steps (ALWAYS CREATE THESE)
    default_steps = [
        {
            'step_name': 'Outline-Erstellung',
            'agent_role': 'supervisor',
            'order_index': 1,
            'input_source': 'user_input',
            'output_target': 'raw_content'
        },
        {
            'step_name': 'Outline-Qualitätsprüfung', 
            'agent_role': 'supervisor',
            'order_index': 2,
            'input_source': 'raw_content',
            'output_target': 'optimized_content'
        },
        {
            'step_name': 'Volltext-Erstellung',
            'agent_role': 'supervisor', 
            'order_index': 3,
            'input_source': 'optimized_content',
            'output_target': 'raw_content'
        },
        {
            'step_name': 'Didaktische Optimierung',
            'agent_role': 'supervisor',
            'order_index': 4, 
            'input_source': 'raw_content',
            'output_target': 'optimized_content'
        },
        {
            'step_name': 'Finale Qualitätsprüfung',
            'agent_role': 'supervisor',
            'order_index': 5,
            'input_source': 'optimized_content', 
            'output_target': 'final_content'
        },
        {
            'step_name': 'Finale Freigabe',
            'agent_role': 'supervisor',
            'order_index': 6,
            'input_source': 'final_content',
            'output_target': 'approved_content'
        }
    ]
    
    logger.info(f"Creating {len(default_steps)} workflow steps")
    
    for i, step_data in enumerate(default_steps):
        step = WorkflowStep(
            workflow_id=workflow.id,
            step_name=step_data['step_name'],
            agent_role=step_data['agent_role'],
            order_index=step_data['order_index'],
            is_enabled=True,
            is_parallel=False,
            retry_attempts=3,
            timeout_seconds=300,  # Use the corrected timeout
            execution_condition=None,
            input_source=step_data['input_source'],
            output_target=step_data['output_target']
        )
        db.session.add(step)
        logger.info(f"Added step {i+1}: {step_data['step_name']}")
    
    db.session.commit()
    
    # Verify creation
    final_steps_count = WorkflowStep.query.filter_by(workflow_id=workflow.id).count()
    logger.info(f"✅ WORKFLOW STEPS VERIFICATION: {final_steps_count} steps created successfully")

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
    try:
        # Simplified query - get workflows first, then count steps separately
        workflows = Workflow.query.all()
        
        # Add step_count attribute to each workflow
        for workflow in workflows:
            step_count = WorkflowStep.query.filter_by(workflow_id=workflow.id).count()
            workflow.step_count = step_count
        
        assistants = Assistant.query.filter_by(is_active=True).all()
        
        logger.info(f"Loaded {len(workflows)} workflows and {len(assistants)} assistants for admin")
        
        return render_template('admin_workflows.html', workflows=workflows, assistants=assistants)
        
    except Exception as e:
        logger.error(f"Error loading workflows: {e}")
        # Return empty data to prevent template errors
        return render_template('admin_workflows.html', workflows=[], assistants=[])

@app.route('/admin/workflows/help')
@require_admin
def admin_workflows_help():
    """Admin workflow help page"""
    return render_template('admin_workflows_help.html')

@app.route('/courses')
def courses():
    """Display user's saved courses"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user_id = session.get('user_id')
        courses = Course.query.filter_by(user_id=user_id).order_by(Course.created_at.desc()).all()
        
        # Add section counts to courses
        for course in courses:
            course.sections_count = CourseSection.query.filter_by(course_id=course.id).count()
        
        return render_template('courses.html', courses=courses)
    except Exception as e:
        logger.error(f"Error loading courses page: {e}")
        return redirect(url_for('dashboard'))

@app.route('/courses/<int:course_id>')
def view_course(course_id):
    """Display a specific course"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user_id = session.get('user_id')
        course = Course.query.filter_by(id=course_id, user_id=user_id).first()
        
        if not course:
            flash('Kurs nicht gefunden.', 'error')
            return redirect(url_for('courses'))
        
        # Get course sections
        sections = CourseSection.query.filter_by(course_id=course.id).order_by(CourseSection.section_order).all()
        
        return render_template('course_view.html', course=course, sections=sections)
    except Exception as e:
        logger.error(f"Error loading course {course_id}: {e}")
        return redirect(url_for('courses'))

# Workflow API Routes
@app.route('/api/workflows', methods=['GET'])
@require_admin
def api_get_workflows():
    """Get all workflows"""
    workflows = Workflow.query.all()
    workflow_list = []
    
    for workflow in workflows:
        steps = WorkflowStep.query.filter_by(workflow_id=workflow.id).order_by(WorkflowStep.order_index).all()
        workflow_data = {
            'id': workflow.id,
            'name': workflow.name,
            'description': workflow.description,
            'workflow_type': workflow.workflow_type,
            'is_active': workflow.is_active,
            'is_default': workflow.is_default,
            'created_at': workflow.created_at.isoformat() if workflow.created_at else None,
            'steps': [{
                'id': step.id,
                'step_name': step.step_name,
                'agent_role': step.agent_role,
                'order_index': step.order_index,
                'is_enabled': step.is_enabled,
                'is_parallel': step.is_parallel,
                'retry_attempts': step.retry_attempts,
                'timeout_seconds': step.timeout_seconds,
                'execution_condition': step.execution_condition,
                'input_source': step.input_source,
                'output_target': step.output_target
            } for step in steps]
        }
        workflow_list.append(workflow_data)
    
    return jsonify(workflow_list)

@app.route('/api/workflows/<int:workflow_id>', methods=['GET'])
@require_admin
def api_get_workflow(workflow_id):
    """Get specific workflow"""
    workflow = Workflow.query.get_or_404(workflow_id)
    steps = WorkflowStep.query.filter_by(workflow_id=workflow.id).order_by(WorkflowStep.order_index).all()
    
    workflow_data = {
        'id': workflow.id,
        'name': workflow.name,
        'description': workflow.description,
        'workflow_type': workflow.workflow_type,
        'is_active': workflow.is_active,
        'is_default': workflow.is_default,
        'steps': [{
            'step_name': step.step_name,
            'agent_role': step.agent_role,
            'order_index': step.order_index,
            'is_enabled': step.is_enabled,
            'is_parallel': step.is_parallel,
            'retry_attempts': step.retry_attempts,
            'timeout_seconds': step.timeout_seconds,
            'execution_condition': step.execution_condition,
            'input_source': step.input_source,
            'output_target': step.output_target
        } for step in steps]
    }
    
    return jsonify(workflow_data)

@app.route('/api/workflows', methods=['POST'])
@require_admin  
def api_create_workflow():
    """Create new workflow"""
    try:
        data = request.get_json()
        
        # Create workflow
        workflow = Workflow(
            name=data['name'],
            description=data.get('description'),
            workflow_type=data.get('workflow_type', 'sequential'),
            is_active=data.get('is_active', True),
            is_default=data.get('is_default', False),
            created_by=session.get('user_id')
        )
        
        db.session.add(workflow)
        db.session.flush()  # Get the ID
        
        # Add steps
        for step_data in data.get('steps', []):
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_name=step_data['step_name'],
                agent_role=step_data['agent_role'],
                order_index=step_data['order_index'],
                is_enabled=step_data.get('is_enabled', True),
                is_parallel=step_data.get('is_parallel', False),
                retry_attempts=step_data.get('retry_attempts', 3),
                timeout_seconds=step_data.get('timeout_seconds', 180),
                execution_condition=step_data.get('execution_condition'),
                input_source=step_data.get('input_source'),
                output_target=step_data.get('output_target')
            )
            db.session.add(step)
        
        db.session.commit()
        logger.info(f"Created workflow: {workflow.name} by user {session.get('user_id')}")
        
        return jsonify({'success': True, 'id': workflow.id})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating workflow: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/workflows/<int:workflow_id>', methods=['PUT'])
@require_admin
def api_update_workflow(workflow_id):
    """Update workflow"""
    try:
        workflow = Workflow.query.get_or_404(workflow_id)
        data = request.get_json()
        
        # Update workflow fields
        workflow.name = data['name']
        workflow.description = data.get('description')
        workflow.workflow_type = data.get('workflow_type', 'sequential')
        workflow.is_active = data.get('is_active', True)
        workflow.is_default = data.get('is_default', False)
        workflow.updated_at = datetime.utcnow()
        
        # Delete existing steps
        WorkflowStep.query.filter_by(workflow_id=workflow.id).delete()
        
        # Add new steps
        for step_data in data.get('steps', []):
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_name=step_data['step_name'],
                agent_role=step_data['agent_role'],
                order_index=step_data['order_index'],
                is_enabled=step_data.get('is_enabled', True),
                is_parallel=step_data.get('is_parallel', False),
                retry_attempts=step_data.get('retry_attempts', 3),
                timeout_seconds=step_data.get('timeout_seconds', 180),
                execution_condition=step_data.get('execution_condition'),
                input_source=step_data.get('input_source'),
                output_target=step_data.get('output_target')
            )
            db.session.add(step)
        
        db.session.commit()
        logger.info(f"Updated workflow: {workflow.name}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating workflow: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/workflows/<int:workflow_id>', methods=['DELETE'])
@require_admin
def api_delete_workflow(workflow_id):
    """Delete workflow"""
    try:
        workflow = Workflow.query.get_or_404(workflow_id)
        
        # Don't allow deleting default workflows
        if workflow.is_default:
            return jsonify({'error': 'Standard-Workflows können nicht gelöscht werden'}), 400
        
        # Delete steps first
        WorkflowStep.query.filter_by(workflow_id=workflow.id).delete()
        
        # Delete workflow
        db.session.delete(workflow)
        db.session.commit()
        
        logger.info(f"Deleted workflow: {workflow.name}")
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting workflow: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/workflows/<int:workflow_id>/toggle', methods=['POST'])
@require_admin
def api_toggle_workflow(workflow_id):
    """Toggle workflow active status"""
    try:
        workflow = Workflow.query.get_or_404(workflow_id)
        workflow.is_active = not workflow.is_active
        workflow.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        status = "aktiviert" if workflow.is_active else "deaktiviert"
        logger.info(f"Workflow {workflow.name} {status}")
        
        return jsonify({'success': True, 'is_active': workflow.is_active})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error toggling workflow: {e}")
        return jsonify({'error': str(e)}), 400

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

# The new code block for creating assistants via POST
@app.route('/api/assistants', methods=['POST'])
@require_admin
def api_create_assistant():
    """Create a new assistant"""
    try:
        data = request.get_json()

        # Basic validation - role is now optional for flexible workflow system
        required_fields = ['name', 'assistant_id']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'Feld "{field}" fehlt'}), 400

        # Parse enabled_tools (can be list or JSON string)
        enabled_tools = data.get('enabled_tools', '[]')
        if isinstance(enabled_tools, str):
            try:
                enabled_tools_parsed = json.loads(enabled_tools)
            except Exception:
                enabled_tools_parsed = []
        else:
            enabled_tools_parsed = enabled_tools

        assistant = Assistant(
            name=data['name'],
            assistant_id=data['assistant_id'],
            role=data.get('role'),  # Optional for flexible workflow system
            description=data.get('description', ''),
            instructions=data.get('instructions', ''),
            model=data.get('model', 'gpt-4o'),
            order_index=int(data.get('order_index', 99)),
            is_active=bool(data.get('is_active', True)),
            assistant_type=data.get('assistant_type', 'custom'),  # New field
            temperature=float(data.get('temperature', 0.7)),
            top_p=float(data.get('top_p', 1.0)),
            max_tokens=int(data.get('max_tokens', 2000)),
            frequency_penalty=float(data.get('frequency_penalty', 0.0)),
            presence_penalty=float(data.get('presence_penalty', 0.0)),
            retry_attempts=int(data.get('retry_attempts', 3)),
            timeout_seconds=int(data.get('timeout_seconds', 180)),
            error_handling=data.get('error_handling', 'graceful'),
            response_limit=int(data.get('response_limit', 30)),
            context_window=int(data.get('context_window', 128000)),
            behavior_preset=data.get('behavior_preset', 'balanced'),
            custom_system_message=data.get('custom_system_message'),
            enabled_tools=json.dumps(enabled_tools_parsed)
        )
        db.session.add(assistant)
        db.session.commit()

        logger.info(f"New assistant created: {assistant.name} ({assistant.role})")
        return jsonify({'id': assistant.id, 'success': True}), 201
    except Exception as e:
        logger.error(f"Error creating assistant: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Workflow Management API Endpoints

@app.route('/api/workflows', methods=['GET', 'POST'])
@require_admin
def api_workflows():
    """Get all workflows or create new workflow"""
    if request.method == 'GET':
        workflows = Workflow.query.all()
        return jsonify([{
            'id': w.id,
            'name': w.name,
            'description': w.description,
            'workflow_type': w.workflow_type,
            'is_active': w.is_active,
            'is_default': w.is_default,
            'created_at': w.created_at.isoformat() if w.created_at else None
        } for w in workflows])
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            workflow = Workflow(
                name=data['name'],
                description=data.get('description', ''),
                workflow_type=data.get('workflow_type', 'course_creation'),
                is_active=data.get('is_active', True),
                is_default=data.get('is_default', False),
                created_by=session.get('user_id')
            )
            db.session.add(workflow)
            db.session.commit()
            
            return jsonify({'id': workflow.id, 'success': True}), 201
        except Exception as e:
            logger.error(f"Error creating workflow: {e}")
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

@app.route('/api/workflows/<int:workflow_id>/steps', methods=['GET', 'POST'])
@require_admin
def api_workflow_steps(workflow_id):
    """Get workflow steps or add new step"""
    if request.method == 'GET':
        steps = WorkflowStep.query.filter_by(workflow_id=workflow_id).order_by(WorkflowStep.order_index).all()
        return jsonify([{
            'id': s.id,
            'workflow_id': s.workflow_id,
            'assistant_id': s.assistant_id,
            'assistant_name': s.assistant.name if s.assistant else None,
            'agent_role': s.agent_role,  # Legacy support
            'step_name': s.step_name,
            'order_index': s.order_index,
            'is_enabled': s.is_enabled,
            'custom_prompt': s.custom_prompt,
            'step_type': s.step_type
        } for s in steps])
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            step = WorkflowStep(
                workflow_id=workflow_id,
                assistant_id=data['assistant_id'],
                step_name=data['step_name'],
                order_index=data['order_index'],
                is_enabled=data.get('is_enabled', True),
                custom_prompt=data.get('custom_prompt', ''),
                step_type=data.get('step_type', 'assistant_call')
            )
            db.session.add(step)
            db.session.commit()
            
            return jsonify({'id': step.id, 'success': True}), 201
        except Exception as e:
            logger.error(f"Error creating workflow step: {e}")
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

@app.route('/api/workflows/<int:workflow_id>/steps/<int:step_id>', methods=['PUT', 'DELETE'])
@require_admin
def api_workflow_step_detail(workflow_id, step_id):
    """Update or delete workflow step"""
    step = WorkflowStep.query.filter_by(id=step_id, workflow_id=workflow_id).first_or_404()
    
    if request.method == 'PUT':
        try:
            data = request.get_json()
            for key, value in data.items():
                if hasattr(step, key):
                    setattr(step, key, value)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Error updating workflow step: {e}")
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    if request.method == 'DELETE':
        try:
            db.session.delete(step)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Error deleting workflow step: {e}")
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

# Course Management API Endpoints

@app.route('/api/courses', methods=['GET'])
def api_get_courses():
    """Get all courses for the current user"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        
        courses = Course.query.filter_by(user_id=user_id).order_by(Course.created_at.desc()).all()
        
        course_list = []
        for course in courses:
            # Get sections count
            sections_count = CourseSection.query.filter_by(course_id=course.id).count()
            
            course_data = {
                'id': course.id,
                'title': course.title,
                'description': course.description,
                'course_topic': course.course_topic,
                'target_audience': course.target_audience,
                'estimated_duration': course.estimated_duration,
                'status': course.status,
                'quality_score': course.quality_score,
                'content_length': course.content_length,
                'sections_count': sections_count,
                'created_at': course.created_at.isoformat() if course.created_at else None,
                'updated_at': course.updated_at.isoformat() if course.updated_at else None
            }
            course_list.append(course_data)
        
        return jsonify(course_list)
        
    except Exception as e:
        logger.error(f"Error fetching courses: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/courses/<int:course_id>', methods=['GET'])
def api_get_course(course_id):
    """Get a specific course with full content"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        
        course = Course.query.filter_by(id=course_id, user_id=user_id).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
        
        # Get course sections
        sections = CourseSection.query.filter_by(course_id=course.id).order_by(CourseSection.section_order).all()
        
        course_data = {
            'id': course.id,
            'title': course.title,
            'description': course.description,
            'course_topic': course.course_topic,
            'target_audience': course.target_audience,
            'estimated_duration': course.estimated_duration,
            'full_content': course.full_content,
            'outline': course.outline,
            'learning_objectives': course.learning_objectives,
            'status': course.status,
            'quality_score': course.quality_score,
            'content_length': course.content_length,
            'created_at': course.created_at.isoformat() if course.created_at else None,
            'updated_at': course.updated_at.isoformat() if course.updated_at else None,
            'sections': [{
                'id': section.id,
                'title': section.section_title,
                'content': section.section_content,
                'order': section.section_order,
                'type': section.section_type,
                'learning_objectives': section.learning_objectives,
                'estimated_duration': section.estimated_duration
            } for section in sections]
        }
        
        return jsonify(course_data)
        
    except Exception as e:
        logger.error(f"Error fetching course {course_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/courses/<int:course_id>', methods=['PUT'])
def api_update_course(course_id):
    """Update course details"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        
        course = Course.query.filter_by(id=course_id, user_id=user_id).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
        
        data = request.get_json()
        
        # Update allowed fields
        if 'title' in data:
            course.title = data['title']
        if 'description' in data:
            course.description = data['description']
        if 'status' in data:
            course.status = data['status']
        if 'target_audience' in data:
            course.target_audience = data['target_audience']
        if 'estimated_duration' in data:
            course.estimated_duration = data['estimated_duration']
        
        db.session.commit()
        logger.info(f"Updated course {course_id}: {course.title}")
        
        return jsonify({'success': True, 'message': 'Course updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating course {course_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/courses/<int:course_id>', methods=['DELETE'])
def api_delete_course(course_id):
    """Delete a course"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        
        course = Course.query.filter_by(id=course_id, user_id=user_id).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
        
        # Delete course sections first
        CourseSection.query.filter_by(course_id=course.id).delete()
        
        # Delete course
        db.session.delete(course)
        db.session.commit()
        
        logger.info(f"Deleted course {course_id}: {course.title}")
        
        return jsonify({'success': True, 'message': 'Course deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting course {course_id}: {e}")
        return jsonify({'error': str(e)}), 500

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if 'user_id' not in session:
        logger.warning("SocketIO connect denied - no user_id in session")
        return False
    
    user_id = session['user_id']
    username = session.get('username', 'Unknown')
    
    try:
        # Join user-specific room so orchestrator can emit directly
        join_room(f'session_{user_id}')
        
        logger.info(f"SocketIO connection: {username} (ID: {user_id}) - joined room session_{user_id}")
        emit('status', {'message': f'Connected as {username}'})
        
        # Emit connection success to frontend
        emit('connection_status', {'connected': True, 'user_id': user_id, 'username': username})
        
    except Exception as e:
        logger.error(f"Error in SocketIO connect for user {user_id}: {e}")
        return False

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    user_id = session.get('user_id')
    username = session.get('username', 'Unknown')
    
    if user_id:
        try:
            leave_room(f'session_{user_id}')
            logger.info(f"SocketIO disconnection: {username} (ID: {user_id}) - left room session_{user_id}")
            
            if user_id in orchestrators:
                try:
                    del orchestrators[user_id]
                    logger.info(f"Cleaned up orchestrator for disconnected user {user_id}")
                except Exception as e:
                    logger.error(f"Error cleaning orchestrator for user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error in SocketIO disconnect for user {user_id}: {e}")
    else:
        logger.warning("SocketIO disconnect - no user_id in session")

# COMPATIBILITY: Support both event names from frontend
@socketio.on('user_message')
def handle_user_message_compat(data):
    """Handle user_message event (compatibility with app.py frontend)"""
    logger.info("📨 RECEIVED user_message event (compatibility mode)")
    return handle_message(data)

@socketio.on('send_message')
def handle_message(data):
    """Handle chat message from user"""
    logger.info(f"📨 RECEIVE MESSAGE EVENT: {data}")
    
    if 'user_id' not in session:
        logger.warning("❌ MESSAGE REJECTED: No user_id in session")
        emit('error', {'message': 'Not authenticated'})
        return
    
    user_id = session['user_id']
    message = data.get('message', '').strip()
    
    logger.info(f"📨 Processing message from user {user_id}: '{message}'")
    
    if not message:
        logger.warning(f"❌ Empty message from user {user_id}")
        return
    
    # CRITICAL FIX: Ensure Flask app context for SQLAlchemy
    with app.app_context():
        # Cleanup old orchestrators before creating new ones
        cleanup_orchestrators()
        
        # Get or create orchestrator for this user with activity tracking
        if user_id not in orchestrators:
            try:
                logger.info(f"🤖 Creating new orchestrator for user {user_id}")
                orchestrator = DynamicChatOrchestrator(
                    socketio=socketio,
                    session_id=user_id
                )
                
                # Store with activity tracking
                orchestrators[user_id] = {
                    'orchestrator': orchestrator,
                    'last_activity': time.time()
                }
                
                logger.info(f"✅ Created new orchestrator for user {user_id}")
            except Exception as e:
                logger.error(f"❌ Error creating orchestrator for user {user_id}: {e}")
                emit('error', {'message': 'Failed to initialize chat system'})
                return
        else:
            logger.info(f"🔄 Using existing orchestrator for user {user_id}")
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
            
            # CRITICAL FIX: Echo user message to frontend so it appears in chat
            username = session.get('username', f'User {user_id}')
            logger.info(f"📤 Echoing user message to frontend: '{message}' from {username}")
            
            emit('new_message', {
                'sender': username,
                'message': message,
                'timestamp': datetime.utcnow().strftime('%H:%M:%S'),
                'type': 'user'
            }, room=f'session_{user_id}')
            
            logger.info(f"🚀 Starting message processing for user {user_id}")
            orchestrator.process_message(message, user_id)
            logger.info(f"✅ Message processing initiated for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error processing message for user {user_id}: {e}")
            logger.error(f"❌ Exception details: {type(e).__name__}: {str(e)}")
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

# CREATE SPECIALIZED ASSISTANTS: Add missing assistant roles
def create_specialized_assistants():
    """Create specialized assistants if they don't exist"""
    try:
        with app.app_context():
            # Check if specialized assistants exist
            existing_roles = set(a.role for a in Assistant.query.all())
            
            specialized_assistants = [
                {
                    'name': 'Content Creator',
                    'assistant_id': 'asst_content_creator_v1',
                    'role': 'content_creator',
                    'description': 'Spezialist für die Erstellung von strukturierten Lerninhalten',
                    'instructions': '''Du bist ein Experte für die Erstellung von hochwertigen Lerninhalten.

DEINE AUFGABE: Erstelle strukturierte, professionelle Kursinhalte basierend auf dem gegebenen Thema.

STRUKTUR DEINER KURSE:
1. Klare Lernziele (3-5 pro Kapitel)
2. Logischer Aufbau (Einführung → Hauptinhalt → Beispiele → Zusammenfassung)
3. Praktische Beispiele und Analogien
4. Verständliche Sprache (max. 20 Wörter pro Satz)
5. Strukturierte Gliederung mit Überschriften

QUALITÄTSKRITERIEN:
- Faktisch korrekt und aktuell
- Zielgruppengerecht formuliert
- Interaktive Elemente einbauen
- Praxisbezug herstellen
- Konsistente Terminologie verwenden

Erstelle immer vollständige, sofort einsetzbare Kursinhalte!''',
                    'model': 'gpt-4o',
                    'temperature': 0.3,
                    'max_tokens': 3000,
                    'order_index': 2
                },
                {
                    'name': 'Didactic Expert',
                    'assistant_id': 'asst_didactic_expert_v1',
                    'role': 'didactic_expert',
                    'description': 'Spezialist für didaktische Optimierung von Lerninhalten',
                    'instructions': '''Du bist ein Didaktik-Experte für die Optimierung von Lerninhalten.

DEINE AUFGABE: Optimiere vorhandene Kursinhalte didaktisch und methodisch.

OPTIMIERUNGSBEREICHE:
1. LERNZIELE: Messbare, klare Ziele formulieren (SMART-Kriterien)
2. PROGRESSION: Logische Lernpfade mit ansteigendem Schwierigkeitsgrad
3. INTERAKTION: Fragen, Übungen, Reflexionspunkte einbauen
4. VERSTÄNDLICHKEIT: Komplexe Konzepte vereinfachen
5. MOTIVATION: Relevanz und Nutzen klar kommunizieren

DIDAKTISCHE METHODEN:
- Advance Organizer einsetzen
- Chunking für bessere Merkfähigkeit
- Beispiele vor Regeln präsentieren
- Wiederholung in verschiedenen Kontexten
- Aktives Lernen fördern

AUSGABE: Der vollständig optimierte Kursinhalt (nicht nur Verbesserungsvorschläge)!''',
                    'model': 'gpt-4o',
                    'temperature': 0.4,
                    'max_tokens': 3000,
                    'order_index': 3
                },
                {
                    'name': 'Quality Checker',
                    'assistant_id': 'asst_quality_checker_v1',
                    'role': 'quality_checker',
                    'description': 'Spezialist für Qualitätskontrolle und finale Prüfung',
                    'instructions': '''Du bist ein Qualitäts-Experte für die finale Prüfung von Kursinhalten.

DEINE AUFGABE: Führe eine kritische Qualitätsprüfung durch und korrigiere Mängel.

PRÜFKRITERIEN:
1. STRUKTUR: Logischer Aufbau, klare Gliederung, vollständige Kapitel
2. INHALT: Faktische Korrektheit, Aktualität, Praxisbezug
3. SPRACHE: Verständlichkeit, Konsistenz, angemessener Ton
4. DIDAKTIK: Lernziele messbar, Progression erkennbar, Beispiele vorhanden
5. VOLLSTÄNDIGKEIT: Alle Aspekte des Themas abgedeckt

QUALITÄTS-STANDARDS:
- Mindestens 3 Lernziele pro Hauptkapitel
- Praktische Beispiele in jedem Abschnitt
- Klare Zusammenfassungen
- Einheitliche Terminologie
- Logische Kapitelübergänge

AUSGABE: Der vollständig korrigierte und qualitätsgesicherte Kurs!''',
                    'model': 'gpt-4o',
                    'temperature': 0.2,
                    'max_tokens': 3000,
                    'order_index': 4
                }
            ]
            
            created_count = 0
            for assistant_data in specialized_assistants:
                if assistant_data['role'] not in existing_roles:
                    assistant = Assistant(
                        name=assistant_data['name'],
                        assistant_id=assistant_data['assistant_id'],
                        role=assistant_data['role'],
                        description=assistant_data['description'],
                        instructions=assistant_data['instructions'],
                        model=assistant_data['model'],
                        temperature=assistant_data['temperature'],
                        max_tokens=assistant_data['max_tokens'],
                        order_index=assistant_data['order_index'],
                        is_active=True,
                        enabled_tools='[]'  # No tools needed for specialized assistants
                    )
                    db.session.add(assistant)
                    created_count += 1
                    logger.info(f"✅ Created specialized assistant: {assistant_data['name']} ({assistant_data['role']})")
            
            if created_count > 0:
                db.session.commit()
                logger.info(f"🎯 Created {created_count} specialized assistants")
            else:
                logger.info("🎯 All specialized assistants already exist")
                
    except Exception as e:
        logger.error(f"Error creating specialized assistants: {e}")
        db.session.rollback()

# Create specialized assistants
create_specialized_assistants()

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