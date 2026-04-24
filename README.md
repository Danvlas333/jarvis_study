# Jarvis Study

## Что положить рядом с проектом
- `app.py`
- `auth.py`
- `planner.py`
- `user_store.py`
- `tts_engine.py`
- папку `templates/`
- папку `user_data/`
- файл `jarvis_study.db`
- файл `requirements.txt`
- папку `mpit/` с голосами:
  - `ru_RU-ruslan-medium.onnx`
  - `ru_RU-ruslan-medium.onnx.json`
  - `ru_RU-irina-medium.onnx`
  - `ru_RU-irina-medium.onnx.json`

## Windows
1. `python -m venv .venv`
   Создаёт виртуальное окружение.

2. `.venv\Scripts\activate`
   Включает виртуальное окружение.

3. `pip install -r requirements.txt`
   Ставит Python-зависимости проекта.

4. Установить [Ollama](https://ollama.com/download/windows)
   Ставит локальную нейросеть.

5. `ollama pull qwen2.5:3b`
   Скачивает быструю модель.

6. `ollama pull mistral:7b-instruct-v0.3-q4_0`
   Скачивает основную умную модель.

7. `python app.py`
   Запускает сайт.

8. Открыть `http://127.0.0.1:8000`
   Открывает сайт в браузере.

## Linux
1. `python3 -m venv .venv`
   Создаёт виртуальное окружение.

2. `source .venv/bin/activate`
   Включает виртуальное окружение.

3. `pip install -r requirements.txt`
   Ставит Python-зависимости проекта.

4. `curl -fsSL https://ollama.com/install.sh | sh`
   Ставит Ollama.

5. `ollama pull qwen2.5:3b`
   Скачивает быструю модель.

6. `ollama pull mistral:7b-instruct-v0.3-q4_0`
   Скачивает основную умную модель.

7. `python3 app.py`
   Запускает сайт.

8. Открыть `http://127.0.0.1:8000`
   Открывает сайт в браузере.

## Логины
- Ученик: `student` / `student123`
- Учитель: `teacher` / `teacher123`
- Администратор: `admin` / `admin123`
