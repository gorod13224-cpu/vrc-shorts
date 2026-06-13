import requests
import re
import random
from flask import Flask, redirect

app = Flask(__name__)

@app.route('/')
def home():
    return "Server is running!"

@app.route('/shorts')
def get_random_short():
    # Поиск по тегу #рекомендации + фильтр на короткие видео
    url = "https://www.youtube.com/results?search_query=%23shorts+%D1%80%D0%B5%D0%BA%D0%BE%D0%BC%D0%B5%D0%BD%D0%B4%D0%B0%D1%86%D0%B8%D0%B8&sp=EgIYAQ%253D%253D"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        # Выдергиваем ID роликов из кода страницы
        video_ids = re.findall(r'"videoId":"([^"]+)"', response.text)
        
        if video_ids:
            unique_ids = list(set(video_ids))
            random_id = random.choice(unique_ids)
            # Перенаправляем плеер на случайный шортс
            return redirect(f"https://www.youtube.com/watch?v={random_id}")
    except Exception:
        pass
        
    # Если Ютуб закапризничал — выдаем дефолтный мем-заглушку
    return redirect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

if __name__ == "__main__":
    app.run()
