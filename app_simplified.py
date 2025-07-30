"""
Kiki Chat - Vereinfachtes KI-Kursstudio
Optimiert für Railway Deployment

Vereinfachte Version mit direkter OpenAI Assistant Integration
"""

import os
import logging
from datetime import datetime
from typing import Dict, Optional, Any

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask App Configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kiki-chat-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Database Configuration (Railway compatible)
database_url = os.environ.get('DATABASE_URL', 'sqlite:///kiki_chat.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create upload folder
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==============================================
# DATABASE MODELS (Simplified)
# ==============================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    title = db.Column(db.String(200), default='New Chat')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_type = db.Column(db.String(20), nullable=False)  # 'user', 'assistant', 'system'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UploadedFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    processed = db.Column(db.Boolean, default=False)
    chunks_count = db.Column(db.Integer, default=0)
    doc_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    full_content = db.Column(db.Text)
    quality_score = db.Column(db.Float)
    content_length = db.Column(db.Integer)
    status = db.Column(db.String(20), default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==============================================
# AUTHENTICATION HELPERS
# ==============================================

def login_required(f):
    """Decorator for login requirement"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator for admin privileges"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            flash('Admin rights required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================
# ROUTES
# ==============================================

@app.route('/')
def index():
    """Homepage - redirect to chat"""
    return redirect(url_for('chat'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            flash(f'Welcome, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout and clear session"""
    username = session.get('username', 'Unknown')
    session.clear()
    flash('Successfully logged out', 'success')
    logger.info(f"User {username} logged out")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard"""
    user = User.query.get(session['user_id'])
    projects = Project.query.filter_by(user_id=session['user_id']).order_by(Project.created_at.desc()).all()
    
    return render_template('dashboard.html', user=user, projects=projects)

@app.route('/chat')
def chat():
    """Main chat interface - simplified for MVP"""
    project_id = request.args.get('project_id', 'default')
    session_id = request.args.get('session_id')
    
    # Mock user for simplified demo
    mock_user = {
        'id': 1,
        'username': 'demo_user',
        'role': 'user'
    }
    
    if not session_id:
        # Create new chat session
        try:
            new_session = ChatSession(
                user_id=mock_user['id'], 
                project_id=int(project_id) if project_id != 'default' else None,
                title='New Chat'
            )
            db.session.add(new_session)
            db.session.commit()
            session_id = new_session.id
        except:
            # Fallback to timestamp-based session
            session_id = f"demo_{int(datetime.now().timestamp())}"
    
    return render_template('chat_simple.html', 
                         project_id=project_id, 
                         session_id=session_id, 
                         user=mock_user)

@app.route('/new-project', methods=['POST'])
@login_required
def new_project():
    """Create new project"""
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    
    if not title:
        flash('Project title is required', 'error')
        return redirect(url_for('dashboard'))
    
    project = Project(
        user_id=session['user_id'],
        title=title,
        description=description
    )
    db.session.add(project)
    db.session.commit()
    
    flash(f'Project "{title}" created successfully', 'success')
    return redirect(url_for('chat', project_id=project.id))

@app.route('/courses')
def courses():
    """Display all created courses"""
    try:
        all_courses = Course.query.order_by(Course.created_at.desc()).limit(50).all()
        return render_template('courses.html', courses=all_courses)
    except Exception as e:
        logger.error(f"Error loading courses: {e}")
        flash('Error loading courses', 'error')
        return redirect(url_for('chat'))

@app.route('/course/<int:course_id>')
def view_course(course_id):
    """View a specific course"""
    try:
        course = Course.query.get_or_404(course_id)
        return render_template('course_view.html', course=course)
    except Exception as e:
        logger.error(f"Error loading course {course_id}: {e}")
        flash('Course not found', 'error')
        return redirect(url_for('courses'))

@app.route('/course/<int:course_id>/download')
def download_course(course_id):
    """Download course as text file"""
    try:
        course = Course.query.get_or_404(course_id)
        
        from flask import Response
        
        # Create text content
        content = f"""# {course.title}

{course.description if course.description else ''}

## Kursinhalt

{course.full_content}

---
Erstellt am: {course.created_at.strftime('%Y-%m-%d %H:%M:%S')}
Qualitäts-Score: {course.quality_score if course.quality_score else 'Nicht bewertet'}
"""
        
        # Create filename
        safe_title = ''.join(c for c in course.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = f"{safe_title}.txt"
        
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
        
    except Exception as e:
        logger.error(f"Error downloading course {course_id}: {e}")
        flash('Download failed', 'error')
        return redirect(url_for('view_course', course_id=course_id))

@app.route('/upload-file', methods=['POST'])
def upload_file():
    """Simplified file upload for knowledge base"""
    try:
        project_id = request.form.get('project_id', 'default')
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename)
        if not filename:
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400
        
        # Save file
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(upload_path)
        
        # Process with Knowledge Manager (if available)
        try:
            from knowledge_manager import get_knowledge_manager
            km = get_knowledge_manager()
            
            numeric_project_id = int(project_id) if project_id != 'default' else 1
            result = km.process_uploaded_file(
                file_path=upload_path,
                project_id=numeric_project_id,
                user_id=1,  # Mock user
                filename=filename
            )
            
            if result['success']:
                return jsonify({
                    'success': True,
                    'message': f'File "{filename}" processed successfully',
                    'details': result
                })
            else:
                return jsonify({'success': False, 'error': result.get('error', 'Processing failed')}), 500
                
        except Exception as e:
            logger.warning(f"Knowledge manager not available: {e}")
            return jsonify({
                'success': True,
                'message': f'File "{filename}" uploaded (knowledge processing unavailable)',
                'details': {'filename': filename, 'chunks_count': 0}
            })
            
    except Exception as e:
        logger.error(f"File upload error: {e}")
        return jsonify({'success': False, 'error': f'Upload error: {str(e)}'}), 500

# ==============================================
# SOCKETIO EVENTS
# ==============================================

@socketio.on('connect')
def handle_connect():
    """Client connected"""
    emit('status', {'msg': 'Connected to Kiki Chat'})
    logger.info("SocketIO connection established")

@socketio.on('join_project')
def handle_join_project(data):
    """User joins a chat session"""
    session_id = data.get('session_id')
    if not session_id:
        emit('error_message', {'error': 'session_id missing'})
        return

    join_room(f'session_{session_id}')
    emit('status', {'msg': f'Joined chat session {session_id}'})
    
    # Load chat history
    try:
        messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.created_at.asc()).limit(50).all()
        
        for msg in messages:
            emit('new_message', {
                'sender': 'AI-Assistant' if msg.message_type == 'assistant' else 'You',
                'message': msg.content,
                'timestamp': msg.created_at.strftime('%H:%M:%S'),
                'type': msg.message_type
            })
            
        if messages:
            emit('status', {'msg': f'{len(messages)} messages loaded'})
            
    except Exception as e:
        logger.error(f"Error loading chat history: {e}")
    
    logger.info(f"User joined session {session_id}")

@socketio.on('leave_project')
def handle_leave_project(data):
    """User leaves project chat"""
    session_id = data.get('session_id')
    if session_id:
        leave_room(f'session_{session_id}')
        logger.info(f"User left session {session_id}")

@socketio.on('user_message')
def handle_user_message(data):
    """Process user message and forward to simplified orchestrator"""
    message = data.get('message', '').strip()
    session_id = data.get('session_id')
    project_id = data.get('project_id', 'default')
    
    if not message:
        emit('error_message', {'error': 'Empty message'})
        return
    
    # Mock user
    mock_user = {'id': 1, 'username': 'demo_user'}
    
    # Save user message
    try:
        chat_message = ChatMessage(
            session_id=session_id,
            user_id=mock_user['id'],
            message_type='user',
            content=message
        )
        db.session.add(chat_message)
        db.session.commit()
    except Exception as e:
        logger.error(f"Database error saving message: {e}")
    
    # Send user message to all participants
    emit('new_message', {
        'sender': mock_user['username'],
        'message': message,
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'type': 'user'
    }, room=f'session_{session_id}')
    
    # Process with simplified orchestrator
    from simple_orchestrator import get_or_create_orchestrator
    
    orchestrator = get_or_create_orchestrator(
        project_id=str(project_id),
        session_id=str(session_id),
        socketio=socketio
    )
    
    # Process message
    orchestrator.process_message(message, mock_user)
    
    logger.info(f"Message from {mock_user['username']} processed: {message[:50]}...")

# ==============================================
# DATABASE INITIALIZATION
# ==============================================

def init_database():
    """Initialize database with default data"""
    with app.app_context():
        try:
            # Wait for database to be ready
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    from sqlalchemy import text
                    with db.engine.connect() as connection:
                        connection.execute(text('SELECT 1'))
                    logger.info("✅ Database connection successful!")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.info(f"Database not ready, attempt {attempt + 1}/{max_retries}: {e}")
                        import time
                        time.sleep(2)
                    else:
                        logger.warning("Database connection timeout, proceeding anyway...")
            
            # Create all tables
            db.create_all()
            logger.info("✅ Database tables created")
            
            # Create default admin user if not exists
            if not User.query.filter_by(username='admin').first():
                admin_user = User(
                    username='admin',
                    password_hash=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(admin_user)
                logger.info("✅ Admin user created")
                
            # Create default demo user
            if not User.query.filter_by(username='demo').first():
                demo_user = User(
                    username='demo',
                    password_hash=generate_password_hash('demo123'),
                    role='user'
                )
                db.session.add(demo_user)
                logger.info("✅ Demo user created")
            
            db.session.commit()
            logger.info("✅ Database initialization completed successfully!")
            
        except Exception as e:
            logger.error(f"⚠️  Database initialization error: {e}")
            logger.info("App will continue with limited functionality...")

# ==============================================
# APPLICATION STARTUP
# ==============================================

if __name__ == '__main__':
    init_database()
    logger.info("Starting Kiki Chat...")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    
    # Development mode
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)