@echo off
:: 设置控制台编码为 UTF-8
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)


pip install pyinstaller
pyinstaller --onefile --windowed ^
--add-data "app.ico;." ^
--icon=app.ico ^
--name WeChatImageSaver ^
自动保存工具.py



pause