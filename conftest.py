"""pytest 루트 conftest. 프로젝트 루트를 sys.path에 등록하여 core/db 임포트를 보장한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
