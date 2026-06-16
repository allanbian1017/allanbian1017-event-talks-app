import os
import time
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Cache configuration
FEED_URL = "https://docs.cloud.google.com/feeds/bigquery-release-notes.xml"
cache = {
    "data": None,
    "last_fetched": 0,
    "expiry_seconds": 300  # 5 minutes cache
}

def clean_text(html_content):
    """Extracts plain text from HTML, collapses whitespace, and returns it."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text()
    # Collapse whitespace
    return " ".join(text.split())

def fetch_and_parse_feed():
    """Fetches the BigQuery Atom feed and parses it into structured updates."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(FEED_URL, headers=headers, timeout=15)
    response.raise_for_status()
    
    root = ET.fromstring(response.content)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
        
    entries = root.findall(f"{ns}entry")
    all_updates = []
    
    for entry_idx, entry in enumerate(entries):
        title_el = entry.find(f"{ns}title")
        date_str = title_el.text if title_el is not None else "Unknown Date"
        
        updated_el = entry.find(f"{ns}updated")
        updated_val = updated_el.text if updated_el is not None else ""
        
        link_el = entry.find(f"{ns}link")
        base_link = link_el.attrib.get('href', '') if link_el is not None else ""
        
        content_el = entry.find(f"{ns}content")
        content_html = content_el.text if content_el is not None else ""
        
        if not content_html:
            continue
            
        soup = BeautifulSoup(content_html, 'html.parser')
        entry_updates = []
        current_type = None
        current_content = []
        
        # Parse individual updates by splitting on <h3> headings
        children = list(soup.find_all(recursive=False))
        
        # If there are no children tags directly inside, wrap content and parse
        if not children and soup.get_text().strip():
            entry_updates.append({
                "category": "Update",
                "html": str(soup)
            })
        else:
            for child in children:
                if child.name == 'h3':
                    if current_type is not None:
                        entry_updates.append({
                            "category": current_type,
                            "html": "".join(str(c) for c in current_content).strip()
                        })
                    current_type = child.get_text().strip()
                    current_content = []
                else:
                    current_content.append(child)
            
            if current_type is not None:
                entry_updates.append({
                    "category": current_type,
                    "html": "".join(str(c) for c in current_content).strip()
                })
        
        # Fallback if parsing failed to extract updates
        if not entry_updates:
            entry_updates.append({
                "category": "Update",
                "html": content_html.strip()
            })
            
        # Compile entries with unique IDs
        for update_idx, up in enumerate(entry_updates):
            html_content = up["html"]
            plain_text = clean_text(html_content)
            
            # Format update type/category
            category = up["category"]
            
            # Create a unique ID for referencing/selecting
            update_id = f"bq-{entry_idx}-{update_idx}"
            
            all_updates.append({
                "id": update_id,
                "date": date_str,
                "updated_raw": updated_val,
                "category": category,
                "html": html_content,
                "text": plain_text,
                "link": base_link
            })
            
    return all_updates

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/release-notes')
def get_release_notes():
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    now = time.time()
    
    if force_refresh or cache["data"] is None or (now - cache["last_fetched"]) > cache["expiry_seconds"]:
        try:
            updates = fetch_and_parse_feed()
            cache["data"] = updates
            cache["last_fetched"] = now
            return jsonify({
                "success": True,
                "source": "network" if force_refresh or (now - cache["last_fetched"]) == 0 else "network_auto",
                "last_fetched": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cache["last_fetched"])),
                "updates": updates
            })
        except Exception as e:
            # If fetch fails but we have cached data, fall back to cache
            if cache["data"] is not None:
                return jsonify({
                    "success": True,
                    "source": "cache_fallback",
                    "last_fetched": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cache["last_fetched"])),
                    "updates": cache["data"],
                    "error_message": str(e)
                })
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    else:
        return jsonify({
            "success": True,
            "source": "cache",
            "last_fetched": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cache["last_fetched"])),
            "updates": cache["data"]
        })

if __name__ == '__main__':
    # Run on port 5001 by default (5000 is used by AirPlay on macOS)
    app.run(host='0.0.0.0', port=5001, debug=True)
