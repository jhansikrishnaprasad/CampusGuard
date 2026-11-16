"""Create a verified SQLite backup: python scripts/backup_db.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.services import backup

config.ensure_dirs()
if not config.DB_PATH.exists():
    sys.exit(f"No database found at {config.DB_PATH.name}")
dest = backup.create_backup(config.DB_PATH, config.BACKUP_DIR)
v = backup.validate_backup(dest)
print("Backup written:", dest.name, "| valid:", v["ok"], "| rows:", v["counts"])
print("NOTE: this copies the database only. Copy the data/videos and data/evidence folders to keep footage and evidence.")
