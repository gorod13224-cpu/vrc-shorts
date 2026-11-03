import random

from flask import Flask, abort, jsonify, redirect, request

from catalog import CATALOG_VERSION, load_registry_document
from refresh_catalog import load_config


app = Flask(__name__)
def build_topic_catalog(document, topics):
    return [
        {"id": topic.id, "name": topic.name,
         "clips": [slot for slot, clip in enumerate(document["clips"])
                   if topic.id in document.get("clip_topics", {}).get(clip, [])]}
        for topic in topics
    ]


REGISTRY = load_registry_document()
CLIP_IDS = tuple(REGISTRY["clips"])
TOPIC_CATALOG = build_topic_catalog(REGISTRY, load_config().topics)


@app.after_request
def prevent_feed_caching(response):
    if request.path in ("/catalog.json", "/shorts") or request.path.startswith("/clip/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.route('/catalog.json')
def catalog():
    return jsonify(version=CATALOG_VERSION, count=len(CLIP_IDS), topics=TOPIC_CATALOG)


@app.route('/clip/<int:slot>')
def clip(slot):
    if slot >= len(CLIP_IDS):
        abort(404)
    return redirect(f"https://www.youtube.com/watch?v={CLIP_IDS[slot]}", code=302)


@app.route('/')
def home():
    return "VRCShorts server is running."


@app.route('/shorts')
def get_random_short():
    # Old worlds keep their URL and redirect contract without doing upstream searches.
    if not CLIP_IDS:
        abort(503)
    return redirect(f"https://www.youtube.com/watch?v={random.choice(CLIP_IDS)}", code=302)


if __name__ == "__main__":
    app.run()
