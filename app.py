from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import yt_dlp
import os
import tempfile
import uuid
import subprocess
import sys
import logging
import re
import shutil
import requests
import zipfile
import io
import json
from datetime import datetime
from urllib.parse import urlparse
import time

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create issues directory if it doesn't exist
ISSUES_DIR = 'issues'
if not os.path.exists(ISSUES_DIR):
    os.makedirs(ISSUES_DIR)

# Configure port for production
port = int(os.environ.get("PORT", 5000))

def sanitize_filename(filename):
    logger.debug(f"Original filename: {filename}")
    
    # Remove any existing extension
    filename = re.sub(r'\.[^.]+$', '', filename)
    logger.debug(f"After removing extension: {filename}")
    
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    logger.debug(f"After removing invalid chars: {filename}")
    
    # Replace special characters with spaces
    filename = re.sub(r'[^\w\s-]', ' ', filename)
    logger.debug(f"After replacing special chars: {filename}")
    
    # Replace multiple spaces with single space
    filename = re.sub(r'\s+', ' ', filename)
    logger.debug(f"After replacing multiple spaces: {filename}")
    
    # Remove leading/trailing spaces and underscores
    filename = filename.strip(' _')
    logger.debug(f"After stripping: {filename}")
    
    # If filename is empty after cleaning, use a default name
    if not filename:
        filename = 'youtube_video'
    
    # Limit length to 100 characters
    filename = filename[:100]
    logger.debug(f"After length limit: {filename}")
    
    # Remove any trailing spaces or underscores again
    filename = filename.rstrip(' _')
    logger.debug(f"Final cleaned filename: {filename}")
    
    return filename

def update_ytdlp():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        return True
    except subprocess.CalledProcessError:
        return False

def install_ffmpeg():
    """Download and install ffmpeg on Windows"""
    try:
        # Create ffmpeg directory in the current working directory
        ffmpeg_dir = os.path.join(os.getcwd(), 'ffmpeg')
        os.makedirs(ffmpeg_dir, exist_ok=True)
        
        # Download ffmpeg
        logger.info("Downloading ffmpeg...")
        url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        response = requests.get(url)
        response.raise_for_status()
        
        # Extract the zip file
        logger.info("Extracting ffmpeg...")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
            zip_ref.extractall(ffmpeg_dir)
        
        # Find the extracted ffmpeg.exe
        for root, dirs, files in os.walk(ffmpeg_dir):
            if 'ffmpeg.exe' in files:
                ffmpeg_path = os.path.join(root, 'ffmpeg.exe')
                # Copy ffmpeg.exe to the current directory
                shutil.copy2(ffmpeg_path, os.getcwd())
                logger.info("ffmpeg installed successfully!")
                return True
        
        logger.error("Could not find ffmpeg.exe in the downloaded files")
        return False
        
    except Exception as e:
        logger.error(f"Failed to install ffmpeg: {str(e)}")
        return False

def check_ffmpeg():
    """Check if ffmpeg is installed"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("ffmpeg not found. Please ensure ffmpeg is installed on the system.")
        return False

def debug_formats(url):
    """Debug function to list available formats"""
    try:
        with yt_dlp.YoutubeDL({'listformats': True, 'quiet': False}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error debugging formats: {e}")
        return None

class MyLogger:
    def debug(self, msg):
        logger.debug(msg)
    def warning(self, msg):
        logger.warning(msg)
    def error(self, msg):
        logger.error(msg)

@app.route('/')
def index():
    return render_template('index.html')

def get_platform_specific_options(url):
    """Get platform-specific yt-dlp options"""
    options = {
        'format': 'bestvideo[height<=2160][ext=mp4][vcodec!*=av01]+bestaudio[ext=m4a]/bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]/best',
        'referer': 'https://www.youtube.com/',
        'extract_flat': False,
        'quiet': False,
        'no_warnings': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'no_color': True,
        'extractor_retries': 5,
        'socket_timeout': 60,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'keepvideo': False,
        'writethumbnail': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'geo_bypass': True,
        'geo_verification_proxy': None,
        'postprocessors': [
            {
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            },
            {
                'key': 'FFmpegMetadata',
            }
        ],
        'logger': MyLogger(),
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
        }
    }

    # Platform-specific configurations
    if 'tiktok.com' in url:
        options.update({
            'format': 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]/best',
            'referer': 'https://www.tiktok.com/',
            'geo_bypass': True,
            'geo_verification_proxy': None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://www.tiktok.com/',
            },
            'extractor_args': {
                'tiktok': {
                    'api_hostname': 'api16-normal-c-useast1a.tiktokv.com',
                    'app_version': '20.2.1',
                    'device_id': '1',
                    'manifest_app_version': '20.2.1',
                    'openudid': '1',
                    'os_version': '10',
                    'resolution': '1080*1920',
                    'sys_region': 'US',
                    'timezone_name': 'America/New_York',
                }
            }
        })
    elif 'youtube.com' in url or 'youtu.be' in url:
        options.update({
            'format': 'bestvideo[height<=2160][ext=mp4][vcodec!*=av01]+bestaudio[ext=m4a]/bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]/best',
            'referer': 'https://www.youtube.com/',
            'geo_bypass': True,
            'geo_verification_proxy': None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://www.youtube.com/',
                'Origin': 'https://www.youtube.com',
            },
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls'],
                    'player_client': ['android', 'web'],
                    'player_skip': ['js', 'configs', 'webpage'],
                    'player_params': {
                        'hl': 'en',
                        'gl': 'US',
                    }
                }
            }
        })
    elif 'instagram.com' in url:
        options.update({
            'format': 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]/best',
            'referer': 'https://www.instagram.com/',
            'extract_flat': False,
            'noplaylist': True,
            'extract_flat_playlist': False,
            'geo_bypass': True,
            'geo_verification_proxy': None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://www.instagram.com/',
                'Origin': 'https://www.instagram.com',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'X-IG-App-ID': '936619743392459',
                'X-ASBD-ID': '198387',
                'X-IG-WWW-Claim': '0',
            },
            'extractor_args': {
                'instagram': {
                    'login': None,
                    'password': None,
                    'client_id': '936619743392459',
                    'client_secret': '1c2d3e4f5g6h7i8j9k0l',
                    'extract_flat': False,
                    'extract_flat_playlist': False,
                    'skip': ['dash', 'hls'],
                    'player_client': ['android', 'web'],
                    'player_skip': ['js', 'configs', 'webpage'],
                    'player_params': {
                        'hl': 'en',
                        'gl': 'US',
                    }
                }
            }
        })
    elif 'twitter.com' in url or 'x.com' in url:
        options.update({
            'format': 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]/best',
            'referer': 'https://twitter.com/',
            'geo_bypass': True,
            'geo_verification_proxy': None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://twitter.com/',
            }
        })

    return options

@app.route('/download', methods=['POST'])
def download_video():
    temp_dir = None
    try:
        # Check for ffmpeg first
        if not check_ffmpeg():
            return jsonify({'error': 'ffmpeg is required but not installed. Please install ffmpeg manually.'}), 500

        url = request.form.get('url', '').strip()
        if not url:
            return jsonify({'error': 'Please provide a URL'}), 400

        logger.info(f"Attempting to download video from URL: {url}")

        # Create a temporary directory for downloads
        temp_dir = tempfile.mkdtemp()
        logger.debug(f"Created temp directory: {temp_dir}")
        
        # Get platform-specific options
        ydl_opts = get_platform_specific_options(url)
        ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(id)s.%(ext)s')
        
        # Add additional options for better reliability
        ydl_opts.update({
            'socket_timeout': 120,  # Increased timeout
            'retries': 20,          # More retries
            'fragment_retries': 20, # More fragment retries
            'extractor_retries': 10,
            'skip_unavailable_fragments': True,
            'ignoreerrors': True,   # Continue on errors
            'no_warnings': True,    # Reduce noise
            'quiet': True,          # Reduce noise
            'nocheckcertificate': True,
            'geo_bypass': True,
            'geo_verification_proxy': None,
        })

        # Add specific headers for better success rate
        ydl_opts['http_headers'].update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # Get video info first with retries
                max_retries = 3
                info = None
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Extracting video information (attempt {attempt + 1}/{max_retries})...")
                        info = ydl.extract_info(url, download=False)
                        if info:
                            break
                    except Exception as e:
                        last_error = e
                        logger.warning(f"Extraction attempt {attempt + 1} failed: {str(e)}")
                        if attempt < max_retries - 1:
                            time.sleep(2)  # Wait before retrying
                
                if not info:
                    error_msg = str(last_error) if last_error else "Unknown error"
                    logger.error(f"Failed to extract video information after {max_retries} attempts: {error_msg}")
                    return jsonify({'error': f'Could not extract video information: {error_msg}'}), 400
                
                if not isinstance(info, dict):
                    logger.error(f"Info object is not a dictionary, got: {type(info)}")
                    return jsonify({'error': 'Invalid video information format'}), 400

                # Debug available formats
                if 'formats' in info:
                    # Log available formats
                    formats = info['formats']
                    logger.info(f"Available formats: {len(formats)}")
                    for fmt in formats[:5]:  # Log first 5 formats
                        logger.info(f"Format: {fmt.get('format_id')} - {fmt.get('ext')} - {fmt.get('resolution')} - {fmt.get('vcodec')} - {fmt.get('acodec')}")

                # Extract basic video information safely
                video_id = info.get('id', str(uuid.uuid4())[:8])
                
                # Try to get the caption/description first, fall back to title if not available
                raw_caption = info.get('description', '') or info.get('caption', '') or info.get('title', f'video_{video_id}')
                
                # Clean up the caption more aggressively
                video_caption = sanitize_filename(raw_caption)
                if not video_caption:
                    video_caption = f'video_{video_id}'
                
                logger.info(f"Raw caption: {raw_caption}")
                logger.info(f"Cleaned caption: {video_caption}")
                logger.info(f"Video ID: {video_id}")
                
                # Download the video with retries
                max_retries = 3
                download_info = None
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Starting video download (attempt {attempt + 1}/{max_retries})...")
                        with yt_dlp.YoutubeDL(ydl_opts) as download_ydl:
                            download_info = download_ydl.extract_info(url, download=True)
                        if download_info:
                            break
                    except Exception as e:
                        last_error = e
                        logger.warning(f"Download attempt {attempt + 1} failed: {str(e)}")
                        if attempt < max_retries - 1:
                            time.sleep(2)  # Wait before retrying
                
                if not download_info:
                    error_msg = str(last_error) if last_error else "Unknown error"
                    logger.error(f"Failed to download video after {max_retries} attempts: {error_msg}")
                    return jsonify({'error': f'Failed to download video: {error_msg}'}), 500

                # Find the downloaded file
                downloaded_files = [f for f in os.listdir(temp_dir) 
                                  if os.path.isfile(os.path.join(temp_dir, f)) and (f.endswith('.mp4') or f.endswith('.m4v') or f.endswith('.mov'))]
                
                if not downloaded_files:
                    logger.error(f"No downloaded files found in {temp_dir}")
                    all_files = os.listdir(temp_dir)
                    logger.error(f"All files in temp dir: {all_files}")
                    
                    # For Instagram, try to find any video file
                    if 'instagram.com' in url:
                        all_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                        logger.info(f"All files in temp dir for Instagram: {all_files}")
                        if all_files:
                            downloaded_file_path = os.path.join(temp_dir, all_files[0])
                            logger.info(f"Using first available file: {all_files[0]}")
                        else:
                            return jsonify({'error': 'Video downloaded but file not found. The post might be private or not contain a video.'}), 500
                    else:
                        return jsonify({'error': 'Video downloaded but file not found'}), 500
                else:
                    # Get the downloaded file
                    downloaded_file_path = os.path.join(temp_dir, downloaded_files[0])
                    logger.info(f"Using file: {downloaded_files[0]}")
                
                # Verify the file has audio streams
                try:
                    ffprobe_cmd = ['ffprobe', '-v', 'quiet', '-show_streams', '-select_streams', 'a', downloaded_file_path]
                    result = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
                    if result.returncode == 0 and result.stdout.strip():
                        logger.info("Audio stream detected in downloaded file")
                    else:
                        logger.warning("No audio stream detected in downloaded file")
                except Exception as e:
                    logger.warning(f"Could not verify audio stream: {e}")
                
                # Create a response with the file
                response = send_file(
                    downloaded_file_path,
                    as_attachment=True,
                    download_name=f"{video_caption}.mp4",
                    mimetype='video/mp4'
                )
                
                # Set the Content-Disposition header directly
                safe_filename = f"{video_caption}.mp4".replace('"', '\\"')  # Escape quotes
                response.headers['Content-Disposition'] = f'attachment; filename="{safe_filename}"; filename*=UTF-8\'\'{safe_filename}'
                
                # Add cleanup callback to the response
                @response.call_on_close
                def cleanup():
                    try:
                        if temp_dir and os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir)
                            logger.info(f"Cleaned up temporary directory: {temp_dir}")
                    except Exception as e:
                        logger.warning(f"Failed to clean up temp directory: {e}")
                
                return response

            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                logger.error(f"yt-dlp Download error: {error_msg}")
                
                # Check for specific errors
                if "Unable to download API page" in error_msg:
                    return jsonify({'error': 'API access failed. The video might be region-blocked or private.'}), 400
                elif "getaddrinfo failed" in error_msg:
                    return jsonify({'error': 'Network connection error. Please check your internet connection.'}), 500
                elif "Private video" in error_msg:
                    return jsonify({'error': 'This video is private and cannot be downloaded.'}), 400
                elif "Video unavailable" in error_msg:
                    return jsonify({'error': 'This video is unavailable or has been removed.'}), 400
                else:
                    return jsonify({'error': f'Download failed: {error_msg}'}), 500
                    
            except Exception as e:
                logger.error(f"Unexpected error during download: {str(e)}")
                return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

    except Exception as e:
        logger.error(f"Top-level error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Video downloader is running'})

@app.route('/debug-formats', methods=['POST'])
def debug_video_formats():
    """Debug endpoint to check available formats for a URL"""
    try:
        url = request.form.get('url', '').strip()
        if not url:
            return jsonify({'error': 'Please provide a URL'}), 400
        
        info = debug_formats(url)
        if info and 'formats' in info:
            formats = []
            for fmt in info['formats']:
                formats.append({
                    'format_id': fmt.get('format_id'),
                    'ext': fmt.get('ext'),
                    'resolution': fmt.get('resolution'),
                    'vcodec': fmt.get('vcodec'),
                    'acodec': fmt.get('acodec'),
                    'filesize': fmt.get('filesize'),
                    'tbr': fmt.get('tbr')
                })
            return jsonify({'formats': formats})
        else:
            return jsonify({'error': 'Could not extract format information'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Debug error: {str(e)}'}), 500

@app.route('/report-issue', methods=['POST'])
def report_issue():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['type', 'url', 'description']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Create issue object
        issue = {
            'id': datetime.now().strftime('%Y%m%d%H%M%S'),
            'timestamp': datetime.now().isoformat(),
            'type': data['type'],
            'url': data['url'],
            'description': data['description'],
            'status': 'new'
        }
        
        # Save issue to JSON file
        issue_file = os.path.join(ISSUES_DIR, f'issue_{issue["id"]}.json')
        with open(issue_file, 'w') as f:
            json.dump(issue, f, indent=2)
        
        logger.info(f'New issue reported: {issue["id"]}')
        return jsonify({'message': 'Issue reported successfully', 'id': issue['id']}), 200
        
    except Exception as e:
        logger.error(f'Error reporting issue: {str(e)}')
        return jsonify({'error': 'Failed to report issue'}), 500

@app.route('/ads.txt')
def ads_txt():
    return send_from_directory('static', 'ads.txt')

if __name__ == '__main__':
    # Check for ffmpeg before starting the app
    if not check_ffmpeg():
        logger.error("FFmpeg is not installed. The application may not function correctly.")
    app.run(host='0.0.0.0', port=port)