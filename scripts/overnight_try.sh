#!/bin/sh
# usage: overnight_try.sh <goal-name in scripts/goals.py> <record-name> [extra record.py args]
cd "$(dirname "$0")/.."
GOAL=$1; NAME=$2; shift 2
export Q_FAST_LIVE=0 PYTHONIOENCODING=utf-8
G=$(backend/.venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'scripts');import goals;print(getattr(goals,'$GOAL'))")
backend/.venv/Scripts/python.exe scripts/record.py "$G" --name "$NAME" --timeout 3000 "$@"
