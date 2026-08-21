import sys
from pathlib import Path

# Permite importar futbol_pred sin instalar el paquete.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
