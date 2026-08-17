#!/usr/bin/env python3
import sys, os
sys.argv = ["briefing.py", "weekly"]
exec(open(os.path.join(os.path.dirname(__file__), "briefing.py")).read())
