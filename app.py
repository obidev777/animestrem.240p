import sys
import asyncio
# Parche para tenacity en Python 3.11+
if sys.version_info >= (3, 11):
    # Añadir el decorador coroutine si no existe
    if not hasattr(asyncio, 'coroutine'):
        def coroutine_decorator(func):
            return func
        asyncio.coroutine = coroutine_decorator
        print("✅ Parche aplicado: asyncio.coroutine")
import os
import threading
import uuid
import shutil
import requests
from flask import Flask, request, jsonify, send_file, Response, stream_with_context, url_for, abort
from bs4 import BeautifulSoup
import re
import time
import json
from datetime import datetime
from pyobidl.downloader import Downloader
from pyobidl.utils import sizeof_fmt, createID
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()

# Configuración
BASE = 'https://tioanime.com/'
DIRECTORIO = 'https://tioanime.com/directorio'
DOWNLOAD_DIR = 'downloads'
DATABASE_FILE = 'downloads_db.json'

# FreeConvert API Configuration
FREECONVERT_API_KEY = 'api_production_3ef612f461b2703d69165df95dc0c13662b4e1a59b16f2b00bfa87e30124dc67.692901eba22aa85dd55aec36.699bc36e5d83271de3bcc898'  # <-- REGISTRATE EN freeconvert.com
FREECONVERT_API_URL = 'https://api.freeconvert.com/v1'

# Crear directorios
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Diccionarios para seguimiento
processes = {}  # Almacena info de descargas
download_sessions = {}  # Almacena sesiones activas
download_progress = {}  # Almacena el progreso de descargas
compression_progress = {}  # Progreso de compresión

# Base de datos de descargas (para persistencia)
downloads_db = {}

# Cargar base de datos si existe
def load_downloads_db():
    global downloads_db
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
                downloads_db = json.load(f)
            print(f"📚 Base de datos cargada: {len(downloads_db)} descargas registradas")
        except Exception as e:
            print(f"Error cargando base de datos: {e}")
            downloads_db = {}
    else:
        downloads_db = {}

def save_downloads_db():
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(downloads_db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error guardando base de datos: {e}")

# Cargar al inicio
load_downloads_db()

# ===== FUNCIONES DE EXTRACCIÓN DE TIOANIME =====
def get_anime_info(list):
    info = []
    for ep in list.contents:
        if ep == '\n': continue
        animename = ep.contents[1].contents[1].contents[3].next
        animeurl = ep.contents[1].contents[1].attrs['href']
        animefigure = ''
        try:
            animefigure = ep.contents[1].contents[1].contents[1].contents[1].contents[0].attrs['src']
        except:
            animefigure = ep.contents[1].contents[1].contents[1].contents[0].contents[0].attrs['src']
        
        if not animefigure.startswith('http'):
            animefigure = f'https://tioanime.com{animefigure}'
            
        info.append({'Anime': animename, 'Url': animeurl, 'Image': animefigure})
    return info

def search(searched):
    try:
        url = DIRECTORIO + '?q=' + str(searched)
        resp = requests.get(url)
        html = str(resp.text).replace('/uploads', 'https://tioanime.com/uploads')
        html = html.replace('/anime', 'https://tioanime.com/anime')
        soup = BeautifulSoup(html, "html.parser")
        animes = get_anime_info(soup.find_all('ul')[1])
        return animes
    except Exception as e:
        print(f"Error en search: {e}")
        return []

def get_mega(list):
    mega = ''
    for l in list:
        try:
            if 'mega' in l.contents[1].attrs['href']:
                mega = l.contents[1].attrs['href']
                break
        except:
            pass
    return mega

def get_mega_url(url):
    try:
        resp = requests.get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        link = get_mega(soup.find_all('td'))
        
        if not link:
            return None
            
        mega = link.replace('https://mega.nz', 'https://mega.nz/file')
        code = mega.split('/')[-1]
        
        if '!' in code:
            fixed_code_array = code.split('!')
            if len(fixed_code_array) >= 3:
                fixed_code = fixed_code_array[1] + fixed_code_array[0] + fixed_code_array[2]
                mega = mega.replace(code, fixed_code)
        
        return mega
    except Exception as e:
        print(f"Error en get_mega_url: {e}")
        return None

def get_info(url):
    episodies = []
    try:
        resp = requests.get(url)
        html = resp.text.replace('/ver', 'https://tioanime.com/ver')
        soup = BeautifulSoup(html, "html.parser")
        
        script = str(soup.find_all('script')[-1].next).replace(' ', '').replace('\n', '').replace('\r', '')
        tokens = script.split(';')
        epis = tokens[1].split(',')
        index = 1
        for ep in epis:
            episodies.append(str(url).replace('anime/', 'ver/') + '-' + str(index))
            index += 1
            
        sinopsis_elem = soup.find('p', {'class': 'sinopsis'})
        sinopsis = sinopsis_elem.next if sinopsis_elem else "Sin sinopsis disponible"
        
        title_elem = soup.find('h1')
        title = title_elem.text if title_elem else "Sin título"
        
        # Buscar imagen
        image = ''
        img_elem = soup.find('img', {'class': 'card-img-top'})
        if img_elem and img_elem.get('src'):
            image = img_elem.get('src')
        
        if not image:
            img_elem = soup.find('img', {'class': 'img-fluid'})
            if img_elem and img_elem.get('src'):
                image = img_elem.get('src')
        
        if not image:
            meta_img = soup.find('meta', {'property': 'og:image'})
            if meta_img and meta_img.get('content'):
                image = meta_img.get('content')
        
        if not image:
            all_images = soup.find_all('img')
            for img in all_images:
                src = img.get('src', '')
                if 'anime' in src or 'cover' in src or 'portada' in src:
                    image = src
                    break
        
        # Asegurar URL completa
        if image and not image.startswith('http'):
            if image.startswith('//'):
                image = 'https:' + image
            elif image.startswith('/'):
                image = f'https://tioanime.com{image}'
            else:
                image = f'https://tioanime.com/{image}'
        
        return {
            'title': title,
            'sinopsis': sinopsis,
            'image': image,
            'episodies': episodies
        }
    except Exception as e:
        print(f"Error en get_info: {e}")
        return {'title': 'Error', 'sinopsis': str(e), 'image': '', 'episodies': []}

# ===== FUNCIÓN PARA COMPRIMIR VIDEO CON FREECONVERT API =====
def compress_video_with_freeconvert(input_filepath, output_filename, download_id):
    """Comprime el video usando FreeConvert API (apunta al 20% del tamaño original)"""
    try:
        compression_progress[download_id] = {
            'status': 'uploading',
            'percent': 0,
            'message': 'Preparando para compresión...'
        }
        
        # Obtener tamaño original
        original_size = os.path.getsize(input_filepath)
        target_size = original_size * 0.2  # 20% del original
        
        print(f"📦 Comprimiendo: {input_filepath}")
        print(f"📊 Tamaño original: {sizeof_fmt(original_size)}")
        print(f"🎯 Objetivo: {sizeof_fmt(target_size)} (20%)")
        
        # Headers para la API
        headers = {
            'Authorization': f'Bearer {FREECONVERT_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # PASO 1: Crear un trabajo de importación
        compression_progress[download_id] = {
            'status': 'uploading',
            'percent': 10,
            'message': 'Conectando con FreeConvert...'
        }
        
        # Crear tarea de importación de archivo
        import_response = requests.post(
            f'{FREECONVERT_API_URL}/process/import/upload',
            headers=headers
        )
        
        if import_response.status_code != 200:
            raise Exception(f"Error al crear importación: {import_response.text}")
        
        import_data = import_response.json()
        upload_url = import_data.get('upload_url')
        upload_id = import_data.get('id')
        
        # PASO 2: Subir el archivo
        compression_progress[download_id] = {
            'status': 'uploading',
            'percent': 20,
            'message': 'Subiendo archivo a FreeConvert...'
        }
        
        with open(input_filepath, 'rb') as f:
            upload_response = requests.put(upload_url, data=f)
        
        if upload_response.status_code not in [200, 201]:
            raise Exception("Error al subir archivo")
        
        # PASO 3: Crear trabajo de compresión
        compression_progress[download_id] = {
            'status': 'compressing',
            'percent': 30,
            'message': 'Iniciando compresión...'
        }
        
        # Configurar opciones de compresión para reducir al 20%
        job_data = {
            'tasks': {
                'import-1': {
                    'operation': 'import/upload',
                    'id': upload_id
                },
                'compress-1': {
                    'operation': 'convert',
                    'input': 'import-1',
                    'output_format': 'mp4',
                    'engine_versions': {
                        'ffmpeg': '6.0'
                    },
                    'options': {
                        'crf': 32,  # Mayor CRF = menor calidad/menor tamaño (default 23, 32 es ~40% tamaño)
                        'preset': 'slow',  # Mejor compresión
                        'video_codec': 'libx264',
                        'audio_codec': 'aac',
                        'audio_bitrate': '64k'  # Reducir audio
                    }
                },
                'export-1': {
                    'operation': 'export/url',
                    'input': 'compress-1'
                }
            }
        }
        
        # Crear el trabajo
        job_response = requests.post(
            f'{FREECONVERT_API_URL}/jobs',
            headers=headers,
            json=job_data
        )
        
        if job_response.status_code not in [200, 201]:
            raise Exception(f"Error al crear trabajo: {job_response.text}")
        
        job_data = job_response.json()
        job_id = job_data.get('id')
        
        # PASO 4: Monitorear progreso
        compression_progress[download_id] = {
            'status': 'compressing',
            'percent': 40,
            'message': 'Comprimiendo video...'
        }
        
        # Esperar a que termine la compresión (polling)
        while True:
            status_response = requests.get(
                f'{FREECONVERT_API_URL}/jobs/{job_id}',
                headers=headers
            )
            
            if status_response.status_code != 200:
                raise Exception("Error al obtener estado")
            
            status_data = status_response.json()
            job_status = status_data.get('status')
            
            # Calcular progreso aproximado
            if job_status == 'pending':
                progress = 45
            elif job_status == 'processing':
                # Intentar obtener progreso de tareas
                tasks = status_data.get('tasks', [])
                if tasks:
                    task = tasks[0]
                    task_status = task.get('status')
                    if task_status == 'processing':
                        # Estimar progreso entre 45-90
                        progress = 45 + (task.get('progress', 0) * 0.45)
                    else:
                        progress = 50
                else:
                    progress = 50
            elif job_status == 'completed':
                progress = 90
            elif job_status in ['failed', 'cancelled']:
                raise Exception(f"Trabajo falló: {status_data.get('message', '')}")
            else:
                progress = 50
            
            compression_progress[download_id] = {
                'status': 'compressing',
                'percent': progress,
                'message': f'Comprimiendo: {progress:.0f}%'
            }
            
            if job_status == 'completed':
                break
            elif job_status in ['failed', 'cancelled']:
                raise Exception(f"Compresión falló: {status_data.get('message', '')}")
            
            time.sleep(2)
        
        # PASO 5: Obtener URL del archivo comprimido
        compression_progress[download_id] = {
            'status': 'downloading',
            'percent': 95,
            'message': 'Descargando archivo comprimido...'
        }
        
        # Buscar la tarea de export
        tasks = status_data.get('tasks', [])
        export_task = None
        for task in tasks:
            if task.get('operation') == 'export/url':
                export_task = task
                break
        
        if not export_task:
            raise Exception("No se encontró tarea de exportación")
        
        compressed_url = export_task.get('result', {}).get('url')
        if not compressed_url:
            raise Exception("No se pudo obtener URL del archivo comprimido")
        
        # PASO 6: Descargar archivo comprimido
        compressed_filename = f"compressed_{output_filename}"
        compressed_filepath = os.path.join(os.path.dirname(input_filepath), compressed_filename)
        
        # Descargar con progreso
        compressed_response = requests.get(compressed_url, stream=True)
        total_size = int(compressed_response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(compressed_filepath, 'wb') as f:
            for chunk in compressed_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = 95 + (downloaded / total_size * 5)
                        compression_progress[download_id] = {
                            'status': 'downloading',
                            'percent': percent,
                            'message': f'Descargando comprimido: {downloaded}/{total_size} bytes'
                        }
        
        compressed_size = os.path.getsize(compressed_filepath)
        reduction = (1 - (compressed_size / original_size)) * 100
        
        print(f"✅ Compresión completada")
        print(f"📦 Tamaño original: {sizeof_fmt(original_size)}")
        print(f"📦 Tamaño comprimido: {sizeof_fmt(compressed_size)}")
        print(f"📉 Reducción: {reduction:.1f}%")
        
        compression_progress[download_id] = {
            'status': 'completed',
            'percent': 100,
            'message': f'Compresión completada. Reducción: {reduction:.1f}%',
            'original_size': original_size,
            'compressed_size': compressed_size,
            'reduction': reduction
        }
        
        return compressed_filepath, compressed_size
        
    except Exception as e:
        print(f"Error en compresión: {e}")
        compression_progress[download_id] = {
            'status': 'error',
            'error': str(e),
            'message': f'Error en compresión: {str(e)}'
        }
        return None, 0

# ===== FUNCIÓN PARA DESCARGAR CON PROGRESO =====
def download_with_progress(mega_url, session_id, episode_num, anime_title, anime_image, download_id, compress=True):
    """Descarga el archivo de Mega y opcionalmente lo comprime"""
    try:
        # Actualizar progreso inicial
        download_progress[download_id] = {
            'status': 'connecting',
            'percent': 0,
            'downloaded': 0,
            'total': 0,
            'speed': 0,
            'message': 'Conectando con Mega...',
            'session_id': session_id,
            'anime_title': anime_title,
            'episode_num': episode_num
        }
        
        # Crear directorio para la sesión
        session_dir = os.path.join(DOWNLOAD_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Nombre del archivo
        safe_title = re.sub(r'[^\w\s-]', '', anime_title).strip().replace(' ', '_')
        filename = f"{safe_title}_ep{episode_num}.mp4"
        filepath = os.path.join(session_dir, filename)
        
        # Crear downloader
        dl = Downloader(destpath=session_dir)
        
        # Obtener info del archivo
        download_progress[download_id]['message'] = 'Obteniendo información del archivo...'
        info = dl.download_info(mega_url)
        
        if not info:
            raise Exception("No se pudo obtener información del archivo")
        
        file_info = info[0] if isinstance(info, list) else info
        total_size = file_info.get('fsize', 0)
        original_filename = file_info.get('fname', filename)
        
        # Usar el nombre original si está disponible
        if original_filename and original_filename != filename:
            ext = os.path.splitext(original_filename)[1]
            filename = f"{safe_title}_ep{episode_num}{ext}"
            filepath = os.path.join(session_dir, filename)
        
        # Actualizar progreso con tamaño total
        download_progress[download_id].update({
            'status': 'downloading',
            'total': total_size,
            'message': f'Iniciando descarga: {filename} ({sizeof_fmt(total_size)})'
        })
        
        # Función de callback para progreso
        def progress_callback(dl_obj, filename, downloaded, total, speed, time_remaining, args=None):
            percent = (downloaded / total * 100) if total > 0 else 0
            
            download_progress[download_id] = {
                'status': 'downloading',
                'percent': percent,
                'downloaded': downloaded,
                'total': total,
                'speed': speed,
                'time_remaining': time_remaining,
                'message': f'Descargando: {sizeof_fmt(downloaded)}/{sizeof_fmt(total)} ({sizeof_fmt(speed)}/s)',
                'session_id': session_id,
                'anime_title': anime_title,
                'episode_num': episode_num
            }
            
            print(f'{filename} {sizeof_fmt(downloaded)}/{sizeof_fmt(total)} ({sizeof_fmt(speed)}/s) - {percent:.1f}%', end='\r')
        
        # Descargar archivo con callback
        downloaded_file = dl.download_url(mega_url, progressfunc=progress_callback)
        
        # Verificar descarga
        if os.path.exists(downloaded_file):
            if downloaded_file != filepath:
                if os.path.exists(filepath):
                    os.remove(filepath)
                os.rename(downloaded_file, filepath)
            
            final_size = os.path.getsize(filepath)
            
            # Generar URLs
            download_url = f"/download/{session_id}/{filename}"
            stream_url = f"/watch/{session_id}/{filename}"
            
            # Registrar entrada base
            download_entry = {
                'id': download_id,
                'anime_title': anime_title,
                'episode_num': episode_num,
                'filename': filename,
                'filepath': filepath,
                'session_id': session_id,
                'download_url': download_url,
                'stream_url': stream_url,
                'size': final_size,
                'size_formatted': sizeof_fmt(final_size),
                'date': datetime.now().isoformat(),
                'anime_image': anime_image,
                'compressed': False
            }
            
            # Si se solicita compresión, comprimir
            if compress and final_size > 50 * 1024 * 1024:  # Solo comprimir si > 50MB
                download_progress[download_id]['message'] = 'Descarga completada. Iniciando compresión...'
                
                compressed_filepath, compressed_size = compress_video_with_freeconvert(
                    filepath, filename, download_id
                )
                
                if compressed_filepath and os.path.exists(compressed_filepath):
                    # Generar URL para archivo comprimido
                    compressed_filename = os.path.basename(compressed_filepath)
                    compressed_download_url = f"/download/{session_id}/{compressed_filename}"
                    compressed_stream_url = f"/watch/{session_id}/{compressed_filename}"
                    
                    # Crear entrada para comprimido
                    compressed_entry = {
                        'id': f"{download_id}_compressed",
                        'anime_title': anime_title,
                        'episode_num': episode_num,
                        'filename': compressed_filename,
                        'filepath': compressed_filepath,
                        'session_id': session_id,
                        'download_url': compressed_download_url,
                        'stream_url': compressed_stream_url,
                        'size': compressed_size,
                        'size_formatted': sizeof_fmt(compressed_size),
                        'date': datetime.now().isoformat(),
                        'anime_image': anime_image,
                        'original_id': download_id,
                        'original_size': final_size,
                        'original_size_formatted': sizeof_fmt(final_size),
                        'reduction': (1 - (compressed_size / final_size)) * 100,
                        'compressed': True
                    }
                    
                    # Guardar ambas entradas
                    downloads_db[download_id] = download_entry
                    downloads_db[f"{download_id}_compressed"] = compressed_entry
                    save_downloads_db()
                    
                    download_progress[download_id] = {
                        'status': 'completed_with_compression',
                        'percent': 100,
                        'message': f'¡Descarga y compresión completadas!',
                        'original': {
                            'filepath': filepath,
                            'filename': filename,
                            'download_url': download_url,
                            'size': final_size,
                            'size_formatted': sizeof_fmt(final_size)
                        },
                        'compressed': {
                            'filepath': compressed_filepath,
                            'filename': compressed_filename,
                            'download_url': compressed_download_url,
                            'size': compressed_size,
                            'size_formatted': sizeof_fmt(compressed_size),
                            'reduction': compressed_entry['reduction']
                        }
                    }
                    
                    print(f"\n✅ Proceso completado - Original + Comprimido")
                    return filepath, compressed_filepath
                else:
                    # Si falla compresión, guardar solo original
                    downloads_db[download_id] = download_entry
                    save_downloads_db()
                    
                    download_progress[download_id] = {
                        'status': 'completed',
                        'percent': 100,
                        'downloaded': final_size,
                        'total': total_size,
                        'speed': 0,
                        'message': f'¡Descarga completada! (compresión no disponible)',
                        'filepath': filepath,
                        'filename': filename,
                        'download_url': download_url,
                        'stream_url': stream_url,
                        'session_id': session_id,
                        'anime_title': anime_title,
                        'episode_num': episode_num
                    }
                    
                    return filepath, None
            else:
                # Sin compresión
                downloads_db[download_id] = download_entry
                save_downloads_db()
                
                download_progress[download_id] = {
                    'status': 'completed',
                    'percent': 100,
                    'downloaded': final_size,
                    'total': total_size,
                    'speed': 0,
                    'message': f'¡Descarga completada! ({sizeof_fmt(final_size)})',
                    'filepath': filepath,
                    'filename': filename,
                    'download_url': download_url,
                    'stream_url': stream_url,
                    'session_id': session_id,
                    'anime_title': anime_title,
                    'episode_num': episode_num
                }
                
                print(f"\n✅ Descarga completada: {filepath}")
                return filepath, None
        else:
            raise Exception("Archivo no encontrado después de la descarga")
            
    except Exception as e:
        print(f"Error en descarga: {e}")
        download_progress[download_id] = {
            'status': 'error',
            'error': str(e),
            'message': f'Error: {str(e)}',
            'session_id': session_id,
            'anime_title': anime_title,
            'episode_num': episode_num
        }
        return None, None

# ===== RUTAS DE FLASK =====
@app.route('/')
def index():
    return Response('''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>AnimeStream - Descarga y Compresión</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes spin { to { transform: rotate(360deg); } }
        .animate-spin { animation: spin 1s linear infinite; }
        .anime-card { transition: transform 0.2s, box-shadow 0.2s; cursor: pointer; }
        .anime-card:hover { transform: translateY(-4px); box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.5); }
        .anime-card:active { transform: scale(0.98); }
        .progress-bar { transition: width 0.3s ease; }
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 600;
        }
        .status-connecting { background-color: #f59e0b; color: #000; }
        .status-downloading { background-color: #3b82f6; color: #fff; }
        .status-uploading { background-color: #8b5cf6; color: #fff; }
        .status-compressing { background-color: #ec4899; color: #fff; }
        .status-completed { background-color: #10b981; color: #fff; }
        .status-completed_with_compression { background-color: #10b981; color: #fff; }
        .status-error { background-color: #ef4444; color: #fff; }
        .download-btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            color: white;
            border-radius: 0.5rem;
            font-weight: bold;
            text-decoration: none;
            transition: transform 0.2s;
        }
        .download-btn:hover {
            transform: scale(1.05);
        }
        .final-download-btn {
            display: inline-block;
            padding: 1rem 2rem;
            background: linear-gradient(135deg, #10b981, #059669);
            color: white;
            border-radius: 0.75rem;
            font-weight: bold;
            font-size: 1.25rem;
            text-decoration: none;
            transition: all 0.3s;
            box-shadow: 0 4px 6px rgba(16, 185, 129, 0.3);
        }
        .final-download-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 6px 8px rgba(16, 185, 129, 0.4);
        }
        .copy-btn {
            padding: 0.5rem 1rem;
            background: #4b5563;
            color: white;
            border-radius: 0.5rem;
            font-size: 0.875rem;
            cursor: pointer;
            transition: background 0.2s;
        }
        .copy-btn:hover {
            background: #6b7280;
        }
        .downloaded-card {
            transition: all 0.2s;
            cursor: pointer;
        }
        .downloaded-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px -5px rgba(139, 92, 246, 0.5);
        }
        .downloaded-card:active {
            transform: scale(0.98);
        }
        .tab-active {
            border-bottom: 3px solid #3b82f6;
            color: #3b82f6;
            font-weight: 600;
        }
        .no-tap-highlight {
            -webkit-tap-highlight-color: transparent;
        }
        .compressed-badge {
            background: linear-gradient(135deg, #8b5cf6, #ec4899);
        }
        @media (max-width: 640px) {
            .anime-card .text-sm {
                font-size: 0.7rem;
            }
            .final-download-btn {
                font-size: 1rem;
                padding: 0.75rem 1rem;
            }
        }
    </style>
</head>
<body class="bg-gradient-to-br from-gray-900 to-gray-800 text-white min-h-screen no-tap-highlight">
    <div class="container mx-auto px-2 sm:px-4 py-4 sm:py-8">
        <!-- Header -->
        <header class="mb-4 sm:mb-8 text-center">
            <h1 class="text-2xl sm:text-4xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent mb-1 sm:mb-2">
                🎬 AnimeStream Compressor
            </h1>
            <p class="text-xs sm:text-sm text-gray-400">Descarga y comprime videos al 20% con FreeConvert</p>
        </header>

        <!-- Barra de búsqueda -->
        <div class="max-w-2xl mx-auto mb-4 sm:mb-8 px-2">
            <div class="flex gap-1 sm:gap-2">
                <input 
                    type="text" 
                    id="searchInput"
                    placeholder="Buscar anime..." 
                    class="flex-1 px-3 sm:px-4 py-2 sm:py-3 bg-gray-800 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none text-white text-sm sm:text-base"
                    value="isekai"
                    onkeypress="if(event.key==='Enter') searchAnime()"
                >
                <button 
                    onclick="searchAnime()"
                    class="px-4 sm:px-6 py-2 sm:py-3 bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors font-semibold text-sm sm:text-base whitespace-nowrap"
                >
                    Buscar
                </button>
            </div>
        </div>

        <!-- Pestañas: Buscar / Mis Descargas -->
        <div class="flex justify-center gap-2 sm:gap-4 mb-4 sm:mb-6 border-b border-gray-700 pb-2">
            <button id="tabSearch" onclick="switchTab('search')" class="tab-btn px-4 sm:px-6 py-2 text-sm sm:text-base tab-active">
                🔍 Buscar Anime
            </button>
            <button id="tabDownloads" onclick="switchTab('downloads')" class="tab-btn px-4 sm:px-6 py-2 text-sm sm:text-base text-gray-400 hover:text-white">
                📥 Mis Descargas
            </button>
        </div>

        <!-- Botones de navegación (solo visible en pestaña search) -->
        <div id="navButtons" class="hidden mb-4">
            <button onclick="backToSearch()" class="text-blue-400 hover:text-blue-300 inline-flex items-center text-sm sm:text-base">
                ← Volver a resultados
            </button>
        </div>

        <!-- Contenido principal - PESTAÑA DE BÚSQUEDA -->
        <div id="searchTabContent">
            <!-- Resultados de búsqueda -->
            <div id="searchResults" class="mb-8">
                <h2 class="text-xl sm:text-2xl font-bold mb-3 sm:mb-4 text-blue-400 px-2">Resultados</h2>
                <div id="resultsGrid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 sm:gap-4">
                    <div class="col-span-full text-center py-12 text-gray-500 text-sm sm:text-base">
                        Busca un anime para ver resultados
                    </div>
                </div>
            </div>

            <!-- Detalles del anime seleccionado -->
            <div id="animeDetails" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-3 sm:p-6">
                    <div class="flex flex-col sm:flex-row gap-4 sm:gap-8">
                        <!-- Imagen del anime -->
                        <div class="w-full sm:w-64 md:w-80 flex-shrink-0">
                            <img id="animeImage" src="" alt="" 
                                 class="w-full h-auto rounded-lg shadow-2xl max-h-96 object-cover"
                                 onerror="this.src='https://via.placeholder.com/400x600?text=No+Image'">
                        </div>
                        
                        <!-- Info del anime -->
                        <div class="flex-1">
                            <h2 id="animeTitle" class="text-2xl sm:text-3xl md:text-4xl font-bold mb-2 sm:mb-4 text-blue-400"></h2>
                            <div class="bg-gray-700 rounded-lg p-3 sm:p-4 mb-4 sm:mb-6">
                                <h3 class="text-lg sm:text-xl font-semibold mb-2 text-gray-300">Sinopsis:</h3>
                                <p id="animeSinopsis" class="text-sm sm:text-base text-gray-300 leading-relaxed"></p>
                            </div>
                            
                            <!-- Episodios -->
                            <h3 class="text-xl sm:text-2xl font-semibold mb-3 sm:mb-4 text-purple-400">Episodios disponibles:</h3>
                            <div id="episodesGrid" class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2 sm:gap-3">
                                <div class="col-span-full text-gray-500 text-sm sm:text-base">Cargando episodios...</div>
                            </div>
                            
                            <!-- Opción de compresión -->
                            <div class="mt-4 flex items-center">
                                <input type="checkbox" id="compressCheck" class="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500" checked>
                                <label for="compressCheck" class="ml-2 text-sm text-gray-300">
                                    Comprimir video al 20% (FreeConvert)
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sección de descarga con progreso -->
            <div id="downloadSection" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-3 sm:p-6">
                    <h3 id="currentEpisode" class="text-lg sm:text-xl font-semibold mb-3 sm:mb-4"></h3>
                    
                    <div id="downloadProgress" class="bg-gray-700 rounded-lg p-3 sm:p-4">
                        <div class="flex flex-col sm:flex-row justify-between items-center mb-2 gap-2">
                            <span class="text-base sm:text-lg">Progreso:</span>
                            <span id="progressStatus" class="status-badge status-connecting text-xs sm:text-sm">Iniciando</span>
                        </div>
                        
                        <!-- Barra de progreso -->
                        <div class="w-full bg-gray-600 rounded-full h-4 sm:h-6 mb-2">
                            <div id="progressBar" class="progress-bar bg-gradient-to-r from-blue-500 to-purple-600 h-4 sm:h-6 rounded-full text-xs text-white text-center leading-4 sm:leading-6" style="width: 0%">0%</div>
                        </div>
                        
                        <!-- Detalles del progreso -->
                        <div id="progressDetails" class="text-xs sm:text-sm text-gray-300 mt-2 text-center">
                            Conectando...
                        </div>
                        
                        <!-- Velocidad y tiempo (solo descarga) -->
                        <div id="speedInfo" class="text-xs text-gray-400 mt-2 text-center">
                            <span id="downloadSpeed">0 B/s</span> • <span id="timeRemaining">Calculando...</span>
                        </div>
                        
                        <!-- ENLACES DE DESCARGA (aparece cuando está listo) -->
                        <div id="downloadLinksContainer" class="hidden mt-4 sm:mt-6">
                            <div class="border-t border-gray-600 pt-4">
                                <p class="text-green-400 font-semibold mb-3 text-sm sm:text-base text-center">✅ ¡Proceso completado!</p>
                                
                                <!-- Versión original -->
                                <div id="originalLinkContainer" class="mb-4 p-3 bg-gray-800 rounded-lg">
                                    <p class="text-xs text-gray-400 mb-2">📦 VERSIÓN ORIGINAL</p>
                                    <div class="flex flex-col sm:flex-row items-center justify-between gap-2">
                                        <span id="originalSize" class="text-sm text-gray-300"></span>
                                        <a id="originalDownloadLink" href="#" class="download-btn text-sm" download>
                                            ⬇️ Descargar Original
                                        </a>
                                    </div>
                                </div>
                                
                                <!-- Versión comprimida -->
                                <div id="compressedLinkContainer" class="p-3 bg-gray-800 rounded-lg border border-purple-500">
                                    <p class="text-xs text-purple-400 mb-2">🗜️ VERSIÓN COMPRIMIDA (20%)</p>
                                    <div class="flex flex-col sm:flex-row items-center justify-between gap-2">
                                        <span id="compressedSize" class="text-sm text-gray-300"></span>
                                        <a id="compressedDownloadLink" href="#" class="download-btn text-sm" style="background: linear-gradient(135deg, #8b5cf6, #ec4899);" download>
                                            ⬇️ Descargar Comprimido
                                        </a>
                                    </div>
                                    <p id="reductionInfo" class="text-xs text-green-400 mt-2 text-center"></p>
                                </div>
                                
                                <!-- URLs para copiar -->
                                <div class="mt-4 flex flex-col gap-2">
                                    <div class="flex flex-col sm:flex-row items-center gap-2">
                                        <input type="text" id="originalUrlInput" readonly class="bg-gray-600 text-xs px-3 py-2 rounded w-full" placeholder="URL original">
                                        <button onclick="copyUrl('original')" class="copy-btn text-xs w-full sm:w-auto">Copiar Original</button>
                                    </div>
                                    <div class="flex flex-col sm:flex-row items-center gap-2">
                                        <input type="text" id="compressedUrlInput" readonly class="bg-gray-600 text-xs px-3 py-2 rounded w-full" placeholder="URL comprimido">
                                        <button onclick="copyUrl('compressed')" class="copy-btn text-xs w-full sm:w-auto">Copiar Comprimido</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- PESTAÑA DE MIS DESCARGAS -->
        <div id="downloadsTabContent" class="hidden">
            <h2 class="text-xl sm:text-2xl font-bold mb-3 sm:mb-4 text-purple-400 px-2">📁 Mis Episodios Descargados</h2>
            
            <!-- Grid de descargas -->
            <div id="downloadsGrid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
                <div class="col-span-full text-center py-12 text-gray-500 text-sm sm:text-base">
                    Cargando tus descargas...
                </div>
            </div>
            
            <!-- Botón para limpiar todo -->
            <div class="mt-6 text-center">
                <button onclick="cleanupAllDownloads()" class="px-4 py-2 bg-red-600 rounded-lg hover:bg-red-700 transition-colors text-sm sm:text-base">
                    🗑️ Limpiar todas las descargas
                </button>
            </div>
        </div>

        <!-- Loading overlay -->
        <div id="loading" class="hidden fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50">
            <div class="bg-gray-800 rounded-lg p-6 sm:p-8 text-center mx-4">
                <div class="animate-spin rounded-full h-12 w-12 sm:h-16 sm:w-16 border-4 border-blue-500 border-t-transparent mx-auto mb-4"></div>
                <p class="text-base sm:text-xl">Cargando...</p>
            </div>
        </div>

        <!-- Mensaje de error -->
        <div id="errorMessage" class="hidden fixed bottom-4 right-4 bg-red-600 text-white px-4 py-2 sm:px-6 sm:py-3 rounded-lg shadow-lg z-50 text-sm sm:text-base max-w-xs sm:max-w-sm"></div>
        
        <!-- Toast de copiado -->
        <div id="copyToast" class="hidden fixed bottom-4 left-4 bg-green-600 text-white px-3 py-2 sm:px-4 sm:py-2 rounded-lg shadow-lg z-50 text-xs sm:text-sm">
            URL copiada al portapapeles
        </div>
        
        <!-- Toast de eliminación -->
        <div id="deleteToast" class="hidden fixed bottom-4 left-1/2 transform -translate-x-1/2 bg-red-600 text-white px-4 py-2 rounded-lg shadow-lg z-50 text-sm">
            Archivo eliminado
        </div>
    </div>

    <script>
        // Estado de la aplicación
        const appState = {
            currentAnime: null,
            currentEpisode: null,
            currentDownloadId: null,
            sessionId: 'session_' + Math.random().toString(36).substr(2, 9),
            searchResults: [],
            downloads: []
        };

        // Elementos DOM
        const elements = {
            searchResults: document.getElementById('searchResults'),
            animeDetails: document.getElementById('animeDetails'),
            downloadSection: document.getElementById('downloadSection'),
            navButtons: document.getElementById('navButtons'),
            resultsGrid: document.getElementById('resultsGrid'),
            episodesGrid: document.getElementById('episodesGrid'),
            downloadsGrid: document.getElementById('downloadsGrid'),
            loading: document.getElementById('loading'),
            downloadProgress: document.getElementById('downloadProgress'),
            progressBar: document.getElementById('progressBar'),
            progressStatus: document.getElementById('progressStatus'),
            progressDetails: document.getElementById('progressDetails'),
            downloadSpeed: document.getElementById('downloadSpeed'),
            timeRemaining: document.getElementById('timeRemaining'),
            downloadLinksContainer: document.getElementById('downloadLinksContainer'),
            originalDownloadLink: document.getElementById('originalDownloadLink'),
            compressedDownloadLink: document.getElementById('compressedDownloadLink'),
            originalUrlInput: document.getElementById('originalUrlInput'),
            compressedUrlInput: document.getElementById('compressedUrlInput'),
            originalSize: document.getElementById('originalSize'),
            compressedSize: document.getElementById('compressedSize'),
            reductionInfo: document.getElementById('reductionInfo'),
            originalLinkContainer: document.getElementById('originalLinkContainer'),
            compressedLinkContainer: document.getElementById('compressedLinkContainer'),
            currentEpisode: document.getElementById('currentEpisode'),
            animeImage: document.getElementById('animeImage'),
            animeTitle: document.getElementById('animeTitle'),
            animeSinopsis: document.getElementById('animeSinopsis'),
            errorMessage: document.getElementById('errorMessage'),
            speedInfo: document.getElementById('speedInfo'),
            copyToast: document.getElementById('copyToast'),
            deleteToast: document.getElementById('deleteToast'),
            tabSearch: document.getElementById('tabSearch'),
            tabDownloads: document.getElementById('tabDownloads'),
            searchTabContent: document.getElementById('searchTabContent'),
            downloadsTabContent: document.getElementById('downloadsTabContent'),
            compressCheck: document.getElementById('compressCheck')
        };

        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function formatTime(seconds) {
            if (!seconds || seconds < 0) return 'Calculando...';
            if (seconds < 60) return Math.round(seconds) + ' seg';
            if (seconds < 3600) {
                const mins = Math.floor(seconds / 60);
                const secs = Math.round(seconds % 60);
                return mins + ' min ' + secs + ' seg';
            }
            const hours = Math.floor(seconds / 3600);
            const mins = Math.floor((seconds % 3600) / 60);
            return hours + 'h ' + mins + 'm';
        }

        function showLoading(show) {
            elements.loading.classList.toggle('hidden', !show);
        }

        function showError(msg) {
            elements.errorMessage.textContent = msg;
            elements.errorMessage.classList.remove('hidden');
            setTimeout(() => {
                elements.errorMessage.classList.add('hidden');
            }, 5000);
        }

        function showCopyToast() {
            elements.copyToast.classList.remove('hidden');
            setTimeout(() => {
                elements.copyToast.classList.add('hidden');
            }, 2000);
        }

        function showDeleteToast() {
            elements.deleteToast.classList.remove('hidden');
            setTimeout(() => {
                elements.deleteToast.classList.add('hidden');
            }, 2000);
        }

        function copyUrl(type) {
            const url = type === 'original' ? elements.originalUrlInput.value : elements.compressedUrlInput.value;
            if (url) {
                navigator.clipboard.writeText(window.location.origin + url);
                showCopyToast();
            }
        }

        function switchTab(tab) {
            if (tab === 'search') {
                elements.tabSearch.classList.add('tab-active');
                elements.tabSearch.classList.remove('text-gray-400');
                elements.tabDownloads.classList.remove('tab-active');
                elements.tabDownloads.classList.add('text-gray-400');
                elements.searchTabContent.classList.remove('hidden');
                elements.downloadsTabContent.classList.add('hidden');
            } else {
                elements.tabDownloads.classList.add('tab-active');
                elements.tabDownloads.classList.remove('text-gray-400');
                elements.tabSearch.classList.remove('tab-active');
                elements.tabSearch.classList.add('text-gray-400');
                elements.searchTabContent.classList.add('hidden');
                elements.downloadsTabContent.classList.remove('hidden');
                loadDownloads();
            }
        }

        function updateStatusBadge(status) {
            elements.progressStatus.className = 'status-badge';
            const statusMap = {
                'connecting': 'status-connecting',
                'downloading': 'status-downloading',
                'uploading': 'status-uploading',
                'compressing': 'status-compressing',
                'completed': 'status-completed',
                'completed_with_compression': 'status-completed_with_compression',
                'error': 'status-error'
            };
            
            let displayStatus = status;
            if (status === 'completed_with_compression') displayStatus = 'Completado';
            else if (status === 'uploading') displayStatus = 'Subiendo';
            else if (status === 'compressing') displayStatus = 'Comprimiendo';
            else displayStatus = status.charAt(0).toUpperCase() + status.slice(1);
            
            elements.progressStatus.classList.add(statusMap[status] || 'status-connecting');
            elements.progressStatus.textContent = displayStatus;
        }

        async function searchAnime() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) {
                showError('Ingresa un término de búsqueda');
                return;
            }

            showLoading(true);
            try {
                const response = await fetch(`/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                
                appState.searchResults = data;
                displayResults(data);
                
                elements.searchResults.classList.remove('hidden');
                elements.animeDetails.classList.add('hidden');
                elements.downloadSection.classList.add('hidden');
                elements.navButtons.classList.add('hidden');
                
            } catch (error) {
                console.error('Error:', error);
                showError('Error al buscar');
            } finally {
                showLoading(false);
            }
        }

        function displayResults(results) {
            if (!results || results.length === 0) {
                elements.resultsGrid.innerHTML = `
                    <div class="col-span-full text-center py-8 sm:py-12">
                        <p class="text-gray-500 text-sm sm:text-base">No se encontraron resultados</p>
                    </div>
                `;
                return;
            }

            elements.resultsGrid.innerHTML = results.map(anime => `
                <div class="anime-card bg-gray-800 rounded-lg overflow-hidden" onclick="selectAnime('${anime.Url.replace('/anime/', '')}')">
                    <img src="${anime.Image}" alt="${anime.Anime}" 
                         class="w-full aspect-[3/4] object-cover"
                         loading="lazy"
                         onerror="this.src='https://via.placeholder.com/300x400?text=No+Image'">
                    <div class="p-2 sm:p-3">
                        <p class="text-xs sm:text-sm font-medium line-clamp-2 text-center">${anime.Anime}</p>
                    </div>
                </div>
            `).join('');
        }

        async function selectAnime(animeUrl) {
            showLoading(true);
            try {
                const response = await fetch(`/anime/${animeUrl}`);
                const data = await response.json();
                
                if (data.success) {
                    appState.currentAnime = data.anime;
                    displayAnimeDetails(data.anime);
                    
                    elements.searchResults.classList.add('hidden');
                    elements.animeDetails.classList.remove('hidden');
                    elements.downloadSection.classList.add('hidden');
                    elements.navButtons.classList.remove('hidden');
                } else {
                    showError('Error al cargar anime');
                }
            } catch (error) {
                console.error('Error:', error);
                showError('Error al cargar detalles');
            } finally {
                showLoading(false);
            }
        }

        function displayAnimeDetails(anime) {
            elements.animeImage.src = anime.image || 'https://via.placeholder.com/400x600?text=Sin+Imagen';
            elements.animeTitle.textContent = anime.title;
            elements.animeSinopsis.textContent = anime.sinopsis;

            if (!anime.episodies || anime.episodies.length === 0) {
                elements.episodesGrid.innerHTML = '<p class="col-span-full text-gray-500 text-sm sm:text-base">No hay episodios disponibles</p>';
                return;
            }

            elements.episodesGrid.innerHTML = anime.episodies.map((epUrl, index) => `
                <button 
                    onclick="downloadEpisode(${index + 1}, '${epUrl}')"
                    class="episode-btn px-2 sm:px-4 py-2 sm:py-3 bg-gray-700 rounded-lg hover:bg-gray-600 transition-colors text-xs sm:text-sm font-medium text-center"
                >
                    Ep. ${index + 1}
                </button>
            `).join('');
        }

        async function downloadEpisode(episodeNum, episodeUrl) {
            appState.currentEpisode = { number: episodeNum, url: episodeUrl };
            
            elements.currentEpisode.textContent = `${appState.currentAnime.title} - Episodio ${episodeNum}`;
            elements.downloadSection.classList.remove('hidden');
            elements.downloadLinksContainer.classList.add('hidden');
            
            // Resetear progreso
            elements.progressBar.style.width = '0%';
            elements.progressBar.textContent = '0%';
            updateStatusBadge('connecting');
            elements.progressDetails.textContent = 'Iniciando descarga...';
            elements.downloadSpeed.textContent = '0 B/s';
            elements.timeRemaining.textContent = 'Calculando...';
            elements.speedInfo.classList.remove('hidden');

            showLoading(true);
            try {
                const compress = elements.compressCheck ? elements.compressCheck.checked : true;
                
                const response = await fetch('/episode/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: episodeUrl,
                        session_id: appState.sessionId,
                        episode_num: episodeNum,
                        anime_title: appState.currentAnime.title,
                        anime_image: appState.currentAnime.image || '',
                        compress: compress
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    appState.currentDownloadId = data.download_id;
                    startProgressMonitoring(data.download_id);
                } else {
                    showError('Error al iniciar descarga: ' + (data.error || 'Desconocido'));
                    elements.downloadSection.classList.add('hidden');
                }
            } catch (error) {
                console.error('Error:', error);
                showError('Error al iniciar descarga');
                elements.downloadSection.classList.add('hidden');
            } finally {
                showLoading(false);
            }
        }

        function startProgressMonitoring(downloadId) {
            const checkInterval = setInterval(async () => {
                try {
                    const response = await fetch(`/progress/${downloadId}`);
                    const data = await response.json();
                    
                    updateProgress(data);
                    updateStatusBadge(data.status);
                    
                    if (data.status === 'completed') {
                        clearInterval(checkInterval);
                        showDownloadLinks(data.download_url, data.filename, null, null, null, null);
                    } else if (data.status === 'completed_with_compression') {
                        clearInterval(checkInterval);
                        showDownloadLinks(
                            data.original.download_url,
                            data.original.filename,
                            data.compressed.download_url,
                            data.compressed.filename,
                            data.original.size,
                            data.compressed.size,
                            data.compressed.reduction
                        );
                        // Recargar descargas si estamos en esa pestaña
                        if (!elements.downloadsTabContent.classList.contains('hidden')) {
                            loadDownloads();
                        }
                    } else if (data.status === 'error') {
                        clearInterval(checkInterval);
                        elements.progressDetails.textContent = data.error || 'Error en la descarga';
                    }
                } catch (error) {
                    console.error('Error:', error);
                }
            }, 500);
        }

        function updateProgress(data) {
            const percent = data.percent || 0;
            elements.progressBar.style.width = percent + '%';
            elements.progressBar.textContent = Math.round(percent) + '%';
            elements.progressDetails.textContent = data.message || '';
            
            if (data.speed) {
                elements.downloadSpeed.textContent = formatBytes(data.speed) + '/s';
            }
            
            if (data.time_remaining) {
                elements.timeRemaining.textContent = formatTime(data.time_remaining);
            }
        }

        function showDownloadLinks(originalUrl, originalFilename, compressedUrl, compressedFilename, originalSize, compressedSize, reduction) {
            elements.downloadLinksContainer.classList.remove('hidden');
            elements.speedInfo.classList.add('hidden');
            
            // Configurar enlaces originales
            if (originalUrl) {
                elements.originalDownloadLink.href = originalUrl;
                elements.originalDownloadLink.download = originalFilename;
                elements.originalUrlInput.value = originalUrl;
                if (originalSize) {
                    elements.originalSize.textContent = `Tamaño: ${formatBytes(originalSize)}`;
                }
            }
            
            // Configurar enlaces comprimidos
            if (compressedUrl) {
                elements.compressedDownloadLink.href = compressedUrl;
                elements.compressedDownloadLink.download = compressedFilename;
                elements.compressedUrlInput.value = compressedUrl;
                if (compressedSize) {
                    elements.compressedSize.textContent = `Tamaño: ${formatBytes(compressedSize)}`;
                }
                if (reduction) {
                    elements.reductionInfo.textContent = `✨ Reducción del ${reduction.toFixed(1)}%`;
                }
                elements.compressedLinkContainer.classList.remove('hidden');
            } else {
                elements.compressedLinkContainer.classList.add('hidden');
            }
            
            elements.progressDetails.textContent = '✅ Proceso completado. Elige qué versión descargar.';
        }

        function backToSearch() {
            elements.searchResults.classList.remove('hidden');
            elements.animeDetails.classList.add('hidden');
            elements.downloadSection.classList.add('hidden');
            elements.navButtons.classList.add('hidden');
            
            if (appState.currentDownloadId) {
                appState.currentDownloadId = null;
            }
        }

        async function loadDownloads() {
            showLoading(true);
            try {
                const response = await fetch('/downloads/list');
                const data = await response.json();
                
                appState.downloads = data.downloads || [];
                displayDownloads(appState.downloads);
            } catch (error) {
                console.error('Error cargando descargas:', error);
                elements.downloadsGrid.innerHTML = `
                    <div class="col-span-full text-center py-8 sm:py-12">
                        <p class="text-red-400 text-sm sm:text-base">Error al cargar descargas</p>
                    </div>
                `;
            } finally {
                showLoading(false);
            }
        }

        function displayDownloads(downloads) {
            if (!downloads || downloads.length === 0) {
                elements.downloadsGrid.innerHTML = `
                    <div class="col-span-full text-center py-8 sm:py-12">
                        <p class="text-gray-500 text-sm sm:text-base">No hay episodios descargados todavía</p>
                        <p class="text-xs text-gray-600 mt-2">Ve a "Buscar Anime" y descarga algunos episodios</p>
                    </div>
                `;
                return;
            }

            // Agrupar por sesión para mostrar original + comprimido juntos
            const grouped = {};
            downloads.forEach(dl => {
                const baseId = dl.id.replace('_compressed', '');
                if (!grouped[baseId]) grouped[baseId] = {};
                if (dl.compressed) {
                    grouped[baseId].compressed = dl;
                } else {
                    grouped[baseId].original = dl;
                }
            });

            elements.downloadsGrid.innerHTML = Object.values(grouped).map(group => {
                const original = group.original;
                const compressed = group.compressed;
                
                if (!original) return '';
                
                return `
                    <div class="downloaded-card bg-gray-800 rounded-lg overflow-hidden border border-gray-700">
                        <div class="flex flex-col h-full">
                            <div class="relative">
                                <img src="${original.anime_image || 'https://via.placeholder.com/300x400?text=No+Image'}" 
                                     alt="${original.anime_title}"
                                     class="w-full aspect-video object-cover"
                                     onerror="this.src='https://via.placeholder.com/300x200?text=No+Image'">
                                <span class="absolute top-2 right-2 bg-purple-600 text-white text-xs px-2 py-1 rounded-full">
                                    EP ${original.episode_num}
                                </span>
                                ${compressed ? '<span class="absolute top-2 left-2 compressed-badge text-white text-xs px-2 py-1 rounded-full">Comprimido</span>' : ''}
                            </div>
                            <div class="p-3 flex-1 flex flex-col">
                                <h3 class="font-semibold text-sm sm:text-base line-clamp-2 mb-1">${original.anime_title}</h3>
                                <p class="text-xs text-gray-400 mb-2">${original.size_formatted}</p>
                                
                                <div class="flex flex-col gap-2 mt-auto">
                                    <div class="flex gap-2">
                                        <a href="${original.download_url}" 
                                           class="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-xs sm:text-sm py-2 px-3 rounded text-center"
                                           download>
                                            ⬇️ Original
                                        </a>
                                        <a href="${original.stream_url}" 
                                           target="_blank"
                                           class="flex-1 bg-green-600 hover:bg-green-700 text-white text-xs sm:text-sm py-2 px-3 rounded text-center">
                                            ▶️ Ver
                                        </a>
                                    </div>
                                    
                                    ${compressed ? `
                                    <div class="flex gap-2">
                                        <a href="${compressed.download_url}" 
                                           class="flex-1 compressed-badge hover:opacity-90 text-white text-xs sm:text-sm py-2 px-3 rounded text-center"
                                           download>
                                            🗜️ Comprimido (${compressed.size_formatted})
                                        </a>
                                        <a href="${compressed.stream_url}" 
                                           target="_blank"
                                           class="flex-1 bg-purple-600 hover:bg-purple-700 text-white text-xs sm:text-sm py-2 px-3 rounded text-center">
                                            ▶️ Ver
                                        </a>
                                    </div>
                                    <p class="text-xs text-green-400 text-center">${compressed.reduction.toFixed(1)}% más pequeño</p>
                                    ` : ''}
                                    
                                    <button onclick="deleteDownload('${original.id}')" 
                                            class="mt-2 bg-red-600 hover:bg-red-700 text-white text-xs sm:text-sm py-2 px-3 rounded w-full">
                                        🗑️ Eliminar
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function deleteDownload(downloadId) {
            if (!confirm('¿Eliminar este episodio y su versión comprimida?')) return;
            
            showLoading(true);
            try {
                const response = await fetch(`/downloads/delete/${downloadId}`, {
                    method: 'POST'
                });
                const data = await response.json();
                
                if (data.success) {
                    showDeleteToast();
                    loadDownloads();
                } else {
                    showError('Error al eliminar');
                }
            } catch (error) {
                console.error('Error:', error);
                showError('Error al eliminar');
            } finally {
                showLoading(false);
            }
        }

        async function cleanupAllDownloads() {
            if (!confirm('¿Eliminar TODOS los episodios descargados? Esta acción no se puede deshacer.')) return;
            
            showLoading(true);
            try {
                const response = await fetch('/downloads/cleanup/all', {
                    method: 'POST'
                });
                const data = await response.json();
                
                if (data.success) {
                    showDeleteToast();
                    loadDownloads();
                } else {
                    showError('Error al limpiar');
                }
            } catch (error) {
                console.error('Error:', error);
                showError('Error al limpiar');
            } finally {
                showLoading(false);
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            searchAnime();
            setTimeout(loadDownloads, 1000);
        });
    </script>
</body>
</html>
    ''', mimetype='text/html')

# ===== RUTAS DE LA API =====
@app.route('/search')
def search_route():
    query = request.args.get('q', '')
    results = search(query)
    return jsonify(results)

@app.route('/anime/<path:anime_url>')
def anime_info_route(anime_url):
    try:
        anime_url = anime_url.replace("https://tioanime.com", "").replace("/anime/", "")
        full_url = f"{BASE}anime/{anime_url}"
        
        info = get_info(full_url)
        
        return jsonify({
            'success': True,
            'anime': {
                'title': info.get('title', 'Sin título'),
                'sinopsis': info.get('sinopsis', 'Sin sinopsis'),
                'image': info.get('image', ''),
                'episodies': info.get('episodies', [])
            }
        })
    except Exception as e:
        print(f"Error en ruta anime: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/episode/download', methods=['POST'])
def episode_download_route():
    """Inicia la descarga del episodio con compresión opcional"""
    data = request.json
    url = data.get('url')
    session_id = data.get('session_id')
    episode_num = data.get('episode_num')
    anime_title = data.get('anime_title', 'Anime')
    anime_image = data.get('anime_image', '')
    compress = data.get('compress', True)
    
    mega_url = get_mega_url(url)
    
    if not mega_url:
        return jsonify({'success': False, 'error': 'No se pudo obtener el enlace de Mega'})
    
    # Crear ID único para esta descarga
    download_id = str(uuid.uuid4())
    
    print(f"Iniciando descarga: {download_id} - {mega_url}")
    print(f"Compresión: {'SÍ' if compress else 'NO'}")
    
    # Iniciar hilo de descarga
    thread = threading.Thread(
        target=download_with_progress,
        args=(mega_url, session_id, episode_num, anime_title, anime_image, download_id, compress)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'download_id': download_id,
        'message': 'Descarga iniciada'
    })

@app.route('/progress/<download_id>')
def progress_route(download_id):
    """Obtiene el progreso de una descarga"""
    progress = download_progress.get(download_id, {
        'status': 'waiting',
        'percent': 0,
        'message': 'Esperando...'
    })
    return jsonify(progress)

@app.route('/compression-progress/<download_id>')
def compression_progress_route(download_id):
    """Obtiene el progreso de compresión"""
    progress = compression_progress.get(download_id, {
        'status': 'waiting',
        'percent': 0,
        'message': 'Esperando compresión...'
    })
    return jsonify(progress)

@app.route('/download/<session_id>/<filename>')
def download_file_route(session_id, filename):
    """Ruta para descargar el archivo"""
    filepath = os.path.join(DOWNLOAD_DIR, session_id, filename)
    
    if os.path.exists(filepath):
        return send_file(
            filepath, 
            as_attachment=True, 
            download_name=filename,
            mimetype='video/mp4'
        )
    
    return jsonify({'error': 'Archivo no encontrado'}), 404

@app.route('/watch/<session_id>/<filename>')
def watch_file_route(session_id, filename):
    """Ruta para ver el video en el navegador"""
    filepath = os.path.join(DOWNLOAD_DIR, session_id, filename)
    
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='video/mp4')
    
    return jsonify({'error': 'Archivo no encontrado'}), 404

@app.route('/downloads/list')
def list_downloads_route():
    """Lista todas las descargas completadas"""
    downloads = list(downloads_db.values())
    downloads.sort(key=lambda x: x.get('date', ''), reverse=True)
    return jsonify({'success': True, 'downloads': downloads})

@app.route('/downloads/delete/<download_id>', methods=['POST'])
def delete_download_route(download_id):
    """Elimina una descarga y su versión comprimida si existe"""
    try:
        # Eliminar versión comprimida si existe
        compressed_id = f"{download_id}_compressed"
        if compressed_id in downloads_db:
            compressed_entry = downloads_db[compressed_id]
            if os.path.exists(compressed_entry['filepath']):
                os.remove(compressed_entry['filepath'])
            del downloads_db[compressed_id]
        
        # Eliminar original
        if download_id in downloads_db:
            entry = downloads_db[download_id]
            if os.path.exists(entry['filepath']):
                os.remove(entry['filepath'])
            
            # Eliminar directorio si está vacío
            session_dir = os.path.dirname(entry['filepath'])
            if os.path.exists(session_dir) and not os.listdir(session_dir):
                os.rmdir(session_dir)
            
            del downloads_db[download_id]
        
        save_downloads_db()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/downloads/cleanup/all', methods=['POST'])
def cleanup_all_downloads_route():
    """Elimina todas las descargas"""
    try:
        # Eliminar todos los archivos
        for download_id, entry in list(downloads_db.items()):
            try:
                if os.path.exists(entry['filepath']):
                    os.remove(entry['filepath'])
                
                session_dir = os.path.dirname(entry['filepath'])
                if os.path.exists(session_dir) and not os.listdir(session_dir):
                    os.rmdir(session_dir)
            except:
                pass
        
        downloads_db.clear()
        save_downloads_db()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cleanup/<session_id>', methods=['POST'])
def cleanup_route(session_id):
    """Limpia los archivos de una sesión específica"""
    try:
        session_dir = os.path.join(DOWNLOAD_DIR, session_id)
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir)
        
        keys_to_delete = [k for k, v in download_progress.items() 
                         if v.get('session_id') == session_id]
        for key in keys_to_delete:
            del download_progress[key]
            
        return jsonify({'success': True, 'cleaned': len(keys_to_delete)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     AnimeStream - COMPRESIÓN FREECONVERT                 ║
    ║                                                          ║
    ║     🌐 http://localhost:5000                             ║
    ║                                                          ║
    ║  CARACTERÍSTICAS:                                        ║
    ║  ✓ Descarga desde Mega con progreso                      ║
    ║  ✓ COMPRESIÓN AUTOMÁTICA AL 20% con FreeConvert          ║
    ║  ✓ Dos versiones: ORIGINAL y COMPRIMIDO                  ║
    ║  ✓ URLs separadas para cada versión                      ║
    ║  ✓ Botones individuales para descargar                   ║
    ║  ✓ Pestaña "Mis Descargas" con ambas versiones           ║
    ║                                                          ║
    ║  ⚠️  IMPORTANTE:                                          ║
    ║  - Registrate en freeconvert.com para obtener API Key    ║
    ║  - Reemplaza FREECONVERT_API_KEY en el código            ║
    ║  - Plan gratis: 20 minutos/día de conversión [citation:2][citation:4] ║
    ║                                                          ║
    ║  Presiona Ctrl+C para detener                            ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=5000, threaded=True, host='0.0.0.0')
