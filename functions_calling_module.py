import os 
import json 
from openai import OpenAI 
from route_mount import * 
import generator_pages as gen_doc 
import requests
import string
import random
from typing import List
import unicodedata

# Configurar el cliente OpenAI con la clave API 
api_key = os.getenv('API_OPENAI') 
client = OpenAI(api_key=api_key) 
 
class FunctionsCallingAvailable: 
    @staticmethod 
    def generate_music(prompt):
        if not prompt:
            raise ValueError("Prompt cannot be empty")
        
        try:
            response = client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=prompt,
            )
            
            audio_name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10)) + '.mp3'
            audio_path = os.path.join('static', 'audio_gen', audio_name)
            os.makedirs(os.path.dirname(audio_path), exist_ok=True)

            response.stream_to_file(audio_path)
            
            local_url = f'/static/audio_gen/{audio_name}'

            return (f"assistant: I have generated a song with the following description: {prompt}", local_url)
        except Exception as e:
            print(f"Error generating audio: {e}")
            return "assistant: Error occurred while generating the audio.", ""

    @staticmethod 
    def process_request_create_documents(title, context_instruction, content, images_insert_html): 
        """ 
        Process a JSON function call to create multiple documents and return a dictionary with their parameters. 
 
        Args: 
            title (str): The title of the document. 
            context_instruction (str): The context instruction for creating the document. 
            content (str): The content of the document. 
 
        Returns: 
            dict: A dictionary containing the function call parameters. 
        """ 
        try: 
            doc_dict = { 
                "title": title, 
                "context_instruction": context_instruction, 
                "content": content, 
                "images_insert_html": images_insert_html 
            } 
            return doc_dict 
        except Exception as e: 
            return f"Se produjo un problema: {str(e)}" 
             
             
    @staticmethod 
    def render_new_document_modified(code_html): 
        return code_html 

    @staticmethod
    def _simplify_query_two_words(query: str) -> str:
        # Elimina acentos y caracteres no alfabéticos, conserva espacios
        nfkd = unicodedata.normalize('NFKD', query or '')
        without_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
        cleaned = ''.join(ch if ch.isalpha() or ch.isspace() else ' ' for ch in without_accents)
        words = [w for w in cleaned.lower().split() if len(w) >= 2]
        if not words:
            return 'happy dog'
        # Intenta tomar las dos primeras palabras "más informativas"
        simple = ' '.join(words[:2])
        # Asegurar exactamente dos palabras para Pixabay seguras
        if len(words) == 1:
            # agrega un comodín genérico
            simple = f"{words[0]} photo"
        return simple

    @staticmethod
    def search_images(query: str, per_page: int = 10, page: int = 1, safesearch: bool = True):
        """
        Busca imágenes en Pixabay y devuelve una lista de URLs.
        Devuelve una tupla (mensaje, urls) para que el renderizador pueda mostrar una galería.
        """
        if not query:
            raise ValueError("La consulta de búsqueda no puede estar vacía")

        api_key = os.getenv("PIXABAY_API_KEY")
        if not api_key:
            raise RuntimeError("PIXABAY_API_KEY no está configurada en .env")

        # Cumplir restricciones de Pixabay: per_page 3–200, page >=1
        per_page = max(3, min(int(per_page or 10), 200))
        page = max(1, int(page or 1))

        # Simplificar consulta a 2 palabras
        simple_query = FunctionsCallingAvailable._simplify_query_two_words(query)

        url = "https://pixabay.com/api/"
        params = {
            "key": api_key,
            "q": simple_query,
            "per_page": per_page,
            "page": page,
            "safesearch": str(safesearch).lower(),
            "image_type": "photo",
            # Agregar idioma; priorizar español si la original parece española
            "lang": "es" if any(ch in query.lower() for ch in "áéíóúñ") else "en",
        }
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 429:
                raise RuntimeError("Rate limit excedido (HTTP 429). Espera al próximo minuto.")
            r.raise_for_status()
            data = r.json()
        except requests.HTTPError as e:
            # Fallback en 400/422: usar defaults mínimos y término genérico en inglés
            status = e.response.status_code if hasattr(e, 'response') and e.response is not None else 0
            if status in (400, 422):
                fallback_params = {
                    "key": api_key,
                    "q": "happy dog",
                    "per_page": 3,
                    "page": 1,
                    "safesearch": "true",
                    "image_type": "photo",
                    "lang": "en",
                }
                r = requests.get(url, params=fallback_params, timeout=20)
                if r.status_code == 429:
                    raise RuntimeError("Rate limit excedido (HTTP 429). Espera al próximo minuto.")
                r.raise_for_status()
                data = r.json()
            else:
                raise

        urls: List[str] = []
        for h in data.get("hits", []):
            # Preferir URL de mayor resolución disponible
            for k in ("imageURL", "fullHDURL", "largeImageURL", "webformatURL"):
                if h.get(k):
                    urls.append(h[k])
                    break
        return (f"assistant: He encontrado {len(urls)} imágenes para: {simple_query}", urls)
      
 
class html_format_out: 
    @staticmethod
    def music_generated(msgsend, audio_uri):
        html_return = f'''
            <div style="font-weight: lighter;">AI Answer:</div>{msgsend}
            <center>
                <audio controls src="{audio_uri}">
                    Your browser does not support the audio element.
                </audio>
            </center>
        '''
        return html_return

    @staticmethod
    def gen_document(title, context_instruction, content, images_insert_html):
        instance_generate_new_doc = gen_doc.GenerateDocument(title, context_instruction, content, images_insert_html)
        Html_code, total_tokens = instance_generate_new_doc.generate_document()
        try:
            Html_code = Html_code.replace("```html", "")
            Html_code = Html_code.replace("```", "")
            
        except:
            pass
        return Html_code, total_tokens

    @staticmethod
    def search_images_result(msgsend: str, urls: List[str]):
        # Renderizar una cuadrícula simple de imágenes enlazadas a su fuente
        imgs_html = ''.join(
            [f'<a href="{u}" target="_blank" rel="noopener"><img src="{u}" style="max-width:180px;max-height:180px;margin:6px;border-radius:8px;object-fit:cover"/></a>' for u in urls]
        )
        html_return = f'<div style="font-weight: lighter;">AI Answer:</div>{msgsend}<div style="display:flex;flex-wrap:wrap;align-items:flex-start">{imgs_html}</div>'
        return html_return

    @staticmethod 
    def render_new_document_modified(code_html): 
        return code_html 
 
functions_available = { 
    "CreateNewDocument": FunctionsCallingAvailable.process_request_create_documents, 
    "edit_current_document": FunctionsCallingAvailable.render_new_document_modified,
    "generate_music": FunctionsCallingAvailable.generate_music,
    "recall_html": FunctionsCallingAvailable.render_new_document_modified,
    "search_images": FunctionsCallingAvailable.search_images,
} 
 
functions_render_avalibles = { 
    "CreateNewDocument": html_format_out.gen_document, 
    "edit_current_document": html_format_out.render_new_document_modified,
    "generate_music": html_format_out.music_generated,
    "recall_html": html_format_out.render_new_document_modified,
    "search_images": html_format_out.search_images_result,
}