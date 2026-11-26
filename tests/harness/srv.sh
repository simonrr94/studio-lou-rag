#!/bin/sh
curl -s -o /dev/null localhost:8001 || (cd /home/claude/repo && nohup python3 -m http.server 8001 >/tmp/s1.log 2>&1 &)
curl -s -o /dev/null localhost:8002 || (cd /home/claude/base && nohup python3 -m http.server 8002 >/tmp/s2.log 2>&1 &)
sleep 1
