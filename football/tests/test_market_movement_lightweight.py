import os
from pathlib import Path
import subprocess
import sys


def test_market_movement_importa_sin_site_packages():
    """El hot refresh instala solo requests: market_movement no puede exigir NumPy/SciPy."""
    src = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import futbol_pred.market_movement"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
