@echo off
setlocal EnableDelayedExpansion

rem Windows (cmd.exe/PowerShell) equivalent of scripts\codex.sh - no git-bash needed.
rem Comments are ASCII-only on purpose: cmd.exe mis-tokenizes UTF-8 (Cyrillic) bytes
rem in batch files on some codepages, even inside REM lines.
rem
rem CODEX_HOME points at .codex\ in the repo root: agent roles, profiles and models
rem are version-controlled and shared by the whole team.
rem Login is reused from %USERPROFILE%\.codex - no need to log in again.
rem
rem   scripts\codex.bat                 normal session (gpt-5.5, xhigh)
rem   scripts\codex.bat -p runner       cheap runner profile
rem   scripts\codex.bat exec "..."      non-interactive

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "CODEX_HOME=%ROOT%\.codex"

if not exist "%CODEX_HOME%" mkdir "%CODEX_HOME%" >nul 2>&1

rem Credentials are linked, not copied: one login for every project, and the
rem key never lands in the repo. mklink (symlink) can need Developer Mode or
rem admin rights; fall back to a copy if it fails.
if not exist "%CODEX_HOME%\auth.json" if exist "%USERPROFILE%\.codex\auth.json" (
    mklink "%CODEX_HOME%\auth.json" "%USERPROFILE%\.codex\auth.json" >nul 2>&1
    if errorlevel 1 copy /y "%USERPROFILE%\.codex\auth.json" "%CODEX_HOME%\auth.json" >nul
)

rem A typo in the profile name isn't caught by Codex itself: `-p runer` silently
rem falls back to the base gpt-5.5/xhigh profile, and that's only visible on the
rem bill. Check it ourselves.
set "PREVARG="
:scanargs
if "%~1"=="" goto scandone
if /i "%PREVARG%"=="-p" (
    set "PROFILE=%~1"
    goto checkprofile
)
if /i "%PREVARG%"=="--profile" (
    set "PROFILE=%~1"
    goto checkprofile
)
:afterprofile
set "PREVARG=%~1"
shift
goto scanargs

:checkprofile
if not exist "%CODEX_HOME%\%PROFILE%.config.toml" (
    echo codex.bat: no such profile "%PROFILE%". 1>&2
    echo Available: 1>&2
    for %%F in ("%CODEX_HOME%\*.config.toml") do echo   %%~nF 1>&2
    exit /b 2
)
goto afterprofile

:scandone

rem The context7 MCP server is wired up from an env var key, not a file in the repo.
set "EXTRA=-c mcp_servers.xds.url=\"https://astryx.atmeta.com/mcp\""
if defined CONTEXT7_API_KEY (
    set EXTRA=%EXTRA% -c mcp_servers.context7.type=\"http\" -c mcp_servers.context7.url=\"https://mcp.context7.com/mcp\" -c mcp_servers.context7.http_headers.CONTEXT7_API_KEY=\"%CONTEXT7_API_KEY%\"
)

codex %EXTRA% %*
exit /b %ERRORLEVEL%
