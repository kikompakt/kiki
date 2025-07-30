"""
SQLAlchemy Database Models für Intelligentes KI-Kursstudio
Unterstützt sowohl SQLite (lokal) als auch PostgreSQL (Railway)
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class Project(db.Model):
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatSession(db.Model):
    __tablename__ = 'chat_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    title = db.Column(db.String(200), default='New Chat')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_sessions.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    sender = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UploadedFile(db.Model):
    __tablename__ = 'uploaded_files'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    processed = db.Column(db.Boolean, default=False)
    chunks_count = db.Column(db.Integer, default=0)
    embedding_model = db.Column(db.String(100))
    collection_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Assistant(db.Model):
    __tablename__ = 'assistants'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    assistant_id = db.Column(db.String(100), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=True)  # CHANGED: Optional for flexibility
    description = db.Column(db.Text)
    instructions = db.Column(db.Text)
    model = db.Column(db.String(50), default='gpt-4o')
    is_active = db.Column(db.Boolean, default=True)
    order_index = db.Column(db.Integer, default=0)
    
    # NEW: Assistant type categorization (optional)
    assistant_type = db.Column(db.String(50), default='custom')  # custom, system, workflow
    
    # Advanced behavior parameters
    temperature = db.Column(db.Float, default=0.7)
    top_p = db.Column(db.Float, default=1.0)
    max_tokens = db.Column(db.Integer, default=2000)
    frequency_penalty = db.Column(db.Float, default=0.0)
    presence_penalty = db.Column(db.Float, default=0.0)
    
    # Workflow settings
    retry_attempts = db.Column(db.Integer, default=3)
    timeout_seconds = db.Column(db.Integer, default=300)
    error_handling = db.Column(db.String(20), default='graceful')
    
    # Performance settings
    response_limit = db.Column(db.Integer, default=30)
    context_window = db.Column(db.Integer, default=128000)
    
    # Behavior presets
    behavior_preset = db.Column(db.String(20), default='balanced')
    custom_system_message = db.Column(db.Text)
    
    # Tool configuration
    enabled_tools = db.Column(db.Text, default='["create_content","optimize_didactics","critically_review","request_user_feedback","knowledge_lookup"]')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Workflow(db.Model):
    __tablename__ = 'workflows'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    workflow_type = db.Column(db.String(50), default='course_creation')
    is_active = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WorkflowStep(db.Model):
    __tablename__ = 'workflow_steps'
    
    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflows.id'), nullable=False)
    
    # NEW FLEXIBLE SYSTEM: Direct assistant assignment
    assistant_id = db.Column(db.Integer, db.ForeignKey('assistants.id'), nullable=False)
    
    # LEGACY SUPPORT: Keep agent_role for backward compatibility (nullable)
    agent_role = db.Column(db.String(50), nullable=True)
    
    step_name = db.Column(db.String(100), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True)
    is_parallel = db.Column(db.Boolean, default=False)
    retry_attempts = db.Column(db.Integer, default=3)
    timeout_seconds = db.Column(db.Integer, default=180)
    execution_condition = db.Column(db.String(200))
    input_source = db.Column(db.String(100))
    output_target = db.Column(db.String(100))
    
    # NEW: Custom prompt for this step
    custom_prompt = db.Column(db.Text)
    
    # NEW: Step type for different execution modes
    step_type = db.Column(db.String(50), default='assistant_call')  # assistant_call, condition, delay
    
    # Relationship to get assistant details
    assistant = db.relationship('Assistant', backref='workflow_steps')

class WorkflowExecution(db.Model):
    __tablename__ = 'workflow_executions'
    
    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflows.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    input_data = db.Column(db.Text)
    output_data = db.Column(db.Text)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    execution_time_seconds = db.Column(db.Integer)

class Course(db.Model):
    __tablename__ = 'courses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    workflow_execution_id = db.Column(db.Integer, db.ForeignKey('workflow_executions.id'))
    
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    course_topic = db.Column(db.String(200))
    target_audience = db.Column(db.String(200))
    estimated_duration = db.Column(db.String(100))
    
    # Course content
    full_content = db.Column(db.Text)  # Complete course text
    outline = db.Column(db.Text)       # Course outline/structure
    learning_objectives = db.Column(db.Text)  # JSON list of objectives
    
    # Status and metadata
    status = db.Column(db.String(20), default='draft')  # draft, published, archived
    quality_score = db.Column(db.Float)
    content_length = db.Column(db.Integer)  # Character count
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = db.Column(db.DateTime)

class CourseSection(db.Model):
    __tablename__ = 'course_sections'
    
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    
    section_title = db.Column(db.String(200), nullable=False)
    section_content = db.Column(db.Text)
    section_order = db.Column(db.Integer, nullable=False)
    section_type = db.Column(db.String(50), default='chapter')  # chapter, exercise, summary
    
    learning_objectives = db.Column(db.Text)  # JSON list for this section
    estimated_duration = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow) 