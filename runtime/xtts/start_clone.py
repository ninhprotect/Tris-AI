"""Read-only reuse of the installed CUDA runtime; no package install/download.

Launch with imagegen/.venv Python (torch 2.5.1+cu121 supports GTX 1060),
then resolve missing speech dependencies from the existing XTTS environment.
Both environments must use the same Python minor version. CPU-only launches
with the XTTS Python remain supported. Never import a second torch build.
"""
import os
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
speech_packages = here / '.venv' / 'Lib' / 'site-packages'
if str(speech_packages) not in sys.path:
    sys.path.append(str(speech_packages))
sys.path.insert(0, str(here))
# All checkpoints have been installed already. Inference must stay offline.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ.setdefault('CLONE_DEVICE', 'auto')
runpy.run_path(str(here / 'clone_server.py'), run_name='__main__')
