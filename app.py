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
from flask import Flask, request, jsonify, send_file, Response, stream_with_context, url_for
from bs4 import BeautifulSoup
import re
import time
from pyobidl.downloader import Downloader
from pyobidl.utils import sizeof_fmt, createID

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()

# Configuración
BASE = 'https://tioanime.com/'
DIRECTORIO = 'https://tioanime.com/directorio'
DOWNLOAD_DIR = 'downloads'

# Crear directorios
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Diccionarios para seguimiento
processes = {}  # Almacena info de descargas
download_sessions = {}  # Almacena sesiones activas
download_progress = {}  # Almacena el progreso de descargas

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

# ===== FUNCIÓN PARA DESCARGAR CON PROGRESO =====
def download_with_progress(mega_url, session_id, episode_num, anime_title, download_id):
    """Descarga el archivo de Mega y muestra progreso"""
    try:
        # Actualizar progreso inicial
        download_progress[download_id] = {
            'status': 'connecting',
            'percent': 0,
            'downloaded': 0,
            'total': 0,
            'speed': 0,
            'message': 'Conectando con Mega...',
            'session_id': session_id
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
            # Mantener la extensión pero con nuestro formato
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
                'session_id': session_id
            }
            
            # También imprimir en consola
            print(f'{filename} {sizeof_fmt(downloaded)}/{sizeof_fmt(total)} ({sizeof_fmt(speed)}/s) - {percent:.1f}%', end='\r')
        
        # Descargar archivo con callback
        downloaded_file = dl.download_url(mega_url, progressfunc=progress_callback)
        
        # Verificar descarga
        if os.path.exists(downloaded_file):
            # Si el nombre es diferente, renombrar
            if downloaded_file != filepath:
                if os.path.exists(filepath):
                    os.remove(filepath)
                os.rename(downloaded_file, filepath)
            
            final_size = os.path.getsize(filepath)
            
            # Generar URL de descarga
            download_url = f"/download/{session_id}/{filename}"
            
            # Actualizar progreso completado
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
                'session_id': session_id
            }
            
            print(f"\n✅ Descarga completada: {filepath}")
            print(f"📥 URL de descarga: {download_url}")
            return filepath
        else:
            raise Exception("Archivo no encontrado después de la descarga")
            
    except Exception as e:
        print(f"Error en descarga: {e}")
        download_progress[download_id] = {
            'status': 'error',
            'error': str(e),
            'message': f'Error: {str(e)}',
            'session_id': session_id
        }
        return None

# ===== RUTAS DE FLASK =====
@app.route('/')
def index():
    return Response('''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AnimeStream - Descarga con Enlace Directo</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes spin { to { transform: rotate(360deg); } }
        .animate-spin { animation: spin 1s linear infinite; }
        .anime-card { transition: transform 0.2s, box-shadow 0.2s; cursor: pointer; }
        .anime-card:hover { transform: translateY(-4px); box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.5); }
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
        .status-completed { background-color: #10b981; color: #fff; }
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
    </style>
</head>
<body class="bg-gradient-to-br from-gray-900 to-gray-800 text-white min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <header class="mb-8 text-center">
            <h1 class="text-4xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent mb-2">
                🎬 AnimeStream
            </h1>
            <p class="text-gray-400">Descarga episodios y obtén enlace directo</p>
        </header>

        <!-- Barra de búsqueda -->
        <div class="max-w-2xl mx-auto mb-8">
            <div class="flex gap-2">
                <input 
                    type="text" 
                    id="searchInput"
                    placeholder="Buscar anime..." 
                    class="flex-1 px-4 py-3 bg-gray-800 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none text-white"
                    value="isekai"
                    onkeypress="if(event.key==='Enter') searchAnime()"
                >
                <button 
                    onclick="searchAnime()"
                    class="px-6 py-3 bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors font-semibold"
                >
                    Buscar
                </button>
            </div>
        </div>

        <!-- Botones de navegación -->
        <div id="navButtons" class="hidden mb-4">
            <button onclick="backToSearch()" class="text-blue-400 hover:text-blue-300 inline-flex items-center">
                ← Volver a resultados
            </button>
        </div>

        <!-- Contenido principal -->
        <div id="mainContent">
            <!-- Resultados de búsqueda -->
            <div id="searchResults" class="mb-8">
                <h2 class="text-2xl font-bold mb-4 text-blue-400">Resultados</h2>
                <div id="resultsGrid" class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    <div class="col-span-full text-center py-12 text-gray-500">
                        Busca un anime para ver resultados
                    </div>
                </div>
            </div>

            <!-- Detalles del anime seleccionado -->
            <div id="animeDetails" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-6">
                    <div class="flex flex-col md:flex-row gap-8">
                        <!-- Imagen del anime -->
                        <div class="w-full md:w-80 flex-shrink-0">
                            <img id="animeImage" src="" alt="" 
                                 class="w-full rounded-lg shadow-2xl"
                                 onerror="this.src='https://via.placeholder.com/400x600?text=No+Image'">
                        </div>
                        
                        <!-- Info del anime -->
                        <div class="flex-1">
                            <h2 id="animeTitle" class="text-3xl md:text-4xl font-bold mb-4 text-blue-400"></h2>
                            <div class="bg-gray-700 rounded-lg p-4 mb-6">
                                <h3 class="text-xl font-semibold mb-2 text-gray-300">Sinopsis:</h3>
                                <p id="animeSinopsis" class="text-gray-300 leading-relaxed"></p>
                            </div>
                            
                            <!-- Episodios -->
                            <h3 class="text-2xl font-semibold mb-4 text-purple-400">Episodios disponibles:</h3>
                            <div id="episodesGrid" class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-3">
                                <div class="col-span-full text-gray-500">Cargando episodios...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sección de descarga con progreso -->
            <div id="downloadSection" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-6">
                    <h3 id="currentEpisode" class="text-xl font-semibold mb-4"></h3>
                    
                    <div id="downloadProgress" class="bg-gray-700 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-lg">Progreso de descarga:</span>
                            <span id="progressStatus" class="status-badge status-connecting">Iniciando</span>
                        </div>
                        
                        <!-- Barra de progreso -->
                        <div class="w-full bg-gray-600 rounded-full h-6 mb-2">
                            <div id="progressBar" class="progress-bar bg-gradient-to-r from-blue-500 to-purple-600 h-6 rounded-full text-xs text-white text-center leading-6" style="width: 0%">0%</div>
                        </div>
                        
                        <!-- Detalles del progreso -->
                        <div id="progressDetails" class="text-sm text-gray-300 mt-2 text-center">
                            Conectando...
                        </div>
                        
                        <!-- Velocidad y tiempo -->
                        <div id="speedInfo" class="text-xs text-gray-400 mt-2 text-center">
                            <span id="downloadSpeed">0 B/s</span> • <span id="timeRemaining">Calculando...</span>
                        </div>
                        
                        <!-- ENLACE DIRECTO DE DESCARGA (aparece cuando está listo) -->
                        <div id="downloadLinkContainer" class="hidden mt-6 text-center">
                            <div class="border-t border-gray-600 pt-4">
                                <p class="text-green-400 font-semibold mb-3">✅ ¡Descarga completada!</p>
                                <a id="finalDownloadLink" href="#" class="final-download-btn" download>
                                    ⬇️ DESCARGAR ARCHIVO
                                </a>
                                <p class="text-xs text-gray-400 mt-3">Haz clic para guardar el archivo en tu dispositivo</p>
                                
                                <!-- URL directa para copiar -->
                                <div class="mt-4 flex items-center justify-center gap-2">
                                    <input type="text" id="directUrlInput" readonly class="bg-gray-600 text-sm px-3 py-2 rounded-l w-64" value="">
                                    <button onclick="copyDirectUrl()" class="copy-btn rounded-r">Copiar</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Loading -->
        <div id="loading" class="hidden fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50">
            <div class="bg-gray-800 rounded-lg p-8 text-center">
                <div class="animate-spin rounded-full h-16 w-16 border-4 border-blue-500 border-t-transparent mx-auto mb-4"></div>
                <p class="text-xl">Cargando...</p>
            </div>
        </div>

        <!-- Mensaje de error -->
        <div id="errorMessage" class="hidden fixed bottom-4 right-4 bg-red-600 text-white px-6 py-3 rounded-lg shadow-lg z-50"></div>
        
        <!-- Toast de copiado -->
        <div id="copyToast" class="hidden fixed bottom-4 left-4 bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg z-50">
            URL copiada al portapapeles
        </div>
    </div>

    <script>
        // Estado de la aplicación
        const appState = {
            currentAnime: null,
            currentEpisode: null,
            currentDownloadId: null,
            sessionId: 'session_' + Math.random().toString(36).substr(2, 9),
            searchResults: []
        };

        // Elementos DOM
        const elements = {
            searchResults: document.getElementById('searchResults'),
            animeDetails: document.getElementById('animeDetails'),
            downloadSection: document.getElementById('downloadSection'),
            navButtons: document.getElementById('navButtons'),
            resultsGrid: document.getElementById('resultsGrid'),
            episodesGrid: document.getElementById('episodesGrid'),
            loading: document.getElementById('loading'),
            downloadProgress: document.getElementById('downloadProgress'),
            progressBar: document.getElementById('progressBar'),
            progressStatus: document.getElementById('progressStatus'),
            progressDetails: document.getElementById('progressDetails'),
            downloadSpeed: document.getElementById('downloadSpeed'),
            timeRemaining: document.getElementById('timeRemaining'),
            downloadLinkContainer: document.getElementById('downloadLinkContainer'),
            finalDownloadLink: document.getElementById('finalDownloadLink'),
            directUrlInput: document.getElementById('directUrlInput'),
            currentEpisode: document.getElementById('currentEpisode'),
            animeImage: document.getElementById('animeImage'),
            animeTitle: document.getElementById('animeTitle'),
            animeSinopsis: document.getElementById('animeSinopsis'),
            errorMessage: document.getElementById('errorMessage'),
            speedInfo: document.getElementById('speedInfo'),
            copyToast: document.getElementById('copyToast')
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
            if (seconds < 60) return Math.round(seconds) + ' segundos';
            if (seconds < 3600) {
                const mins = Math.floor(seconds / 60);
                const secs = Math.round(seconds % 60);
                return mins + ' min ' + secs + ' seg';
            }
            const hours = Math.floor(seconds / 3600);
            const mins = Math.floor((seconds % 3600) / 60);
            return hours + ' h ' + mins + ' min';
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

        function copyDirectUrl() {
            const url = elements.directUrlInput.value;
            if (url) {
                navigator.clipboard.writeText(window.location.origin + url);
                showCopyToast();
            }
        }

        function updateStatusBadge(status) {
            elements.progressStatus.className = 'status-badge';
            const statusMap = {
                'connecting': 'status-connecting',
                'downloading': 'status-downloading',
                'completed': 'status-completed',
                'error': 'status-error'
            };
            elements.progressStatus.classList.add(statusMap[status] || 'status-connecting');
            elements.progressStatus.textContent = status === 'connecting' ? 'Conectando' :
                                                 status === 'downloading' ? 'Descargando' :
                                                 status === 'completed' ? 'Completado' : 'Error';
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
                    <div class="col-span-full text-center py-12">
                        <p class="text-gray-500">No se encontraron resultados</p>
                    </div>
                `;
                return;
            }

            elements.resultsGrid.innerHTML = results.map(anime => `
                <div class="anime-card bg-gray-800 rounded-lg overflow-hidden" onclick="selectAnime('${anime.Url.replace('/anime/', '')}')">
                    <img src="${anime.Image}" alt="${anime.Anime}" 
                         class="w-full aspect-[3/4] object-cover"
                         onerror="this.src='https://via.placeholder.com/300x400?text=No+Image'">
                    <div class="p-3">
                        <p class="text-sm font-medium line-clamp-2 text-center">${anime.Anime}</p>
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
                elements.episodesGrid.innerHTML = '<p class="col-span-full text-gray-500">No hay episodios disponibles</p>';
                return;
            }

            elements.episodesGrid.innerHTML = anime.episodies.map((epUrl, index) => `
                <button 
                    onclick="downloadEpisode(${index + 1}, '${epUrl}')"
                    class="episode-btn px-4 py-3 bg-gray-700 rounded-lg hover:bg-gray-600 transition-colors text-sm font-medium text-center"
                >
                    Ep. ${index + 1}
                </button>
            `).join('');
        }

        async function downloadEpisode(episodeNum, episodeUrl) {
            appState.currentEpisode = { number: episodeNum, url: episodeUrl };
            
            elements.currentEpisode.textContent = `${appState.currentAnime.title} - Episodio ${episodeNum}`;
            elements.downloadSection.classList.remove('hidden');
            elements.downloadLinkContainer.classList.add('hidden');
            
            // Resetear progreso
            elements.progressBar.style.width = '0%';
            elements.progressBar.textContent = '0%';
            updateStatusBadge('connecting');
            elements.progressDetails.textContent = 'Iniciando descarga...';
            elements.downloadSpeed.textContent = '0 B/s';
            elements.timeRemaining.textContent = 'Calculando...';

            showLoading(true);
            try {
                const response = await fetch('/episode/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: episodeUrl,
                        session_id: appState.sessionId,
                        episode_num: episodeNum,
                        anime_title: appState.currentAnime.title
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
                        showDownloadLink(data.download_url, data.filename);
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

        function showDownloadLink(downloadUrl, filename) {
            // Mostrar el enlace directo de descarga
            elements.finalDownloadLink.href = downloadUrl;
            elements.finalDownloadLink.download = filename;
            elements.directUrlInput.value = downloadUrl;
            elements.downloadLinkContainer.classList.remove('hidden');
            
            // Actualizar mensaje
            elements.progressDetails.textContent = '✅ Descarga completada. Haz clic en el botón para guardar el archivo.';
            elements.speedInfo.classList.add('hidden');
            
            console.log('Enlace de descarga generado:', downloadUrl);
        }

        function backToSearch() {
            elements.searchResults.classList.remove('hidden');
            elements.animeDetails.classList.add('hidden');
            elements.downloadSection.classList.add('hidden');
            elements.navButtons.classList.add('hidden');
            
            // Detener monitoreo de progreso si está activo
            if (appState.currentDownloadId) {
                appState.currentDownloadId = null;
            }
        }

        // Búsqueda inicial
        document.addEventListener('DOMContentLoaded', searchAnime);
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
    """Inicia la descarga del episodio"""
    data = request.json
    url = data.get('url')
    session_id = data.get('session_id')
    episode_num = data.get('episode_num')
    anime_title = data.get('anime_title', 'Anime')
    
    mega_url = get_mega_url(url)
    
    if not mega_url:
        return jsonify({'success': False, 'error': 'No se pudo obtener el enlace de Mega'})
    
    # Crear ID único para esta descarga
    download_id = str(uuid.uuid4())
    
    print(f"Iniciando descarga: {download_id} - {mega_url}")
    
    # Iniciar hilo de descarga
    thread = threading.Thread(
        target=download_with_progress,
        args=(mega_url, session_id, episode_num, anime_title, download_id)
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

@app.route('/download/<session_id>/<filename>')
def download_file_route(session_id, filename):
    """Ruta para descargar el archivo completado - ENLACE DIRECTO"""
    filepath = os.path.join(DOWNLOAD_DIR, session_id, filename)
    
    if os.path.exists(filepath):
        return send_file(
            filepath, 
            as_attachment=True, 
            download_name=filename,
            mimetype='video/mp4'
        )
    
    return jsonify({'error': 'Archivo no encontrado'}), 404

@app.route('/file/<session_id>/<filename>')
def stream_file_route(session_id, filename):
    """Ruta alternativa para ver el archivo en el navegador"""
    filepath = os.path.join(DOWNLOAD_DIR, session_id, filename)
    
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='video/mp4')
    
    return jsonify({'error': 'Archivo no encontrado'}), 404

@app.route('/cleanup/<session_id>', methods=['POST'])
def cleanup_route(session_id):
    """Limpia los archivos de una sesión"""
    try:
        session_dir = os.path.join(DOWNLOAD_DIR, session_id)
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir)
        
        # Limpiar progreso asociado
        keys_to_delete = [k for k, v in download_progress.items() 
                         if v.get('session_id') == session_id]
        for key in keys_to_delete:
            del download_progress[key]
            
        return jsonify({'success': True, 'cleaned': len(keys_to_delete)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/sessions')
def list_sessions():
    """Lista todas las descargas activas"""
    sessions = {}
    for download_id, progress in download_progress.items():
        sessions[download_id] = {
            'status': progress.get('status'),
            'percent': progress.get('percent'),
            'message': progress.get('message'),
            'downloaded': progress.get('downloaded', 0),
            'total': progress.get('total', 0)
        }
    return jsonify(sessions)

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     AnimeStream - Descarga con Enlace Directo            ║
    ║                                                          ║
    ║     🌐 http://localhost:5000                             ║
    ║                                                          ║
    ║  CARACTERÍSTICAS:                                        ║
    ║  ✓ Descarga real de archivos Mega                        ║
    ║  ✓ Barra de progreso en tiempo real                      ║
    ║  ✓ Velocidad y tiempo restante                           ║
    ║  ✓ Almacenamiento local en /downloads                    ║
    ║  ✓ ENLACE DIRECTO: /download/session_id/filename.mp4     ║
    ║  ✓ Botón grande para descargar                           ║
    ║  ✓ URL copiable al portapapeles                          ║
    ║                                                          ║
    ║  Presiona Ctrl+C para detener                            ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=5000, threaded=True)
