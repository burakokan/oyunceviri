@echo off
rem Builds packaging\output\OyunCeviri-Kurulum.exe (PyInstaller, then Inno Setup).
cd /d "%~dp0"
"..\.venv\Scripts\python.exe" build_tv_web.py || exit /b 1
"..\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --distpath dist --workpath build OyunCeviri.spec || exit /b 1
"..\.venv\Scripts\python.exe" make_wizard.py || exit /b 1
for /f %%v in ('"..\.venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'..\pc'); from gt.version import VERSION; print(VERSION)"') do set APPVER=%%v
"%LOCALAPPDATA%\Programs\Inno\ISCC.exe" /DAppVersion=%APPVER% OyunCeviri.iss || exit /b 1
echo.
echo Hazir: %~dp0output\OyunCeviri-Kurulum.exe
