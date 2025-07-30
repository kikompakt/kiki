"""
Initialisiert die spezifizierten OpenAI Assistenten in der Datenbank
"""

import os
from app_simplified import app, db, User
from werkzeug.security import generate_password_hash

def init_assistants_and_users():
    """Initialize database with specified assistants and default users"""
    
    with app.app_context():
        # Create all tables
        db.create_all()
        print("✅ Database tables created")
        
        # Create default admin user if not exists
        if not User.query.filter_by(username='admin').first():
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                role='admin'
            )
            db.session.add(admin_user)
            print("✅ Admin user created (admin/admin123)")
            
        # Create default demo user if not exists
        if not User.query.filter_by(username='demo').first():
            demo_user = User(
                username='demo',
                password_hash=generate_password_hash('demo123'),
                role='user'
            )
            db.session.add(demo_user)
            print("✅ Demo user created (demo/demo123)")
        
        db.session.commit()
        print("✅ Default users initialized")
        
        print("\n🤖 OpenAI Assistants Configuration:")
        print("The following assistants are configured in simple_orchestrator.py:")
        print("- Supervisor: asst_19FlW2QtTAIb7Z96f3ukfSre (gpt-4.1-nano)")
        print("- Der Autor: asst_UCpHRYdDK2uPsb7no8Zw5Z0p (gpt-4.1-nano)")
        print("- Der Pädagoge: asst_tmj7Nz75MSwjPSrBf4KV2EIt (gpt-4.1-nano)")
        print("- Der Prüfer: asst_qH5a6MsVByLHP2ZLQ8gT8jg0 (gpt-4.1-nano)")
        print("\n✅ Database initialization complete!")

if __name__ == '__main__':
    init_assistants_and_users()