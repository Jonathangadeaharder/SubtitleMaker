@echo off
REM Batch script to run subtitle_maker.py with --no-preview flag
REM Assumes venv is located in the parent directory

cd /d "%~dp0"

REM Check if venv exists in parent directory
if exist "..\venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call "..\venv\Scripts\activate.bat"
) else if exist "..\venv\Scripts\python.exe" (
    echo Using virtual environment python directly...
    set PYTHON_PATH=..\venv\Scripts\python.exe
    goto :run_script
) else (
    echo Virtual environment not found in parent directory.
    echo Looking for system Python...
    set PYTHON_PATH=python
)

:run_script
echo Running subtitle maker with --no-preview flag...
if defined PYTHON_PATH (
    "%PYTHON_PATH%" subtitle_maker.py --no-preview %*
) else (
    python subtitle_maker.py --no-preview %*
)

echo.
echo Script finished. Press any key to exit...
pause >nul