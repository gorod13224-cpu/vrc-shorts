import requests
import re
import random
from flask import Flask, redirect
from urllib.parse import quote

app = Flask(__name__)

# Полный список поисковых запросов для максимального рандома (включая стримеров и Валакаса)
SEARCH_QUERIES = [
    "#shorts рекомендации",
    "#shorts memes funny",
    "#shorts мегамемы",
    "#shorts приколы тикток",
    "#shorts тренды",
    "#shorts угар",
    "#shorts youtube shorts",
    "#shorts подборка приколов",
    # Твич контент (Братишкин, Стинт и ко):
    "#shorts стрим приколы",
    "#shorts нарезки стримеров",
    "#shorts братишкин",
    "#shorts bratishkinoff",
    "#shorts стинт",
    "#shorts stint",
    "#shorts тоха2х2",
    "#shorts тоха 2х2",
    "#shorts дрейк",
    "#shorts drakeww",
    "#shorts твич фрешмен",
    "#shorts твич приколы",
    # Великий и ужасный Глад Валакас:
    "#shorts глад валакас",
    "#shorts валакас",
    "#shorts валакас приколы",
    "#shorts жмышенко валерий альбертович",
    "#shorts валакас звонки",
    "#shorts денис петров",
    "#shorts валакас рофлы"
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
    
    # Ссылка на поиск с фильтром коротких видео
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
            
            # Фильтруем технический мусор Ютуба (id видео всегда 11 символов)
            unique_ids = [v for v in unique_ids if len(v) == 11]
            
            if unique_ids:
                # Берем случайный видос из пачки найденных
                random_id = random.choice(unique_ids)
                return redirect(f"https://www.youtube.com/watch?v={random_id}")
    except Exception:
        pass
        
    # Заглушка (Рикролл) на случай, если Ютуб временно заблочит запросы
    return redirect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

if __name__ == "__main__":
    app.run()
