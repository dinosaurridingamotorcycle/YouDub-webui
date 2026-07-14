import sys
from pathlib import Path

# 确保在当前目录下直接运行可以同级导入
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from cli import main

if __name__ == "__main__":
    sys.exit(main())
