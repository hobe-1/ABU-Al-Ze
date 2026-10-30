@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo تثبيت متطلبات خدمة الطباعة...
where py >nul 2>nul
if errorlevel 1 (
  echo لم يتم العثور على Python. ثبّت Python 3 من https://www.python.org/downloads/windows/ مع تحديد Add Python to PATH ثم أعد تشغيل هذا الملف.
  pause
  exit /b 1
)
py -m pip install --upgrade pip
py -m pip install pywin32 pillow
if errorlevel 1 (
  echo فشل التثبيت. تحقق من الإنترنت وأعد المحاولة.
  pause
  exit /b 1
)
echo اكتمل التثبيت. شغّل run.bat.
pause
