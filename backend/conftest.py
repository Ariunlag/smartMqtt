import os
import sys

# Ensure the backend package root is importable as top-level modules
# (services, api, config, ...) when running pytest from any directory.
BACKEND_ROOT = os.path.dirname(__file__)
REPOSITORY_ROOT = os.path.dirname(BACKEND_ROOT)
sys.path.insert(0, BACKEND_ROOT)
sys.path.insert(0, REPOSITORY_ROOT)
