"""Reset (or create) an administrator password: python scripts/reset_admin_password.py [username]"""
import getpass, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal, get_engine, init_db
from app.models import User
from app.security import hash_password

get_engine(); init_db()
name = sys.argv[1] if len(sys.argv) > 1 else "admin"
pw = getpass.getpass("New password (min 10 chars): ")
if len(pw) < 10 or pw != getpass.getpass("Repeat: "):
    sys.exit("Passwords differ or are too short.")
with SessionLocal() as db:
    u = db.query(User).filter(User.username == name).first()
    if u: u.password_hash, u.active = hash_password(pw), True
    else: db.add(User(username=name, password_hash=hash_password(pw), role="admin"))
    db.commit()
print("Password set for", name)
