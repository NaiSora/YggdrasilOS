import sys
from pathlib import Path

# Les tests importent bot, database et cogs depuis la racine du projet
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
