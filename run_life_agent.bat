@echo off
cd /d d:\antigravity\life-agent
echo ==============================================
echo [%date% %time%] Starting Life-Agent...
echo ==============================================
python main.py
python import_notion_to_gcal.py
python generate_free_slots.py
python schedule_todos.py --days=7 --offset=0
python schedule_todos.py --days=7 --offset=7
python schedule_todos.py --days=7 --offset=14
python schedule_todos.py --days=7 --offset=21
python schedule_todos.py --days=7 --offset=28
echo ==============================================
echo [%date% %time%] Life-Agent run complete!
echo ==============================================
