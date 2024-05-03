#!/bin/bash
script_path=$(realpath $(echo $0))
repo_path=$(dirname ${script_path})
source ${repo_path}/.venv/bin/activate
export PYTHONUNBUFFERED=1
python3 ${repo_path}/chopper_plot.py "$@" &> /tmp/chopper_plot.log &
echo $! > /tmp/chopper_plot.pid
