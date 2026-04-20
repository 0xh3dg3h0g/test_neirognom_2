# Нейроагроном

## Запуск проекта

1. `cd backend && pip install fastapi paho-mqtt uvicorn`
2. `uvicorn main:app --reload --port 8000`
3. `python watchdog.py`  
   Запускать в отдельном терминале из корня проекта.
4. `python sim_esp32.py`  
   Запускать в отдельном терминале из корня проекта для тестовой телеметрии.
5. `cd frontend && npm install && npm run dev`
