import os
import threading
import uuid
import shutil
import requests
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
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

# ===== FUNCIÓN PARA OBTENER ITERADOR DE DESCARGA =====
def get_download_iterator(mega_url, session_id, episode_num, anime_title):
    """Obtiene el iterador de descarga de pyobidl"""
    try:
        # Crear downloader
        dl = Downloader()
        
        # Obtener info del archivo
        info = dl.download_info(mega_url)
        print(f"Info de Mega: {info}")
        
        if not info:
            raise Exception("No se pudo obtener información del archivo")
        
        file_info = info[0] if isinstance(info, list) else info
        filename = file_info.get('fname', f"{anime_title}_ep{episode_num}.mp4")
        filesize = file_info.get('fsize', 0)
        
        # Obtener el iterador
        iterator = file_info['iter']
        
        # Crear ID único para esta sesión
        download_id = str(uuid.uuid4())
        
        # Guardar información de la sesión
        download_sessions[download_id] = {
            'iterator': iterator,
            'filename': filename,
            'filesize': filesize,
            'session_id': session_id,
            'episode_num': episode_num,
            'anime_title': anime_title,
            'info': file_info,
            'downloaded': 0,
            'start_time': time.time()
        }
        
        return download_id, filename, filesize
        
    except Exception as e:
        print(f"Error al obtener iterador: {e}")
        return None, None, 0

# ===== RUTAS DE FLASK =====
@app.route('/')
def index():
    return Response('''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AnimeStream - Descarga Directa con Iterador</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes spin { to { transform: rotate(360deg); } }
        .animate-spin { animation: spin 1s linear infinite; }
        .anime-card { transition: transform 0.2s, box-shadow 0.2s; cursor: pointer; }
        .anime-card:hover { transform: translateY(-4px); box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.5); }
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
        .download-link {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
            background: #10b981;
            color: white;
            border-radius: 0.5rem;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.2s;
        }
        .download-link:hover {
            background: #059669;
            transform: scale(1.02);
        }
    </style>
</head>
<body class="bg-gradient-to-br from-gray-900 to-gray-800 text-white min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <header class="mb-8 text-center">
            <h1 class="text-4xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent mb-2">
                🎬 AnimeStream Directo
            </h1>
            <p class="text-gray-400">Streaming directo desde Mega usando iteradores</p>
        </header>

        <!-- Barra de búsqueda -->
        <div class="max-w-2xl mx-auto mb-8">
            <div class="flex gap-2">
                <input 
                    type="text" 
                    id="searchInput"
                    placeholder="Buscar anime (ej: shingeki, one piece, jujutsu...)" 
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

            <!-- Sección de enlace de descarga -->
            <div id="downloadSection" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-6">
                    <h3 id="currentEpisode" class="text-xl font-semibold mb-4"></h3>
                    
                    <div class="bg-gray-700 rounded-lg p-6">
                        <div class="text-center mb-4">
                            <div class="inline-block p-3 bg-blue-600 rounded-full mb-3">
                                <svg class="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                                </svg>
                            </div>
                            <h4 class="text-2xl font-bold text-white mb-2">¡Enlace generado!</h4>
                            <p class="text-gray-400 mb-4">Haz clic en el botón para descargar el archivo directamente</p>
                            
                            <div id="downloadLinkContainer" class="mt-4">
                                <!-- El enlace se insertará aquí dinámicamente -->
                            </div>
                            
                            <p id="fileInfo" class="text-sm text-gray-500 mt-4"></p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Loading -->
        <div id="loading" class="hidden fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50">
            <div class="bg-gray-800 rounded-lg p-8 text-center">
                <div class="animate-spin rounded-full h-16 w-16 border-4 border-blue-500 border-t-transparent mx-auto mb-4"></div>
                <p class="text-xl">Procesando...</p>
            </div>
        </div>

        <!-- Mensaje de error -->
        <div id="errorMessage" class="hidden fixed bottom-4 right-4 bg-red-600 text-white px-6 py-3 rounded-lg shadow-lg z-50"></div>
    </div>

    <script>
        // Estado de la aplicación
        const appState = {
            currentAnime: null,
            currentEpisode: null,
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
            downloadLinkContainer: document.getElementById('downloadLinkContainer'),
            currentEpisode: document.getElementById('currentEpisode'),
            fileInfo: document.getElementById('fileInfo'),
            animeImage: document.getElementById('animeImage'),
            animeTitle: document.getElementById('animeTitle'),
            animeSinopsis: document.getElementById('animeSinopsis'),
            errorMessage: document.getElementById('errorMessage')
        };

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

        function formatBytes(bytes, decimals = 2) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const dm = decimals < 0 ? 0 : decimals;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
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
                console.log('Seleccionando anime:', animeUrl);
                const response = await fetch(`/anime/${animeUrl}`);
                const data = await response.json();
                
                console.log('Respuesta:', data);
                
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
            if (anime.image) {
                elements.animeImage.src = anime.image;
            } else {
                elements.animeImage.src = 'https://via.placeholder.com/400x600?text=Sin+Imagen';
            }
            
            elements.animeTitle.textContent = anime.title;
            elements.animeSinopsis.textContent = anime.sinopsis;

            elements.animeImage.onerror = function() {
                this.src = 'https://via.placeholder.com/400x600?text=Error+Imagen';
            };

            if (!anime.episodies || anime.episodies.length === 0) {
                elements.episodesGrid.innerHTML = '<p class="col-span-full text-gray-500">No hay episodios disponibles</p>';
                return;
            }

            elements.episodesGrid.innerHTML = anime.episodies.map((epUrl, index) => `
                <button 
                    onclick="selectEpisode(${index + 1}, '${epUrl}')"
                    class="episode-btn px-4 py-3 bg-gray-700 rounded-lg hover:bg-gray-600 transition-colors text-sm font-medium text-center"
                >
                    Ep. ${index + 1}
                </button>
            `).join('');
        }

        async function selectEpisode(episodeNum, episodeUrl) {
            console.log('Seleccionando episodio:', episodeNum, episodeUrl);
            appState.currentEpisode = { number: episodeNum, url: episodeUrl };
            
            elements.currentEpisode.textContent = `${appState.currentAnime.title} - Episodio ${episodeNum}`;
            elements.downloadSection.classList.remove('hidden');
            elements.downloadLinkContainer.innerHTML = '<p class="text-gray-400">Generando enlace de descarga...</p>';

            showLoading(true);
            try {
                const response = await fetch('/episode/link', {
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
                    // Mostrar el enlace de descarga
                    const downloadUrl = `/download/${data.download_id}/${encodeURIComponent(data.filename)}`;
                    
                    elements.downloadLinkContainer.innerHTML = `
                        <a href="${downloadUrl}" 
                           class="download-link text-xl px-8 py-4" 
                           target="_blank">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                            </svg>
                            Descargar Episodio
                        </a>
                    `;
                    
                    elements.fileInfo.textContent = `Tamaño: ${formatBytes(data.filesize)} | Formato: MP4`;
                } else {
                    showError('Error al generar enlace: ' + (data.error || 'Desconocido'));
                    elements.downloadSection.classList.add('hidden');
                }
            } catch (error) {
                console.error('Error:', error);
                showError('Error al procesar');
                elements.downloadSection.classList.add('hidden');
            } finally {
                showLoading(false);
            }
        }

        function backToSearch() {
            elements.searchResults.classList.remove('hidden');
            elements.animeDetails.classList.add('hidden');
            elements.downloadSection.classList.add('hidden');
            elements.navButtons.classList.add('hidden');
        }

        // Búsqueda inicial
        document.addEventListener('DOMContentLoaded', () => {
            searchAnime();
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
        print(f"Obteniendo info de: {full_url}")
        
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

@app.route('/episode/link', methods=['POST'])
def episode_link_route():
    """Genera un ID de descarga y devuelve el enlace"""
    data = request.json
    url = data.get('url')
    session_id = data.get('session_id')
    episode_num = data.get('episode_num')
    anime_title = data.get('anime_title', 'Anime')
    
    mega_url = get_mega_url(url)
    
    if not mega_url:
        return jsonify({'success': False, 'error': 'No se pudo obtener el enlace de Mega'})
    
    print(f"Mega URL obtenida: {mega_url}")
    
    # Obtener el iterador
    download_id, filename, filesize = get_download_iterator(mega_url, session_id, episode_num, anime_title)
    
    if download_id:
        return jsonify({
            'success': True, 
            'download_id': download_id,
            'filename': filename,
            'filesize': filesize,
            'message': 'Enlace generado correctamente'
        })
    else:
        return jsonify({'success': False, 'error': 'No se pudo obtener el iterador de descarga'})

@app.route('/download/<download_id>/<path:filename>')
def download_file_route(download_id, filename):
    """Endpoint que usa el iterador para enviar el archivo"""
    if download_id not in download_sessions:
        return jsonify({'error': 'Sesión de descarga no encontrada'}), 404
    
    session = download_sessions[download_id]
    iterator = session['iterator']
    
    def generate():
        try:
            for chunk in iterator:
                if chunk:
                    yield chunk
        except Exception as e:
            print(f"Error durante la transmisión: {e}")
        finally:
            # Limpiar la sesión después de la descarga
            if download_id in download_sessions:
                del download_sessions[download_id]
    
    response = Response(
        stream_with_context(generate()),
        mimetype='video/mp4',
        headers={
            'Content-Disposition': f'attachment; filename="{session["filename"]}"',
            'Content-Length': str(session['filesize']) if session['filesize'] else None
        }
    )
    
    return response

@app.route('/cleanup/<session_id>', methods=['POST'])
def cleanup_route(session_id):
    """Limpia las sesiones de descarga"""
    try:
        # Limpiar sesiones de descarga
        keys_to_delete = [k for k, v in download_sessions.items() if v.get('session_id') == session_id]
        for key in keys_to_delete:
            del download_sessions[key]
            
        return jsonify({'success': True, 'cleaned': len(keys_to_delete)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/sessions')
def list_sessions():
    """Endpoint para ver sesiones activas (debug)"""
    sessions_info = {}
    for download_id, session in download_sessions.items():
        sessions_info[download_id] = {
            'filename': session['filename'],
            'filesize': session['filesize'],
            'session_id': session['session_id'],
            'episode_num': session['episode_num'],
            'anime_title': session['anime_title'],
            'downloaded': session.get('downloaded', 0),
            'elapsed': time.time() - session.get('start_time', time.time())
        }
    return jsonify(sessions_info)

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     AnimeStream - Streaming Directo con Iteradores      ║
    ║                                                          ║
    ║     🌐 http://localhost:5000                             ║
    ║                                                          ║
    ║  CARACTERÍSTICAS:                                        ║
    ║  ✓ Búsqueda de animes desde TioAnime                    ║
    ║  ✓ Información detallada (imagen + sinopsis)            ║
    ║  ✓ Lista de episodios                                    ║
    ║  ✓ Genera enlace directo /download/id/filename.mp4      ║
    ║  ✓ Usa el iterador de pyobidl para transmitir           ║
    ║  ✓ Sin almacenamiento en disco                          ║
    ║  ✓ Streaming directo al navegador                       ║
    ║                                                          ║
    ║  Presiona Ctrl+C para detener                            ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=5000, threaded=True)
