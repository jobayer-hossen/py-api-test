from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from pytube import YouTube
from pytube.exceptions import PytubeError
import subprocess
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
            try:
                file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
                if now - file_modified > timedelta(hours=1):
                    os.remove(filepath)
                    print(f"Deleted old file: {filename}")
            except:
                pass
    except Exception as e:
        print(f"Cleanup error: {e}")

def start_cleanup_thread():
    thread = threading.Thread(target=cleanup_old_files, daemon=True)
    thread.start()

def convert_to_mp3(input_path, output_path):
    """Convert MP4 to MP3 using ffmpeg"""
    try:
        command = [
            'ffmpeg',
            '-i', input_path,
            '-q:a', '9',
            '-n',  # Don't overwrite
            output_path
        ]
        subprocess.run(command, check=True, capture_output=True)
        return True
    except Exception as e:
        print(f"FFmpeg error: {e}")
        return False

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
            return jsonify({'error': 'Invalid format'}), 400

        print(f"Converting: {url} to {format_type}")

        try:
            # Create YouTube object
            yt = YouTube(url)
            print(f"Title: {yt.title}")
            print(f"Duration: {yt.length}s")

            # Check if video is too long (>1 hour for free tier)
            if yt.length > 3600:
                return jsonify({
                    'error': 'Video is too long (max 1 hour). Please use a shorter video.'
                }), 400

            timestamp = int(datetime.now().timestamp() * 1000)
            safe_title = re.sub(r'[^\w\s-]', '', yt.title)[:50]
            
            if format_type == 'mp4':
                # Download highest quality video
                stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
                
                if not stream:
                    # Try non-progressive
                    stream = yt.streams.filter(file_extension='mp4').first()
                
                if not stream:
                    return jsonify({'error': 'No video stream available'}), 400

                filename = f"{timestamp}-{safe_title}.mp4"
                filepath = os.path.join(TEMP_DIR, filename)
                
                print(f"Downloading video: {stream.resolution}")
                stream.download(output_path=TEMP_DIR, filename=filename)
                
            else:  # mp3
                # Download best audio
                stream = yt.streams.filter(only_audio=True).first()
                
                if not stream:
                    return jsonify({'error': 'No audio stream available'}), 400

                filename = f"{timestamp}-{safe_title}.mp4"
                filepath = os.path.join(TEMP_DIR, filename)
                
                print(f"Downloading audio")
                stream.download(output_path=TEMP_DIR, filename=filename)
                
                # Convert to MP3
                mp3_filename = f"{timestamp}-{safe_title}.mp3"
                mp3_filepath = os.path.join(TEMP_DIR, mp3_filename)
                
                print(f"Converting to MP3")
                if convert_to_mp3(filepath, mp3_filepath):
                    os.remove(filepath)  # Remove original mp4
                    filename = mp3_filename
                    filepath = mp3_filepath
                else:
                    return jsonify({'error': 'Failed to convert to MP3'}), 500

            # Check if file exists
            if not os.path.exists(filepath):
                return jsonify({'error': 'Download failed. Try again.'}), 500

            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"Success! File size: {file_size_mb:.2f} MB")

            return jsonify({
                'success': True,
                'filename': filename,
                'fileSize': f'{file_size_mb:.2f} MB',
                'downloadUrl': f'/api/download/{filename}'
            }), 200

        except PytubeError as e:
            error_msg = str(e).lower()
            print(f"PyTube error: {e}")
            
            if 'age' in error_msg or 'restricted' in error_msg:
                return jsonify({'error': 'Video is age-restricted'}), 400
            elif 'private' in error_msg:
                return jsonify({'error': 'Video is private'}), 400
            elif 'unavailable' in error_msg:
                return jsonify({'error': 'Video is unavailable'}), 400
            else:
                return jsonify({'error': f'Cannot process this video. Try another.'}), 400

    except Exception as e:
        error_msg = str(e)
        print(f"Error: {error_msg}")
        return jsonify({'error': 'Server error. Please try again later.'}), 500

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
        print(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'message': 'YouTube Converter API',
        'version': '1.0',
        'status': 'running'
    }), 200

if __name__ == '__main__':
    start_cleanup_thread()
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))