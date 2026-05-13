from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import threading
from datetime import datetime, timedelta
import re

app = Flask(__name__)
CORS(app)

TEMP_DIR = '/tmp/youtube_downloads'
os.makedirs(TEMP_DIR, exist_ok=True)

def is_valid_youtube_url(url):
    youtube_regex = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
    return re.match(youtube_regex, url) is not None

def cleanup_old_files():
    try:
        now = datetime.now()
        for filename in os.listdir(TEMP_DIR):
            filepath = os.path.join(TEMP_DIR, filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if now - file_modified > timedelta(hours=1):
                os.remove(filepath)
    except Exception as e:
        print(f"Cleanup error: {e}")

def start_cleanup_thread():
    thread = threading.Thread(target=cleanup_old_files, daemon=True)
    thread.start()

@app.route('/api/convert', methods=['POST'])
def convert():
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        format_type = data.get('format', 'mp3').lower()

        # Validate input
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        if not is_valid_youtube_url(url):
            return jsonify({'error': 'Invalid YouTube URL'}), 400

        if format_type not in ['mp3', 'mp4']:
            return jsonify({'error': 'Invalid format. Use mp3 or mp4'}), 400

        # Set up yt-dlp options
        timestamp = int(datetime.now().timestamp() * 1000)
        output_template = os.path.join(TEMP_DIR, f'{timestamp}-%(title)s.%(ext)s')

        ydl_opts = {
            'quiet': False,
            'no_warnings': False,
            'outtmpl': output_template,
            'socket_timeout': 30,
            'default_search': 'auto',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        }

        if format_type == 'mp3':
            # Download best audio and convert to mp3
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:  # mp4
            # Download best video with audio
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

        print(f"Converting: {url} to {format_type}")
        print(f"Options: {ydl_opts}")

        # Download and convert
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        # Find the actual file (mp3 or mp4)
        base_name = os.path.splitext(filename)[0]
        
        if format_type == 'mp3':
            file_path = base_name + '.mp3'
        else:
            file_path = base_name + '.mp4'

        print(f"Looking for file: {file_path}")

        # If file doesn't exist with expected extension, search for it
        if not os.path.exists(file_path):
            # Search in temp dir for recently created files
            files = sorted(
                os.listdir(TEMP_DIR),
                key=lambda x: os.path.getctime(os.path.join(TEMP_DIR, x)),
                reverse=True
            )
            
            for f in files[:5]:  # Check last 5 files
                full_path = os.path.join(TEMP_DIR, f)
                if f.startswith(str(timestamp)) and (f.endswith('.mp3') or f.endswith('.mp4')):
                    file_path = full_path
                    break

        if os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            base_filename = os.path.basename(file_path)

            return jsonify({
                'success': True,
                'filename': base_filename,
                'fileSize': f'{file_size_mb:.2f} MB',
                'downloadUrl': f'/api/download/{base_filename}'
            }), 200
        else:
            print(f"File not found: {file_path}")
            print(f"Files in temp dir: {os.listdir(TEMP_DIR)}")
            return jsonify({'error': 'File not found after conversion'}), 500

    except Exception as e:
        error_msg = str(e)
        print(f"Error occurred: {error_msg}")
        
        if 'unavailable' in error_msg.lower():
            return jsonify({'error': 'Video is unavailable or restricted'}), 400
        if 'private' in error_msg.lower():
            return jsonify({'error': 'Video is private'}), 400
        if 'age' in error_msg.lower():
            return jsonify({'error': 'Video is age-restricted'}), 400
        if 'not available' in error_msg.lower():
            return jsonify({'error': 'Video format not available. Try another video'}), 400
        
        return jsonify({'error': f'Conversion failed: {error_msg}'}), 500

@app.route('/api/download/<filename>', methods=['GET'])
def download(filename):
    try:
        safe_filename = os.path.basename(filename)
        filepath = os.path.join(TEMP_DIR, safe_filename)

        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        if safe_filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'video/mp4'

        return send_file(
            filepath,
            mimetype=mimetype,
            as_attachment=True,
            download_name=safe_filename
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/', methods=['GET'])
def index():
    return jsonify({'message': 'YouTube Converter API', 'version': '1.0'}), 200

if __name__ == '__main__':
    start_cleanup_thread()
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))