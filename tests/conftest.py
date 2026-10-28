import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Tests run on a throwaway SQLite file, never on the production database.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(ROOT, "tests", "private", "test.db")
os.environ.setdefault("APP_SECRET", "test-secret")
