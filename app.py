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
import threading

app = Flask(__name__)

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        # Force update to latest version with longer timeout
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "--upgrade", "--force-reinstall", "yt-dlp"
        ], timeout=300)  # 5 minute timeout
        
        # Verify version
        import yt_dlp
        logger.info(f"yt-dlp version: {yt_dlp.version.__version__}")
        
        # Check if version is recent enough (2024.03.10 or newer)
        version_parts = yt_dlp.version.__version__.split('.')
        if len(version_parts) >= 3:
            year = int(version_parts[0])
            month = int(version_parts[1])
            if year < 2024 or (year == 2024 and month < 3):
                logger.warning("yt-dlp version is older than 2024.03.10, which may affect downloads")
        
        return True
    except subprocess.TimeoutExpired:
        logger.error("yt-dlp update timed out")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to update yt-dlp: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error checking yt-dlp version: {str(e)}")
        return False

def check_ffmpeg():
    """Check if ffmpeg is installed with better error handling"""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'], 
            capture_output=True, 
            check=True, 
            timeout=30
        )
        logger.info("ffmpeg is available")
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg check timed out")
        return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"ffmpeg not found: {e}")
        return False

class MyLogger:
    def debug(self, msg):
        logger.debug(f"yt-dlp: {msg}")
    def warning(self, msg):
        logger.warning(f"yt-dlp: {msg}")
    def error(self, msg):
        logger.error(f"yt-dlp: {msg}")

@app.route('/')
def index():
    return render_template('index.html')

def get_platform_specific_options(url):
    """Get platform-specific yt-dlp options with production fixes"""
    
    # Base options with production-friendly settings
    options = {
        'format': 'best[height<=1080]/best',
        'extract_flat': False,
        'quiet': True,
        'no_warnings': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'no_color': True,
        'extractor_retries': 5,  # Increased retries
        'socket_timeout': 60,    # Increased timeout
        'retries': 10,           # Increased retries
        'fragment_retries': 10,  # Increased retries
        'skip_unavailable_fragments': True,
        'keepvideo': False,
        'writethumbnail': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'logger': MyLogger(),
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        }
    }

    # Platform-specific configurations
    if 'youtube.com' in url or 'youtu.be' in url:
        if '/shorts/' in url:
            options.update({
                'format': 'best[height<=1080]/best',
                'referer': 'https://www.youtube.com/shorts/',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                    'Referer': 'https://www.youtube.com/shorts/',
                    'Origin': 'https://www.youtube.com',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-User': '?1'
                },
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['web'],
                        'player_skip': ['js', 'configs', 'webpage'],
                        'player_params': {
                            'hl': 'en',
                            'gl': 'US',
                        }
                    }
                }
            })
        else:
            options.update({
                'format': 'best[height<=1080]/best',
                'referer': 'https://www.youtube.com/',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate',
                    'Referer': 'https://www.youtube.com/',
                    'Origin': 'https://www.youtube.com',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-User': '?1'
                },
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['web'],
                        'player_skip': ['js', 'configs', 'webpage'],
                        'player_params': {
                            'hl': 'en',
                            'gl': 'US',
                        }
                    }
                }
            })
    elif 'tiktok.com' in url:
        options.update({
            'format': 'best[height<=720]/best',
            'referer': 'https://www.tiktok.com/',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://www.tiktok.com/',
                'Origin': 'https://www.tiktok.com',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1'
            }
        })
    elif 'instagram.com' in url:
        options.update({
            'format': 'best[height<=720]/best',
            'referer': 'https://www.instagram.com/',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://www.instagram.com/',
                'Origin': 'https://www.instagram.com',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1'
            }
        })
    elif 'twitter.com' in url or 'x.com' in url:
        options.update({
            'format': 'best[height<=720]/best',
            'referer': 'https://twitter.com/',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Referer': 'https://twitter.com/',
                'Origin': 'https://twitter.com',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1'
            }
        })

    return options

def cleanup_temp_dir(temp_dir, delay=300):
    """Cleanup temp directory after delay"""
    def cleanup():
        time.sleep(delay)  # Wait 5 minutes
        try:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to clean up temp directory: {e}")
    
    # Run cleanup in background thread
    threading.Thread(target=cleanup, daemon=True).start()

@app.route('/download', methods=['POST'])
def download_video():
    temp_dir = None
    try:
        # Check for ffmpeg first
        if not check_ffmpeg():
            logger.error("ffmpeg not available")
            return jsonify({'error': 'Video processing unavailable. Please try again later.'}), 500

        url = request.form.get('url', '').strip()
        if not url:
            return jsonify({'error': 'Please provide a URL'}), 400

        logger.info(f"Processing download request for: {url}")

        # Create a temporary directory for downloads
        temp_dir = tempfile.mkdtemp(prefix='video_dl_')
        logger.info(f"Created temp directory: {temp_dir}")
        
        # Get platform-specific options
        ydl_opts = get_platform_specific_options(url)
        ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title).50s.%(ext)s')
        
        # Add a small delay before starting the download
        time.sleep(2)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                logger.info("Extracting video information...")
                
                # Add retry logic for info extraction
                max_retries = 3
                retry_delay = 5
                
                for attempt in range(max_retries):
                    try:
                        info = ydl.extract_info(url, download=False)
                        if info:
                            break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            raise e
                
                if not info:
                    return jsonify({'error': 'Video information could not be extracted'}), 400

                # Extract video information
                video_id = info.get('id', str(uuid.uuid4())[:8])
                raw_title = info.get('title', '') or info.get('description', '')[:50] or f'video_{video_id}'
                video_title = sanitize_filename(raw_title)
                
                logger.info(f"Video title: {video_title}")
                
                # Add a small delay before downloading
                time.sleep(2)
                
                # Download the video
                logger.info("Starting video download...")
                try:
                    download_info = ydl.extract_info(url, download=True)
                except Exception as e:
                    logger.error(f"Download failed: {str(e)}")
                    return jsonify({'error': 'Download failed. The video may be too large or unavailable.'}), 500

                # Find the downloaded file
                downloaded_files = []
                for f in os.listdir(temp_dir):
                    if os.path.isfile(os.path.join(temp_dir, f)):
                        downloaded_files.append(f)
                
                if not downloaded_files:
                    logger.error("No files downloaded")
                    return jsonify({'error': 'Download completed but no file found'}), 500

                # Get the first (and likely only) downloaded file
                downloaded_file_path = os.path.join(temp_dir, downloaded_files[0])
                
                # Check file size (limit to 100MB for production)
                file_size = os.path.getsize(downloaded_file_path)
                max_size = 100 * 1024 * 1024  # 100MB
                if file_size > max_size:
                    logger.warning(f"File too large: {file_size} bytes")
                    return jsonify({'error': 'Video file is too large for download (max 100MB)'}), 413

                logger.info(f"Sending file: {downloaded_files[0]} ({file_size} bytes)")
                
                # Create response
                response = send_file(
                    downloaded_file_path,
                    as_attachment=True,
                    download_name=f"{video_title}.mp4",
                    mimetype='video/mp4'
                )
                
                # Schedule cleanup (don't use @response.call_on_close in production)
                cleanup_temp_dir(temp_dir, delay=60)  # Cleanup after 1 minute
                
                return response

            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                logger.error(f"yt-dlp error: {error_msg}")
                
                # Enhanced error handling for different platforms
                if 'youtube.com' in url or 'youtu.be' in url:
                    if '/shorts/' in url:
                        if 'Video unavailable' in error_msg or "content isn't available" in error_msg:
                            return jsonify({'error': 'This YouTube Short is unavailable. It may have been removed or made private.'}), 400
                        elif 'Private video' in error_msg:
                            return jsonify({'error': 'This YouTube Short is private and cannot be downloaded.'}), 400
                        elif 'Sign in' in error_msg:
                            return jsonify({'error': 'This YouTube Short requires sign in to access.'}), 400
                        elif 'age-restricted' in error_msg.lower():
                            return jsonify({'error': 'This YouTube Short is age-restricted and cannot be downloaded.'}), 400
                        elif 'copyright' in error_msg.lower():
                            return jsonify({'error': 'This YouTube Short is not available due to copyright restrictions.'}), 400
                        elif 'region' in error_msg.lower():
                            return jsonify({'error': 'This YouTube Short is not available in your region.'}), 400
                    else:
                        if 'Video unavailable' in error_msg:
                            return jsonify({'error': 'This video is unavailable. It may have been removed or made private.'}), 400
                        elif 'Private video' in error_msg:
                            return jsonify({'error': 'This video is private and cannot be downloaded.'}), 400
                        elif 'Sign in' in error_msg:
                            return jsonify({'error': 'This video requires sign in to access.'}), 400
                        elif 'age-restricted' in error_msg.lower():
                            return jsonify({'error': 'This video is age-restricted and cannot be downloaded.'}), 400
                        elif 'copyright' in error_msg.lower():
                            return jsonify({'error': 'This video is not available due to copyright restrictions.'}), 400
                        elif 'region' in error_msg.lower():
                            return jsonify({'error': 'This video is not available in your region.'}), 400
                elif 'tiktok.com' in url:
                    if 'Video unavailable' in error_msg:
                        return jsonify({'error': 'This TikTok video is unavailable or has been removed.'}), 400
                    elif 'private' in error_msg.lower():
                        return jsonify({'error': 'This TikTok video is private.'}), 400
                elif 'instagram.com' in url:
                    if 'login' in error_msg.lower():
                        return jsonify({'error': 'This Instagram post requires login to access.'}), 400
                    elif 'private' in error_msg.lower():
                        return jsonify({'error': 'This Instagram post is private.'}), 400
                
                # Generic error handling
                if 'timeout' in error_msg.lower():
                    return jsonify({'error': 'Request timed out. Please try again.'}), 408
                elif 'network' in error_msg.lower():
                    return jsonify({'error': 'Network error. Please check your connection and try again.'}), 500
                else:
                    return jsonify({'error': 'Could not download the video. Please check if the URL is correct and the video is available.'}), 400

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
    
    finally:
        # Fallback cleanup
        if temp_dir and os.path.exists(temp_dir):
            try:
                cleanup_temp_dir(temp_dir, delay=10)  # Quick cleanup on error
            except:
                pass

@app.route('/health')
def health_check():
    """Enhanced health check"""
    try:
        # Check yt-dlp
        import yt_dlp
        ytdlp_version = yt_dlp.version.__version__
        
        # Check ffmpeg
        ffmpeg_available = check_ffmpeg()
        
        return jsonify({
            'status': 'ok',
            'message': 'Video downloader is running',
            'yt_dlp_version': ytdlp_version,
            'ffmpeg_available': ffmpeg_available,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

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

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large'}), 413

@app.errorhandler(408)
def request_timeout(error):
    return jsonify({'error': 'Request timed out'}), 408

if __name__ == '__main__':
    logger.info("Starting video downloader application...")
    
    # Update yt-dlp before starting the app (optional in production)
    if os.environ.get('UPDATE_YTDLP', 'false').lower() == 'true':
        if not update_ytdlp():
            logger.warning("Failed to update yt-dlp. Continuing with existing version.")
    
    # Check for ffmpeg before starting the app
    if not check_ffmpeg():
        logger.warning("FFmpeg is not available. Video processing may fail.")
    
    # Production vs development settings
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=debug_mode,
        threaded=True  # Enable threading for better performance
    )