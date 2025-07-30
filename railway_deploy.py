#!/usr/bin/env python3
"""
Railway Deployment Script für Kiki Chat
Führt Datenbank-Migration und App-Start durch
"""

import os
import sys
import logging
import time

# Setup logging for Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def wait_for_database(max_retries=30, delay=2):
    """Wait for database to be available"""
    logger.info("🔄 Waiting for database connection...")
    
    for attempt in range(max_retries):
        try:
            from app_simplified import app, db
            from sqlalchemy import text
            with app.app_context():
                # Try to connect to database (SQLAlchemy 2.0+ syntax)
                with db.engine.connect() as connection:
                    connection.execute(text('SELECT 1'))
                logger.info("✅ Database connection successful!")
                return True
        except Exception as e:
            logger.info(f"Attempt {attempt + 1}/{max_retries}: Database not ready ({e})")
            time.sleep(delay)
    
    logger.error("❌ Database connection failed after all attempts")
    return False

def run_migration():
    """Run database migration"""
    logger.info("🚀 Starting Railway deployment...")
    
    # Wait for database
    if not wait_for_database():
        logger.error("❌ Database not available - aborting deployment")
        sys.exit(1)
    
    # Run migration
    try:
        logger.info("🔄 Running database migration...")
        from migrate_database import migrate_database
        migrate_database()
        logger.info("✅ Database migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        # Don't exit - let Railway handle restart
        logger.info("Continuing with app startup despite migration error...")
    
    logger.info("✅ Railway deployment completed!")

if __name__ == '__main__':
    run_migration()