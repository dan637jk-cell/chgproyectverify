import os
import json
from openai import AzureOpenAI
from dotenv import load_dotenv

# Load environment variables from .env file (align with b.py)
load_dotenv()

class GenerateDocument:
    """
    Generates a complete responsive HTML anchor page using Azure OpenAI (Chat Completions).

    Environment variables used:
    - ENDPOINT_URL: Azure OpenAI endpoint URL
    - DEPLOYMENT_NAME: Azure OpenAI deployment name for the chat model
    - AZURE_OPENAI_API_KEY: Azure OpenAI API key
    """

    def __init__(self, title, context_instruction, content, images_insert_html):
        self.title = title or ""
        self.context_instruction = context_instruction or ""
        self.content = content or ""
        self.images_insert_html = images_insert_html or ""

        endpoint = os.getenv("ENDPOINT_URL")
        deployment = os.getenv("DEPLOYMENT_NAME")
        subscription_key = os.getenv("AZURE_OPENAI_API_KEY")

        # Validate required credentials come from environment
        missing = [
            name for name, val in (
                ("ENDPOINT_URL", endpoint),
                ("DEPLOYMENT_NAME", deployment),
                ("AZURE_OPENAI_API_KEY", subscription_key),
            ) if not val
        ]
        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

        self.deployment = deployment
        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=subscription_key,
            api_version="2025-01-01-preview",
        )

    def _create_messages(self):
        # System/developer instruction based on the provided template
        developer_text = (
            "Create a professional, responsive anchor page that starts with <html> and ends with </html>. "
            "All code, including <script> or <style>, must be placed inside <html>. "
            "Always output the result as a single HTML code block. The page must include:\n\n"
            "A header menu whose items are linked via anchors to their corresponding sections.\n\n"
            "Smooth scrolling behavior when clicking on menu items.\n\n"
            "Multiple sections, each with a unique ID, descriptive text, and images (URLs will be provided by the user).\n\n"
            "At least two “Contact us on WhatsApp” buttons, using the official WhatsApp logo and linking to the specified phone number.\n\n"
            "A layout that adapts to mobile, tablet, and desktop devices.\n"
        )

        # Build user prompt combining provided fields
        user_text = (
            f"Title: {self.title}\n"
            f"Instruction: {self.context_instruction}\n\n"
            f"Content:\n{self.content}\n\n"
            f"Use these sources (image URLs or context):\n{self.images_insert_html}\n"
        )

        # Use content parts format as in the example
        messages = [
            {
                "role": "developer",
                "content": [
                    {"type": "text", "text": developer_text}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text}
                ],
            },
        ]
        return messages

    def _handle_response(self, response):
        # Extract message content as string
        message = response.choices[0].message
        content = message.content if isinstance(message.content, str) else str(message.content)

        if isinstance(content, str) and "<html" in content and "</html>" in content:
            start = content.find("<html")
            end = content.find("</html>") + len("</html>")
            return content[start:end]

        return "Error: No HTML code found in the response"

    def generate_document(self):
        messages = self._create_messages()

        # Create completion using Azure Chat Completions
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            # For 2025-01-01-preview models, use max_completion_tokens (not max_tokens)
            max_completion_tokens=40096,
            stream=False,
        )

        html_code = self._handle_response(response)

        # Usage information (if available)
        total_tokens = 0
        try:
            if hasattr(response, "usage") and response.usage and hasattr(response.usage, "total_tokens"):
                total_tokens = response.usage.total_tokens or 0
        except Exception:
            total_tokens = 0

        return html_code, total_tokens

