import requests
import re
import random
from flask import Flask, redirect
from urllib.parse import quote

app = Flask(__name__)

# Огромный список поисковых запросов для максимального рандома мемов и шортсов
SEARCH_QUERIES = [
    "#shorts рекомендации",
    "#shorts memes funny",
    "#shorts мегамемы",
    "#shorts приколы тикток",
    "#shorts тренды",
    "#shorts угар",
    "#shorts youtube shorts",
    "#shorts подборка приколов"
]

@app.route('/')
def home():
    return "Server is running with mega-randomizer!"

@app.route('/shorts')
def get_random_short():
    # 1. Выбираем абсолютно случайный тег из нашего списка
    random_query = random.choice(SEARCH_QUERIES)
    
    # Кодируем текст в понятную для ссылок строку (чтобы кириллица не ломалась)
    encoded_query = quote(random_query)
    
    # Ссылка на поиск с фильтром коротких видео (до 4 минут)
    url = f"https://www.youtube.com/results?search_query={encoded_query}&sp=EgIYAQ%253D%253D"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        video_ids = re.findall(r'"videoId":"([^"]+)"', response.text)
        
        if video_ids:
            # Убираем дубликаты
            unique_ids = list(set(video_ids))
            
            # Фильтруем технический мусор Ютуба, если он попался (опционально)
            unique_ids = [v for v in unique_ids if len(v) == 11]
            
            if unique_ids:
                random_id = random.choice(unique_ids)
                return redirect(f"https://www.youtube.com/watch?v={random_id}")
    except Exception:
        pass
        
    # Заглушка на случай сбоя
    return redirect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

if __name__ == "__main__":
    app.run()
