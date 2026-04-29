import os
from google import genai
from dotenv import load_dotenv

# 1. Load the hidden variables from your .env file
load_dotenv()

# 2. Grab the hidden key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("API Key not found! Check your .env file.")

# 3. Initialize the new SDK Client
client = genai.Client(api_key=api_key)

def test_llm():
    print("Establishing connection to the latest LLM endpoint...")
    
    # Send a strict test prompt using the updated Client syntax and model version
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Return exactly the phrase: 'Data pipeline connected!' and nothing else."
    )
    
    print("\n--- Model Response ---")
    print(response.text)

if __name__ == "__main__":
    test_llm()