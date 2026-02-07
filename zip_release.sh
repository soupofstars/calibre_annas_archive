#!/bin/bash
version=$(
    sed -nE 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*\(([0-9]+),[[:space:]]*([0-9]+),[[:space:]]*([0-9]+)\).*/\1.\2.\3/p' __init__.py
)
zip "calibre_annas_archive-v${version}.zip" __init__.py README.md plugin-import-name-store_annas_archive.txt annas_archive.py config.py constants.py
