# session_module.py gamedb

import os
import json
import hashlib
import random
import string
import time
from datetime import datetime, timezone
from flask import jsonify
from werkzeug.security import check_password_hash
import threading
import openai
from openai import OpenAI
from route_mount import *
from db_module import ConnectDB
import mysql.connector
client = OpenAI(api_key=os.getenv('API_OPENAI'))
# Configuración de OpenAI (asegúrate de que la API key esté configurada correctamente)
openai.api_key = os.getenv('API_OPENAI')

if not os.path.exists(route_mount):
    os.makedirs(route_mount)

class flow_login_session:
    def __init__(self, username, typechat):
        self.username = username
        self.chat_select = typechat

    def instance_session(self, initial_msg, user_id):
        try:
            # Crear un nuevo hilo
            thread = client.beta.threads.create()

            # Crear un nuevo mensaje en el hilo
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=initial_msg
            )

            # Abrir el archivo JSON
            json_path = os.path.join(route_mount, f'json_files/templates_structures/gpt_configs/{self.chat_select}.json')
            with open(json_path, 'r') as f:
                data = json.load(f)

            client.beta.threads.runs.create_and_poll(
                thread_id=thread.id,
                assistant_id=data["id_gpt_version"],  # Usar el ID del asistente existente
                instructions=data["function_minimalist_instruct"]
            )

            # Guardar los valores de las claves principales en variables individuales
            instance_gpt = {
                'session_thread': thread,
                'configs_gpts': data,
                'user_id': user_id
            }

            return instance_gpt
        except Exception as e:
            print(f"Error creating OpenAI session: {e}")
            return None

    def try_login_session(self, initial_msg, user_id):
        instance_created = self.instance_session(initial_msg, user_id)
        if instance_created is not None:
            return instance_created
        else:
            return "Config load failed."

