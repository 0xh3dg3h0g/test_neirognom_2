![Neuroagronomist](frontend/src/assets/gnome_2.png)

# Neuroagronomist

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-Frontend-61DAFB?logo=react&logoColor=111111)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-Simulator-E7352C?logo=espressif&logoColor=white)

**Neuroagronomist** - прототип системы автоматизации гидропонной теплицы. Проект принимает телеметрию датчиков по MQTT, сохраняет измерения в SQLite, показывает состояние фермы в React-интерфейсе и отправляет команды исполнительным устройствам через симулятор ESP32.

## Описание проекта

Система построена как связка из трёх основных компонентов:

- **FastAPI backend** принимает MQTT-телеметрию, сохраняет показания в SQLite, предоставляет REST API для frontend и запускает внутренний watchdog для AI-анализа аномалий климата.
- **React frontend** отображает температуру, влажность, температуру воды, состояние устройств, журнал AI-решений, переключение режимов симуляции и чат с ассистентом.
- **ESP32 simulator** имитирует контроллер лотка: публикует синтетические данные датчиков и слушает MQTT-команды для помпы, света и вентилятора.

Схема обмена данными:

```text
sim_esp32.py -> MQTT broker -> backend/main.py -> SQLite farm.db
                                      |
                                      v
                              React dashboard
                                      |
                                      v
                         MQTT commands to devices
```

## Структура репозитория

```text
.
|-- backend/
|   |-- main.py              # FastAPI, MQTT-клиент, SQLite, AI watchdog
|   |-- .env.example         # безопасный шаблон переменных окружения
|   `-- farm.db              # локальная SQLite-БД, создаётся при запуске
|-- frontend/
|   |-- package.json         # зависимости и npm-скрипты React/Vite
|   `-- src/                 # UI, компоненты, стили и ассеты
|-- sim_esp32.py             # симулятор датчиков и исполнительных устройств ESP32
|-- start_farm.bat           # запуск всей системы в один клик на Windows
|-- requirements.txt         # Python-зависимости backend и симулятора
`-- README.md
```

## Требования к окружению

- **Python 3.11+** для backend и симулятора ESP32.
- **Node.js 20+** и npm для frontend на React/Vite.
- **Windows** для запуска через `start_farm.bat`.
- Доступ к MQTT-брокеру и AI API, указанным в настройках проекта.

## Установка

Создайте и активируйте виртуальное окружение Python из корня репозитория:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Установите зависимости frontend:

```powershell
cd frontend
npm install
cd ..
```

## Настройка

Backend и симулятор читают переменные окружения из файла:

```text
.env
```

Создайте этот файл по шаблону `.env.example`.

MQTT-брокер настраивается через переменные окружения `BROKER_HOST` и `BROKER_PORT`. По умолчанию используется локальный брокер на `localhost`.

Пример файла `.env`:

```dotenv
BROKER_HOST=127.0.0.1
BROKER_PORT=1883
POLZA_API_KEY=replace_with_your_polza_api_key
AI_MODEL=gpt-5-nano
POLZA_BASE_URL=https://polza.ai/api/v1/chat/completions
```

Что это означает:

- `BROKER_HOST=127.0.0.1` - локальный MQTT-брокер на текущем компьютере.
- `BROKER_PORT=1883` - стандартный MQTT-порт.
- Для сервера можно указать внешний адрес, например изменить `BROKER_HOST` на DNS-имя или IP нужного брокера.

Остальные настройки выполнения:

- SQLite-БД создаётся автоматически по пути `backend/farm.db`.
- Backend запускается на порту `8000`.
- Frontend запускается на порту `5174`.

## Запуск проекта

Самый простой запуск всей системы на Windows:

```powershell
start_farm.bat
```

Скрипт открывает отдельные терминалы и поднимает три процесса:

- **ESP32 simulator**: выполняет `python sim_esp32.py`, раз в секунду публикует climate/water телеметрию в MQTT и принимает команды устройств.
- **FastAPI backend**: выполняет `uvicorn main:app --reload --host 0.0.0.0 --port 8000` из папки `backend/`, инициализирует SQLite, подписывается на MQTT, открывает REST API и запускает внутренний watchdog.
- **React frontend**: выполняет `npm run dev -- --host 0.0.0.0 --port 5174` из папки `frontend/`.

После запуска откройте интерфейс:

```text
http://localhost:5174
```

Backend API доступен по адресу:

```text
http://localhost:8000
```

## Полезные API endpoints

- `GET /` - проверка состояния backend.
- `GET /api/telemetry` - последние значения температуры, влажности и температуры воды.
- `POST /api/device/control` - отправка команды устройству через MQTT.
- `POST /api/ai/decide` - ручной запрос AI-решения по текущей телеметрии.
- `GET /api/logs` - последние решения и действия AI.
- `POST /api/chat` - чат с AI-ассистентом.

## Ручной запуск

Если `start_farm.bat` не используется, запустите процессы в отдельных терминалах.

Симулятор ESP32:

```powershell
venv\Scripts\activate
python sim_esp32.py
```

Backend:

```powershell
cd backend
..\venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```powershell
cd frontend
npm run dev -- --host 0.0.0.0 --port 5174
```

## Примечания

- Симулятор поддерживает режимы `NORMAL`, `HEAT` и `COLD` через MQTT-топик `farm/sim/control`.
- Команды устройствам публикуются в топики вида `farm/tray_1/cmd/{pump|light|fan}`.
