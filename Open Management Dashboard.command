#!/bin/bash

cd "/Users/you/Desktop/THERAWEB/Management App " || exit 1
exec "./venv/bin/python3" "./management_app.py" --remote "http://SERVER_IP:8787"
