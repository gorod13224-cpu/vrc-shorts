import os
import requests
import re
import random
import base64
from flask import Flask, Response

app = Flask(__name__)

# Твой рабочий токен
GITHUB_TOKEN = "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"
FILE_PATH = "live_video.txt"

# ЖЕСТКО ПРОПИСЫВАЕМ ТВОИ ДАННЫЕ СЮДА:
REPO_OWNER = "gorod13224-cpu"
REPO_NAME = "vrc-shorts"

SEARCH_QUERIES = [
    "#shorts рекомендации", "#shorts memes funny", "#shorts мегамемы",
    "#shorts приколы тикток", "#shorts тренды", "#shorts угар",
    "#shorts подборка приколов", "#shorts стрим приколы",
    "#shorts нарезки стримеров", "#shorts братишкин", "#shorts стинт",
    "#shorts тоха2х2", "#shorts дрейк", "#shorts глад валакас",
    "#shorts валакас приколы", "#shorts жмышенко валерий альбертович"
]

def update_github_file(content_text):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    sha = None
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        sha = res.json().get("sha")
        
    base64_content = base64.b64encode(content_text.encode('utf-8')).decode('utf-8')
    
    data = {
        "message": "VRChat Bot: Update short URL",
        "content": base64_content
    }
    if sha:
        data["sha"] = sha

    put_res = requests.put(url, headers=headers, json=data)
    return put_res.status_code in [200, 201]

@app.route('/')
def home():
    return f"Server is running! Target Repo: {REPO_OWNER}/{REPO_NAME}"

@app.route('/shorts')
def get_random_short():
    random_query = random.choice(SEARCH_QUERIES)
    search_url = f"https://www.youtube.com/results?search_query={random_query}&sp=EgIYAQ%253D%253D"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    video_id = "R98yY1Ww_6A" # Дефолтный дед Глад
    
    try:
        response = requests.get(search_url, headers=headers, timeout=5)
        video_ids = re.findall(r'"videoId":"([^"]+)"', response.text)
        if video_ids:
            unique_ids = [v for v in list(set(video_ids)) if len(v) == 11]
            if unique_ids:
                video_id = random.choice(unique_ids)
    except Exception:
        pass
        
    full_youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Пушим ссылку в текстовый файл на гитхаб
    update_github_file(full_youtube_url)
        
    return Response("OK", mimetype='text/plain')

if __name__ == "__main__":
    app.run()
