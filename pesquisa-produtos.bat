@echo off
title Pesquisa Produtos - Assistente de Compras
cd /d "%~dp0"
echo.
echo  ==========================================
echo   Pesquisa Produtos - Assistente de Compras
echo  ==========================================
echo.
echo  Comandos disponiveis:
echo    pesquisa-produtos search "produto" --cep 00000-000
echo    pesquisa-produtos interactive
echo    pesquisa-produtos setup
echo    pesquisa-produtos cache stats
echo.
cmd /k "C:\Users\nicol\AppData\Local\Programs\Python\Python311\Scripts\pesquisa-produtos.exe"
