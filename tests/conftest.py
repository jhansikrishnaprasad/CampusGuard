import os, sys, tempfile
from pathlib import Path
_tmp = tempfile.mkdtemp(prefix="campus_test_")
os.environ["CAMPUS_DATA_DIR"] = _tmp
os.environ["ADMIN_PASSWORD"] = "test-password-123"
os.environ["CAMPUS_REQUIRE_LOGIN"] = "true"   # the security tests exercise real authentication
os.environ["CAMPUS_MODELS_DIR"] = str(Path(_tmp) / "models")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
