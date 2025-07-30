"""
Database Migration Script für Railway PostgreSQL
Erstellt alle benötigten Tabellen und initialisiert Standard-Daten
"""

import os
import sys
import logging
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_simplified import app, db, User
from werkzeug.security import generate_password_hash

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Create all database tables and initialize default data"""
    
    try:
        with app.app_context():
            logger.info("🔄 Starting database migration...")
            
            # Drop all tables first (for clean migration)
            logger.info("Dropping existing tables...")
            db.drop_all()
            
            # Create all tables
            logger.info("Creating all tables...")
            db.create_all()
            logger.info("✅ All tables created successfully")
            
            # Create default users
            logger.info("Creating default users...")
            
            # Admin user
            if not User.query.filter_by(username='admin').first():
                admin_user = User(
                    username='admin',
                    password_hash=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(admin_user)
                logger.info("✅ Admin user created (admin/admin123)")
            
            # Demo user  
            if not User.query.filter_by(username='demo').first():
                demo_user = User(
                    username='demo',
                    password_hash=generate_password_hash('demo123'),
                    role='user'
                )
                db.session.add(demo_user)
                logger.info("✅ Demo user created (demo/demo123)")
            
            # Commit all changes
            db.session.commit()
            logger.info("✅ Database migration completed successfully!")
            
            # Verify tables exist
            logger.info("Verifying tables...")
            tables = db.engine.table_names()
            expected_tables = ['user', 'project', 'chat_session', 'chat_message', 'uploaded_file', 'course']
            
            for table in expected_tables:
                if table in tables:
                    logger.info(f"✅ Table '{table}' exists")
                else:
                    logger.error(f"❌ Table '{table}' missing!")
            
            logger.info("🎉 Migration complete - System ready!")
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        raise

if __name__ == '__main__':
    migrate_database()