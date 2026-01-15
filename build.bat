@echo off
if exist ".venv\\Scripts\\python.exe" (".venv\\Scripts\\python.exe" tools\\package.py) else (python tools\\package.py)
pause
