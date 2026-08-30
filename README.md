# Dharshan's Lil Buddy

A Streamlit chatbot powered by Ollama's hosted API. It remembers the current
browser-session conversation and can include uploaded PNG, JPG, JPEG, or WEBP
images in a prompt. Its logo is stored at `assets/lil_buddy_logo.png`.

## Run locally

1. Install dependencies: `pip install -r requirements.txt`
2. Create `.streamlit/secrets.toml` with:

   ```toml
   OLLAMA_API_KEY = "your_ollama_api_key"
   ```

3. Start the app: `streamlit run app.py`

## Deploy to Streamlit Community Cloud

Set `OLLAMA_API_KEY` in the app's **Secrets** settings. Do not commit it to the
repository. The app uses the fixed, image-capable `gemma4:31b-cloud` model.
