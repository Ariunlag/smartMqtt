import os
import sys

# Ensure the backend package root is importable as top-level modules
# (services, api, config, ...) when running pytest from any directory.
sys.path.insert(0, os.path.dirname(__file__))
