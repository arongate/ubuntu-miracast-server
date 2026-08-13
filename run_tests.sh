#!/bin/bash
cd /home/epepy/Workspace/linux-remote-screen-cast/ubuntu-miracast-server
.venv/bin/python -m pytest tests/test_history.py -v --tb=short -x 2>&1 > /tmp/test_history_output.txt
echo "EXIT_CODE=$?" >> /tmp/test_history_output.txt
