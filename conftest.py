import os
import sys

# Make scripts/setup_db.py importable from tests (scripts/ isn't a package).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
