@echo off
chcp 65001 >nul
title AUTO3D - extractor de metadatos
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0AUTO3D_metadatos.ps1" %*
if errorlevel 1 pause
