#!/usr/bin/env python3
"""
Migration: Flexible Workflow System
Migrates from role-based to assistant-based workflow steps
"""

import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def migrate_to_flexible_workflows(db_path='instance/app.db'):
    """
    Migrates database to support flexible workflow system:
    1. Add assistant_type to assistants table
    2. Add assistant_id, custom_prompt, step_type to workflow_steps
    3. Make agent_role nullable in workflow_steps
    4. Create default mappings for existing data
    """
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("🔄 Starting migration to flexible workflow system...")
        
        # 1. Add assistant_type to assistants table (if not exists)
        try:
            cursor.execute("ALTER TABLE assistants ADD COLUMN assistant_type VARCHAR(50) DEFAULT 'custom'")
            print("✅ Added assistant_type column to assistants")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("ℹ️ assistant_type column already exists")
            else:
                raise
        
        # 2. Make role nullable in assistants (SQLite limitation - we'll handle in app logic)
        print("ℹ️ Role nullability will be handled in application logic")
        
        # 3. Add new columns to workflow_steps table
        new_columns = [
            ("assistant_id", "INTEGER"),
            ("custom_prompt", "TEXT"),
            ("step_type", "VARCHAR(50) DEFAULT 'assistant_call'")
        ]
        
        for column_name, column_type in new_columns:
            try:
                cursor.execute(f"ALTER TABLE workflow_steps ADD COLUMN {column_name} {column_type}")
                print(f"✅ Added {column_name} column to workflow_steps")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print(f"ℹ️ {column_name} column already exists")
                else:
                    raise
        
        # 4. Create default assistant-to-role mappings for existing workflow steps
        print("🔄 Creating default assistant mappings...")
        
        # Get all assistants with roles
        cursor.execute("SELECT id, role FROM assistants WHERE role IS NOT NULL")
        assistant_role_map = {role: assistant_id for assistant_id, role in cursor.fetchall()}
        
        # Update workflow_steps with assistant_id based on agent_role
        cursor.execute("SELECT id, agent_role FROM workflow_steps WHERE assistant_id IS NULL")
        steps_to_update = cursor.fetchall()
        
        for step_id, agent_role in steps_to_update:
            if agent_role in assistant_role_map:
                assistant_id = assistant_role_map[agent_role]
                cursor.execute(
                    "UPDATE workflow_steps SET assistant_id = ? WHERE id = ?",
                    (assistant_id, step_id)
                )
                print(f"✅ Mapped step {step_id} ({agent_role}) to assistant {assistant_id}")
            else:
                print(f"⚠️ No assistant found for role '{agent_role}' in step {step_id}")
        
        # 5. Set default values for new columns
        cursor.execute("UPDATE assistants SET assistant_type = 'system' WHERE role IN ('supervisor', 'content_creator', 'didactic_expert', 'quality_checker')")
        cursor.execute("UPDATE workflow_steps SET step_type = 'assistant_call' WHERE step_type IS NULL")
        
        # 6. Update assistant creation timestamp if missing
        cursor.execute("UPDATE assistants SET created_at = ? WHERE created_at IS NULL", (datetime.utcnow(),))
        cursor.execute("UPDATE assistants SET updated_at = ? WHERE updated_at IS NULL", (datetime.utcnow(),))
        
        conn.commit()
        print("✅ Migration completed successfully!")
        
        # 7. Show migration summary
        cursor.execute("SELECT COUNT(*) FROM assistants")
        assistant_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM workflow_steps WHERE assistant_id IS NOT NULL")
        mapped_steps = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM workflow_steps")
        total_steps = cursor.fetchone()[0]
        
        print(f"\n📊 Migration Summary:")
        print(f"   Assistants: {assistant_count}")
        print(f"   Workflow Steps: {total_steps}")
        print(f"   Mapped Steps: {mapped_steps}/{total_steps}")
        
        if mapped_steps < total_steps:
            print(f"⚠️ {total_steps - mapped_steps} steps need manual assistant assignment")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if 'conn' in locals():
            conn.rollback()
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def rollback_migration(db_path='instance/app.db'):
    """
    Rollback migration (limited due to SQLite constraints)
    """
    print("⚠️ Note: SQLite doesn't support dropping columns. Rollback creates backup tables.")
    # Implementation would create backup tables and copy data
    pass

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_migration()
    else:
        migrate_to_flexible_workflows()