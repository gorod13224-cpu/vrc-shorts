import os
import requests
import re
import random
import base64
from flask import Flask, Response

app = Flask(__name__)

GITHUB_TOKEN = "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"
FILE_PATH = "live_video.txt"
REPO_OWNER = "gorod13224-cpu"
REPO_NAME = "vrc-shorts"

SEARCH_QUERIES = ["#shorts мегамемы", "#shorts приколы тикток", "#shorts угар"]

def update_github_file(content_text):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Проверяем файл
    res = requests.get(url, headers=headers)
    sha = None
    if res.status_code == 200:
        sha = res.json().get("sha")
    elif res.status_code == 401:
        return "ERROR: GitHub token is INVALID or EXPIRED (401)"
    elif res.status_code == 404:
        # Если файла нет, это нормально для первой записи, но проверим токен
        pass

    base64_content = base64.b64encode(content_text.encode('utf-8')).decode('utf-8')
    
    data = {
        "message": "VRChat Bot: Update short URL",
        "content": base64_content
    }
    if sha:
        data["sha"] = sha

    put_res = requests.put(url, headers=headers, json=data)
    
    if put_res.status_code in [200, 201]:
        return "SUCCESS: File updated on GitHub!"
    else:
        return f"ERROR: GitHub rejected update. Code: {put_res.status_code}, Response: {put_res.text}"

@app.route('/')
def home():
    return "Server is running!"

@app.route('/shorts')
def get_random_short():
    random_query = random.choice(SEARCH_QUERIES)
    search_url = f"https://www.youtube.com/results?search_query={random_query}&sp=EgIYAQ%253D%253D"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    video_id = "R98yY1Ww_6A"
    try:
        response = requests.get(search_url, headers=headers, timeout=5)
        video_ids = re.findall(r'"videoId":"([^"]+)"', response.text)
        if video_ids:
            unique_ids = [v for v in list(set(video_ids)) if len(v) == 11]
            if unique_ids:
                video_id = random.choice(unique_ids)
    except Exception as e:
        return f"ERROR: YouTube parse failed: {str(e)}"
        
    full_youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Получаем детальный статус отправки на Гитхаб
    github_status = update_github_file(full_youtube_url)
        
    return Response(f"Link: {full_youtube_url} | Status: {github_status}", mimetype='text/plain')

if __name__ == "__main__":
    app.run()
