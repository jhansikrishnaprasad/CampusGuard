"""Validate and restore a backup. STOP THE SERVER FIRST.
   python scripts/restore_db.py data\\backups\\<file>.db          (validate only, shows what it would restore)
   python scripts/restore_db.py data\\backups\\<file>.db --yes    (restore; current DB is saved as pre_restore_*.db)"""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.services import backup

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 1:
    sys.exit(__doc__)
src = Path(args[0])
res = backup.validate_backup(src)
print("Validation:", "OK" if res["ok"] else "FAILED", "| schema v%s" % res["schema_version"], "| rows:", res["counts"])
for w in res["warnings"]: print("  warning:", w)
for e in res["errors"]: print("  ERROR:", e)
if not res["ok"]:
    sys.exit("Refusing to restore an invalid backup. Nothing was changed.")
if "--yes" not in sys.argv:
    sys.exit("Validated only. Re-run with --yes to restore.")
if config.DB_PATH.exists():  # make sure no running server holds the database
    try:
        c = sqlite3.connect(config.DB_PATH, timeout=1); c.execute("BEGIN EXCLUSIVE"); c.rollback(); c.close()
    except sqlite3.OperationalError:
        sys.exit("The database is in use. Stop the server (Ctrl+C) and try again. Nothing was changed.")
keep = backup.restore_backup(src, config.DB_PATH, config.BACKUP_DIR)
print("Restored. Previous database saved as:", keep.name if keep else "(none existed)")
print("Start the server again; an older schema is migrated automatically.")
