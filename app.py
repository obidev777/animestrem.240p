# app.py - PARCHE PARA COMPATIBILIDAD
import sys
import asyncio

# Parche para asyncio.coroutine (compatible con Python 3.11+)
if not hasattr(asyncio, 'coroutine'):
    asyncio.coroutine = lambda x: x
    print("✅ Parche 1 aplicado: asyncio.coroutine")

# Parche adicional para tenacity
try:
    from tenacity import _asyncio
    if not hasattr(_asyncio, 'coroutine'):
        _asyncio.coroutine = lambda x: x
        print("✅ Parche 2 aplicado: tenacity._asyncio.coroutine")
except ImportError:
    pass

# Parche para mega.py
try:
    import mega.mega
    if not hasattr(asyncio, 'coroutine'):
        mega.mega.asyncio.coroutine = lambda x: x
        print("✅ Parche 3 aplicado: mega.mega.asyncio.coroutine")
except ImportError:
    pass

# AHORA importa el resto de librerías
import os
import threading
import uuid
import shutil
import requests
from flask import Flask, request, jsonify, send_file, Response
from bs4 import BeautifulSoup
import re
import time
from mega import Mega
import moviepy
from moviepy.editor import VideoFileClip
import tempfile

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()

# TU CONFIGURACIÓN ORIGINAL
BASE = 'https://tioanime.com/'
DIRECTORIO = 'https://tioanime.com/directorio'
DOWNLOAD_DIR = 'downloads'
STREAM_DIR = 'streams'

# Crear directorios
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(STREAM_DIR, exist_ok=True)

# Diccionario para progreso
conversion_progress = {}

# Inicializar cliente Mega
mega_api = Mega()

# ===== TUS FUNCIONES ORIGINALES =====
def get_anime_info(list):
    info = []
    for ep in list.contents:
        if ep == '\n':continue
        animename = ep.contents[1].contents[1].contents[3].next
        animeurl = ep.contents[1].contents[1].attrs['href']
        animefigure = ''
        try:
            animefigure = ep.contents[1].contents[1].contents[1].contents[1].contents[0].attrs['src']
        except:
            animefigure = ep.contents[1].contents[1].contents[1].contents[0].contents[0].attrs['src']
        
        if not animefigure.startswith('http'):
            animefigure = f'https://tioanime.com{animefigure}'
            
        info.append({'Anime':animename,'Url':animeurl,'Image':animefigure})
    return info

def search(searched,named=True):
    try:
        url = DIRECTORIO + '?q=' + str(searched)
        resp = requests.get(url)
        html = str(resp.text).replace('/uploads','https://tioanime.com/uploads')
        html = html.replace('/anime','https://tioanime.com/anime')
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
            
        mega = link.replace('https://mega.nz','https://mega.nz/file')
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
        html = resp.text.replace('/ver','https://tioanime.com/ver')
        soup = BeautifulSoup(html, "html.parser")
        
        # TU LÓGICA ORIGINAL para extraer episodios
        script = str(soup.find_all('script')[-1].next).replace(' ','').replace('\n','').replace('\r','')
        tokens = script.split(';')
        epis = tokens[1].split(',')
        index = 1
        for ep in epis:
            episodies.append(str(url).replace('anime/','ver/')+'-'+str(index))
            index+=1
            
        sinopsis_elem = soup.find('p',{'class':'sinopsis'})
        sinopsis = sinopsis_elem.next if sinopsis_elem else "Sin sinopsis disponible"
        
        # Título
        title_elem = soup.find('h1')
        title = title_elem.text if title_elem else "Sin título"
        
        # ===== CORRECCIÓN DE LA IMAGEN =====
        # Buscar la imagen de diferentes maneras
        image = ''
        
        # Método 1: Buscar imagen con clase card-img-top
        img_elem = soup.find('img', {'class': 'card-img-top'})
        if img_elem and img_elem.get('src'):
            image = img_elem.get('src')
            print(f"Imagen encontrada (card-img-top): {image}")
        
        # Método 2: Si no funciona, buscar cualquier imagen principal
        if not image:
            img_elem = soup.find('img', {'class': 'img-fluid'})
            if img_elem and img_elem.get('src'):
                image = img_elem.get('src')
                print(f"Imagen encontrada (img-fluid): {image}")
        
        # Método 3: Buscar en meta tags
        if not image:
            meta_img = soup.find('meta', {'property': 'og:image'})
            if meta_img and meta_img.get('content'):
                image = meta_img.get('content')
                print(f"Imagen encontrada (og:image): {image}")
        
        # Método 4: Buscar cualquier imagen relevante
        if not image:
            all_images = soup.find_all('img')
            for img in all_images:
                src = img.get('src', '')
                if 'anime' in src or 'cover' in src or 'portada' in src:
                    image = src
                    print(f"Imagen encontrada (relevante): {image}")
                    break
        
        # Asegurar URL completa
        if image and not image.startswith('http'):
            if image.startswith('//'):
                image = 'https:' + image
            elif image.startswith('/'):
                image = f'https://tioanime.com{image}'
            else:
                image = f'https://tioanime.com/{image}'
        
        print(f"URL final de la imagen: {image}")
        
        return {
            'title': title,
            'sinopsis': sinopsis,
            'image': image,
            'episodies': episodies
        }
    except Exception as e:
        print(f"Error en get_info: {e}")
        return {'title': 'Error', 'sinopsis': str(e), 'image': '', 'episodies': []}

# ===== FUNCIÓN DE CONVERSIÓN CON MOVIEPY =====
def convert_to_240p_with_moviepy(input_path, output_path, progress_key):
    """Convierte video a 240p usando moviepy"""
    try:
        conversion_progress[progress_key] = {
            'status': 'converting',
            'percent': 60,
            'message': 'Cargando video...'
        }
        
        # Cargar el video
        clip = VideoFileClip(input_path)
        
        # Obtener duración total para calcular progreso
        total_duration = clip.duration
        
        conversion_progress[progress_key] = {
            'status': 'converting',
            'percent': 70,
            'message': 'Redimensionando a 240p...'
        }
        
        # Redimensionar a 240p manteniendo aspecto
        clip_resized = clip.resize(height=240)
        
        conversion_progress[progress_key] = {
            'status': 'converting',
            'percent': 80,
            'message': 'Ajustando audio...'
        }
        
        # Configurar audio
        clip_resized = clip_resized.volumex(1.0)
        
        conversion_progress[progress_key] = {
            'status': 'converting',
            'percent': 85,
            'message': 'Escribiendo archivo final...'
        }
        
        # Escribir el archivo con compresión
        clip_resized.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            bitrate='300k',
            audio_bitrate='64k',
            preset='ultrafast',
            threads=2,
            logger=None  # Silenciar output
        )
        
        # Cerrar clips
        clip.close()
        clip_resized.close()
        
        conversion_progress[progress_key] = {
            'status': 'processing',
            'percent': 95,
            'message': 'Optimizando para streaming...'
        }
        
        return True
        
    except Exception as e:
        print(f"Error en conversión con moviepy: {e}")
        return False

# ===== FUNCIÓN DE DESCARGA Y CONVERSIÓN =====
def download_and_convert(mega_url, session_id, episode_num, anime_title):
    """Descarga desde Mega y convierte a 240p usando moviepy"""
    try:
        session_dir = os.path.join(STREAM_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Nombres de archivo
        safe_title = re.sub(r'[^\w\s-]', '', anime_title).strip().replace(' ', '_')
        temp_filename = f"{safe_title}_ep{episode_num}_temp.mp4"
        final_filename = f"{safe_title}_ep{episode_num}.mp4"
        
        temp_file = os.path.join(session_dir, temp_filename)
        output_file = os.path.join(session_dir, final_filename)
        
        progress_key = f"{session_id}_{episode_num}"
        
        # Estado: Conectando a Mega
        conversion_progress[progress_key] = {
            'status': 'connecting',
            'percent': 5,
            'message': 'Conectando a Mega...'
        }
        
        # Iniciar sesión anónima en Mega
        mega = mega_api.login()
        
        conversion_progress[progress_key] = {
            'status': 'downloading',
            'percent': 10,
            'message': 'Iniciando descarga...'
        }
        
        # Descargar archivo
        print(f"Descargando desde Mega: {mega_url}")
        mega.download_url(mega_url, session_dir, dest_filename=temp_filename)
        
        # Verificar descarga
        if not os.path.exists(temp_file):
            raise Exception("Error en la descarga: archivo no encontrado")
        
        file_size = os.path.getsize(temp_file)
        print(f"Archivo descargado: {temp_file}, tamaño: {file_size} bytes")
        
        conversion_progress[progress_key] = {
            'status': 'downloaded',
            'percent': 50,
            'message': f'Descarga completada ({file_size/1024/1024:.1f} MB)'
        }
        
        # Convertir con moviepy
        success = convert_to_240p_with_moviepy(temp_file, output_file, progress_key)
        
        if not success:
            raise Exception("Error en la conversión del video")
        
        # Eliminar archivo temporal
        if os.path.exists(temp_file):
            os.remove(temp_file)
            print(f"Archivo temporal eliminado: {temp_file}")
        
        # Verificar archivo final
        if os.path.exists(output_file):
            final_size = os.path.getsize(output_file)
            conversion_progress[progress_key] = {
                'status': 'completed',
                'percent': 100,
                'file': f"/stream/{session_id}/{final_filename}",
                'filename': final_filename,
                'size': final_size,
                'message': f'¡Video listo! ({final_size/1024/1024:.1f} MB)'
            }
            
            print(f"Video listo: {output_file}")
            return output_file
        else:
            raise Exception("Archivo no encontrado después de la conversión")
            
    except Exception as e:
        print(f"Error en download_and_convert: {e}")
        conversion_progress[progress_key] = {
            'status': 'error',
            'error': str(e),
            'message': f'Error: {str(e)}'
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
    <title>AnimeStream 240p - Streaming de Anime</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes spin { to { transform: rotate(360deg); } }
        .animate-spin { animation: spin 1s linear infinite; }
        .video-container { position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; }
        .video-container video { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
        .progress-bar { transition: width 0.3s ease; }
        .anime-card { transition: transform 0.2s, box-shadow 0.2s; cursor: pointer; }
        .anime-card:hover { transform: translateY(-4px); box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.5); }
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 600;
        }
        .status-connecting { background-color: #f59e0b; color: #000; }
        .status-downloading { background-color: #3b82f6; color: #fff; }
        .status-downloaded { background-color: #10b981; color: #fff; }
        .status-converting { background-color: #8b5cf6; color: #fff; }
        .status-processing { background-color: #ec4899; color: #fff; }
        .status-completed { background-color: #10b981; color: #fff; }
        .status-error { background-color: #ef4444; color: #fff; }
        .anime-detail-image {
            max-height: 400px;
            object-fit: cover;
            border-radius: 0.5rem;
        }
    </style>
</head>
<body class="bg-gradient-to-br from-gray-900 to-gray-800 text-white min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <header class="mb-8 text-center">
            <h1 class="text-4xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent mb-2">
                🎬 AnimeStream 240p
            </h1>
            <p class="text-gray-400">Streaming de anime optimizado para bajo consumo</p>
        </header>

        <!-- Barra de búsqueda -->
        <div class="max-w-2xl mx-auto mb-8">
            <div class="flex gap-2">
                <input 
                    type="text" 
                    id="searchInput"
                    placeholder="Buscar anime (ej: isekai, shingeki, one piece...)" 
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

            <!-- Detalles del anime seleccionado (CON IMAGEN GRANDE) -->
            <div id="animeDetails" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-6">
                    <div class="flex flex-col md:flex-row gap-8">
                        <!-- Imagen grande del anime -->
                        <div class="w-full md:w-80 flex-shrink-0">
                            <img id="animeImage" src="" alt="" 
                                 class="w-full rounded-lg shadow-2xl anime-detail-image"
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

            <!-- Reproductor -->
            <div id="playerSection" class="hidden mb-8">
                <div class="bg-gray-800 rounded-lg p-6">
                    <h3 id="currentEpisode" class="text-xl font-semibold mb-4"></h3>
                    
                    <!-- Reproductor de video -->
                    <div id="videoContainer" class="video-container bg-black rounded-lg mb-4 hidden">
                        <video id="videoPlayer" controls class="w-full"></video>
                    </div>
                    
                    <!-- Progreso de descarga y conversión -->
                    <div id="downloadProgress" class="bg-gray-700 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-lg">Procesando episodio:</span>
                            <span id="progressStatus" class="status-badge status-connecting">Iniciando</span>
                        </div>
                        <div class="w-full bg-gray-600 rounded-full h-4">
                            <div id="progressBar" class="progress-bar bg-gradient-to-r from-blue-500 to-purple-600 h-4 rounded-full" style="width: 0%"></div>
                        </div>
                        <div id="progressDetails" class="text-sm text-gray-400 mt-2 text-center"></div>
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
            playerSection: document.getElementById('playerSection'),
            navButtons: document.getElementById('navButtons'),
            resultsGrid: document.getElementById('resultsGrid'),
            episodesGrid: document.getElementById('episodesGrid'),
            loading: document.getElementById('loading'),
            videoContainer: document.getElementById('videoContainer'),
            videoPlayer: document.getElementById('videoPlayer'),
            downloadProgress: document.getElementById('downloadProgress'),
            progressBar: document.getElementById('progressBar'),
            progressStatus: document.getElementById('progressStatus'),
            progressDetails: document.getElementById('progressDetails'),
            currentEpisode: document.getElementById('currentEpisode'),
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

        function updateStatusBadge(status) {
            elements.progressStatus.className = 'status-badge';
            const statusMap = {
                'connecting': 'status-connecting',
                'downloading': 'status-downloading',
                'downloaded': 'status-downloaded',
                'converting': 'status-converting',
                'processing': 'status-processing',
                'completed': 'status-completed',
                'error': 'status-error'
            };
            elements.progressStatus.classList.add(statusMap[status] || 'status-connecting');
            elements.progressStatus.textContent = status.charAt(0).toUpperCase() + status.slice(1);
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
                elements.playerSection.classList.add('hidden');
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
                    elements.playerSection.classList.add('hidden');
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
    // Mostrar imagen grande del anime con fallback
    if (anime.image) {
        elements.animeImage.src = anime.image;
        console.log('Cargando imagen:', anime.image);
    } else {
        elements.animeImage.src = 'https://via.placeholder.com/400x600?text=Sin+Imagen';
    }
    
    elements.animeTitle.textContent = anime.title;
    elements.animeSinopsis.textContent = anime.sinopsis;

    // Manejar error de carga de imagen
    elements.animeImage.onerror = function() {
        console.log('Error cargando imagen:', anime.image);
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
            elements.playerSection.classList.remove('hidden');
            elements.videoContainer.classList.add('hidden');
            elements.downloadProgress.classList.remove('hidden');
            
            elements.progressBar.style.width = '0%';
            updateStatusBadge('connecting');
            elements.progressDetails.textContent = 'Obteniendo enlace de Mega...';

            showLoading(true);
            try {
                const response = await fetch('/episode/process', {
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
                    startProgressMonitoring(episodeNum);
                } else {
                    showError('Error al procesar episodio');
                }
            } catch (error) {
                console.error('Error:', error);
                showError('Error al procesar');
            } finally {
                showLoading(false);
            }
        }

        function startProgressMonitoring(episodeNum) {
            const checkInterval = setInterval(async () => {
                try {
                    const response = await fetch(`/progress/${appState.sessionId}/${episodeNum}`);
                    const data = await response.json();
                    
                    updateProgress(data);
                    updateStatusBadge(data.status);
                    
                    if (data.status === 'completed' && data.file) {
                        clearInterval(checkInterval);
                        playVideo(data.file, episodeNum);
                    } else if (data.status === 'error') {
                        clearInterval(checkInterval);
                        elements.progressDetails.textContent = data.error || 'Error en la descarga';
                    }
                } catch (error) {
                    console.error('Error:', error);
                }
            }, 1000);
        }

        function updateProgress(data) {
            elements.progressBar.style.width = data.percent + '%';
            elements.progressDetails.textContent = data.message || '';
        }

        function playVideo(fileUrl, episodeNum) {
            elements.videoContainer.classList.remove('hidden');
            elements.videoPlayer.src = fileUrl;
            elements.videoPlayer.load();
            elements.videoPlayer.play().catch(e => console.log('Autoplay prevented:', e));
            
            setTimeout(() => {
                elements.downloadProgress.classList.add('hidden');
            }, 3000);
        }

        function backToSearch() {
            elements.searchResults.classList.remove('hidden');
            elements.animeDetails.classList.add('hidden');
            elements.playerSection.classList.add('hidden');
            elements.navButtons.classList.add('hidden');
            elements.videoPlayer.pause();
        }

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
    """Usa TU función get_info() original"""
    try:
        # Limpiar la URL
        anime_url = anime_url.replace("https://tioanime.com", "").replace("/anime/", "")
        full_url = f"{BASE}anime/{anime_url}"
        print(f"Obteniendo info de: {full_url}")
        
        info = get_info(full_url)
        
        # Verificar que la imagen existe
        print(f"Info obtenida: {info}")
        
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

@app.route('/episode/process', methods=['POST'])
def process_episode_route():
    data = request.json
    url = data.get('url')
    session_id = data.get('session_id')
    episode_num = data.get('episode_num')
    anime_title = data.get('anime_title', 'Anime')
    
    mega_url = get_mega_url(url)
    
    if not mega_url:
        return jsonify({'success': False, 'error': 'No se pudo obtener el enlace de Mega'})
    
    print(f"Mega URL obtenida: {mega_url}")
    
    thread = threading.Thread(
        target=download_and_convert,
        args=(mega_url, session_id, episode_num, anime_title)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': 'Procesando episodio...'})

@app.route('/progress/<session_id>/<int:episode_num>')
def progress_route(session_id, episode_num):
    key = f"{session_id}_{episode_num}"
    progress = conversion_progress.get(key, {
        'status': 'waiting',
        'percent': 0,
        'message': 'Esperando...'
    })
    return jsonify(progress)

@app.route('/stream/<session_id>/<filename>')
def stream_video_route(session_id, filename):
    video_path = os.path.join(STREAM_DIR, session_id, filename)
    
    if os.path.exists(video_path):
        return send_file(video_path, mimetype='video/mp4')
    
    return jsonify({'error': 'Video no encontrado'}), 404

@app.route('/cleanup/<session_id>', methods=['POST'])
def cleanup_route(session_id):
    try:
        session_dir = os.path.join(STREAM_DIR, session_id)
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     AnimeStream 240p - CON MOVIEPY                       ║
    ║                                                          ║
    ║     🌐 http://localhost:5000                             ║
    ║                                                          ║
    ║  CARACTERÍSTICAS:                                        ║
    ║  ✓ Búsqueda de animes                                    ║
    ║  ✓ Imagen grande del anime con sinopsis                  ║
    ║  ✓ Extracción de episodios                               ║
    ║  ✓ Descarga desde Mega                                   ║
    ║  ✓ Conversión a 240p con moviepy                         ║
    ║  ✓ Barra de progreso en tiempo real                      ║
    ║  ✓ Streaming integrado                                   ║
    ║                                                          ║
    ║  Presiona Ctrl+C para detener                            ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=5000, threaded=True)

