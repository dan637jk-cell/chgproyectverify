import json
import os
from pathlib import Path
import tiktoken
from openai import OpenAI
from functions_calling_module import *
import time
from generator_pages import *
import threading
from db_module import AccountsDBTools
from decimal import Decimal

# Configure the OpenAI client with the API key
api_key = os.getenv('API_OPENAI')
client = OpenAI(api_key=api_key)
try:
    encoding = tiktoken.encoding_for_model("gpt-4")
except Exception:
    # Fallback to a base encoding name if specific model not present in this tiktoken build
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:
        # Last resort: define a dummy shim to count bytes
        class _DummyEnc:
            def encode(self, s):
                return s.encode('utf-8')
        encoding = _DummyEnc()

class gpt_run_session:
    def __init__(self, hahschat, balance_session, price_per_tokenGPT, price_per_img_GEN, balance_amount, instruction_minimalist='', user_lang='en', user_balance=0.0):
        self.hash_session = hahschat
        self.instance_gpt = balance_session['session_thread']
        self.user_id = balance_session.get('user_id')
        self.name_instance = balance_session['configs_gpts']['name_instance']
        self.function_minimalist_instruct = balance_session['configs_gpts']['function_minimalist_instruct']
        self.id_gpt_version = balance_session['configs_gpts']['id_gpt_version']
        self.price_per_token = Decimal(os.getenv('PRICE_PER_TOKEN_USD', '0.000002'))
        self.price_per_token_deepseek = Decimal(os.getenv('PRICE_PER_TOKEN_DEEPSEEK_USD', '0.0000014'))
        self.price_img_gen = Decimal('0.04')
        self.user_balance = Decimal(user_balance)
        self.tokens_usage = 0
        self.run = None
        self.img_tokens_generated = 0
        self.instruction_minimalist = instruction_minimalist
        self.user_lang = user_lang
        self.images_base64_computer_vision = []
        self.return_html_object = None
        self.current_document = ""
        self.return_html_final = None
        self.lock = threading.Lock()
        self.db_builder = AccountsDBTools(
            user_db=os.getenv('USERDB'),
            password_db=os.getenv('PASSWORDDB'),
            host_db=os.getenv('DBHOST'),
            port_db=os.getenv('PORTDB'),
            database="strawberry_platform"
        )
    
    def call_function(self, function_name, *args, **kwargs):
        if function_name in functions_available:
            return functions_available[function_name](*args, **kwargs)
        else:
            raise ValueError("Function not available.")
    
    def functions_render_html(self, function_name, *args, **kwargs):
        if function_name in functions_render_avalibles:
            if function_name == "CreateNewDocument":
                render_html_code, total_tokens = functions_render_avalibles[function_name](*args, **kwargs)
                cost = Decimal(total_tokens) * self.price_per_token_deepseek
                self.user_balance -= cost
                self.db_builder.update_user_balance(self.user_id, self.user_balance)
                return render_html_code
            else:
                render_html_code = functions_render_avalibles[function_name](*args, **kwargs)
                token_count = len(encoding.encode(render_html_code))
                return render_html_code
        else:
            raise ValueError("Function render html out not available.")
    
    def process_tool_call(self, tool_call):
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        
        # Handle special cases first
        
        if function_name == "generate_music":
            self.user_balance -= Decimal('0.02')
            self.db_builder.update_user_balance(self.user_id, self.user_balance)

        if function_name == "recall_html":
            output = f"It is very important that you follow these instructions. This is the code you need to modify. Modify only what the user requests and leave everything else as is: {self.return_html_object}"
            token_count = len(encoding.encode(output))
            cost = Decimal(token_count) * self.price_per_token
            self.user_balance -= cost
            self.db_builder.update_user_balance(self.user_id, self.user_balance)
            return output
        
        if function_name == "edit_current_document":
            self.current_document = arguments['new_code_html_modified']
            self.return_html_object = arguments['new_code_html_modified']
            self.return_html_final = self.return_html_object
            token_count = len(encoding.encode(arguments['new_code_html_modified']))
            cost = Decimal(token_count) * self.price_per_token
            self.user_balance -= cost
            self.db_builder.update_user_balance(self.user_id, self.user_balance)
            return self.return_html_object
        
        try:
            # Call the function
            print(arguments)
            if isinstance(arguments, dict):
                output = self.call_function(function_name, **arguments)
            else:
                output = self.call_function(function_name, *arguments)
            
            # Process the result
            if isinstance(output, tuple):
                # For functions that return multiple values (like search_images, generate_music)
                message, additional_data = output
                self.return_html_object = self.functions_render_html(function_name, message, additional_data)
            elif isinstance(output, dict):
                # For functions that return dictionaries
                self.return_html_object = self.functions_render_html(function_name, **output)
            else:
                # For functions that return strings or other types
                self.return_html_object = self.functions_render_html(function_name, output)
            self.return_html_object = self.return_html_object.replace("```html", "").replace("```", "").replace("\n", "").replace("```json", "")
            # Update token usage count
            token_count = len(encoding.encode(str(self.return_html_object)))
            cost = Decimal(token_count) * self.price_per_token
            self.user_balance -= cost
            self.db_builder.update_user_balance(self.user_id, self.user_balance)
            self.return_html_final = self.return_html_object
            return self.return_html_object
        except Exception as e:
            return f"A problem occurred: {str(e)}"

    def check_new_msg(self):
        while self.run.status in ['queued', 'in_progress']:
            self.run = client.beta.threads.runs.retrieve(
                thread_id=self.instance_gpt.id,
                run_id=self.run.id
            )
            time.sleep(1)
        
        if self.run.status == 'completed':
            messages = client.beta.threads.messages.list(
                thread_id=self.instance_gpt.id
            )
            for message in messages.data:
                if message.role == 'assistant':
                    return message.content[0].text.value
        elif self.run.status == 'requires_action':
            tool_outputs = []
            for tool_call in self.run.required_action.submit_tool_outputs.tool_calls:
                output = self.process_tool_call(tool_call)
                print("**** "*16)
                print(output)
                print("**** "*16)
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": str(output)
                })

            if tool_outputs:
                try:
                    self.run = client.beta.threads.runs.submit_tool_outputs(
                        thread_id=self.instance_gpt.id,
                        run_id=self.run.id,
                        tool_outputs=tool_outputs
                    )
                    
                    return self.check_new_msg()
                except Exception as e:
                    print(f"Error sending tool outputs: {e}")
                    return "An error occurred while processing the request."
        elif self.run.status in ['failed', 'cancelled', 'expired']:
            error_message = f"The run ended with status: {self.run.status}."
            if self.run.last_error:
                error_message += f" Reason: {self.run.last_error.message}"
            return error_message

    def push_new_msg_user(self, msg_user, AudioReturn, images_base64):
        if not self.lock.acquire(blocking=False):
            return "Another request is already being processed. Please wait.", None, ""
        
        try:
            # Cancel any lingering active runs on this thread to avoid conflicts.
            # This handles cases where a previous run might be stuck.
            try:
                runs = client.beta.threads.runs.list(thread_id=self.instance_gpt.id, limit=10)
                for run in runs.data:
                    if run.status in ['queued', 'in_progress', 'requires_action']:
                        client.beta.threads.runs.cancel(thread_id=self.instance_gpt.id, run_id=run.id)
            except Exception as e:
                print(f"Error cancelling existing runs: {e}")

            self.return_html_final = None
            self.images_base64_computer_vision = images_base64

            # Language instruction
            language_instruction = f"You must respond and generate all content in {self.user_lang}."

            message = client.beta.threads.messages.create(
                thread_id=self.instance_gpt.id,
                role="user",
                content=f"{language_instruction}\n\n{msg_user}. It is mandatory that you always use your retrieval knowledge. Check the uploaded files and follow the instructions in the uploaded files. It is mandatory."
            )

            self.run = client.beta.threads.runs.create(
                thread_id=self.instance_gpt.id,
                assistant_id=self.id_gpt_version,
                instructions=self.instruction_minimalist
            )

            msg_respond = self.check_new_msg()

            if msg_respond is None:
                return "No response from the assistant.", None, ""

            token_count = len(encoding.encode(msg_user))
            cost = Decimal(token_count) * self.price_per_token
            self.user_balance -= cost
            self.db_builder.update_user_balance(self.user_id, self.user_balance)

            token_count_response = len(encoding.encode(msg_respond))
            cost_response = Decimal(token_count_response) * self.price_per_token
            self.user_balance -= cost_response
            self.db_builder.update_user_balance(self.user_id, self.user_balance)

            audio_generate = None  # Replace with the logic for generating audio
            return msg_respond, audio_generate, self.return_html_final
        finally:
            self.lock.release()

    def handle_user_interruption(self, msg_user):
        return "I am still working on creating your document, please give me a moment.", None, None
