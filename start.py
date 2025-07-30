"""
Railway Start Script für Kiki Chat
Initialisiert die Datenbank und startet die Anwendung
"""

import os
import logging
from app_simplified import app, db, init_database

# Configure logging for Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Main startup function for Railway"""
    logger.info("Starting Kiki Chat application...")
    
    # Initialize database
    try:
        with app.app_context():
            logger.info("Initializing database...")
            db.create_all()
            logger.info("✅ Database initialized successfully")
            
            # Create default users if they don't exist
            from app_simplified import User
            from werkzeug.security import generate_password_hash
            
            if not User.query.filter_by(username='admin').first():
                admin_user = User(
                    username='admin',
                    password_hash=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(admin_user)
                logger.info("Created admin user")
                
            if not User.query.filter_by(username='demo').first():
                demo_user = User(
                    username='demo',
                    password_hash=generate_password_hash('demo123'),
                    role='user'
                )
                db.session.add(demo_user)
                logger.info("Created demo user")
            
            db.session.commit()
            logger.info("✅ Default users created")
            
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        # Don't exit - let Railway handle restarts
    
    logger.info("✅ Kiki Chat is ready!")

if __name__ == '__main__':
    main()