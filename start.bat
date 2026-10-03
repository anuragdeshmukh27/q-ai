@echo off
setlocal
rem Q launcher: stops old Q servers and their windows, frees ports 8000 and 5173, starts the backend and the frontend, opens the browser.
rem Safe to double-click again while old Q windows are still open.
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [!] backend\.venv is missing. Run the setup steps in README.md first.
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo [!] frontend\node_modules is missing. Run "npm install" in the frontend folder first.
  pause
  exit /b 1
)

echo Stopping old Q servers and freeing ports 8000 and 5173...
powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; for ($i=0; $i -lt 4; $i++) { Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'create_app.*--port 8000|--port 5173' -and $_.CommandLine -notmatch 'Get-CimInstance' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null }; foreach ($p in 8000,5173) { Get-NetTCPConnection -LocalPort $p -State Listen | ForEach-Object { taskkill /PID $_.OwningProcess /T /F | Out-Null } }; Start-Sleep -Milliseconds 700; if (-not (Get-NetTCPConnection -LocalPort 8000,5173 -State Listen)) { break } }"
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo [!] Port 8000 or 5173 is still in use by a program that could not be stopped. Close it and run start.bat again.
  pause
  exit /b 1
)

powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:11434/api/version -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo.
  echo [!] Ollama is not running. Demo mode with recorded builds works without it.
  echo     For live builds start Ollama first: open the Ollama app, or run "ollama serve".
  echo.
) else (
  echo Ollama is running.
)

echo Starting the backend on http://localhost:8000 ...
start "Q backend" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8000"

echo Starting the frontend on http://localhost:5173 ...
start "Q frontend" /D "%~dp0frontend" cmd /k "npm run dev -- --port 5173 --strictPort"

echo Waiting for both servers (up to 90 seconds)...
rem Check 127.0.0.1 and [::1] directly: waiting on the name "localhost" costs about 2 seconds per try when the first address it picks does not answer.
powershell -NoProfile -Command "function Up($urls) { foreach ($u in $urls) { try { Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch {} }; return $false }; $end=(Get-Date).AddSeconds(90); $b=$false; $f=$false; while ((Get-Date) -lt $end -and -not ($b -and $f)) { if (-not $b) { $b = Up @('http://127.0.0.1:8000/api/health') }; if (-not $f) { $f = Up @('http://127.0.0.1:5173','http://[::1]:5173') }; Start-Sleep -Milliseconds 500 }; if (-not $b) { Write-Host '[!] The backend did not answer on port 8000. Read the Q backend window.' }; if (-not $f) { Write-Host '[!] The frontend did not answer on port 5173. Read the Q frontend window.' }; if ($b -and $f) { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo.
  echo [!] Q did not start completely. The two server windows show the reason.
  pause
  exit /b 1
)

start "" http://localhost:5173
echo.
echo Q is running at http://localhost:5173  (close the two server windows to stop it).
endlocal
