import asyncio
import os
import json
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv

# 1. Load your hidden API key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("API Key not found! Check your .env file.")

client = genai.Client(api_key=api_key)

async def scrape_catalog():
    print("Step 1: Launching browser to scrape catalog...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        await page.goto("https://www.traderjoes.com/home/products/category/meat-seafood-11")
        await page.wait_for_timeout(5000)
        
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        await browser.close()

    scraped_products = []
    products = soup.find_all(['h2', 'h3'])
    
    for prod in products:
        title_text = prod.get_text().strip()
        if not title_text or title_text in ["Fearless Flyer", "The Podcast", "Recipes", "What's New"]:
            continue
            
        card_container = prod.find_parent('section')
        if card_container:
            link_tag = card_container.find('a', href=True)
            if link_tag and "/pdp/" in link_tag['href']:
                href = link_tag['href']
                full_url = href if href.startswith("http") else f"https://www.traderjoes.com{href}"
                
                if not any(p['name'] == title_text for p in scraped_products):
                    scraped_products.append({
                        "name": title_text,
                        "url": full_url
                    })
                    
    print(f"-> Successfully scraped {len(scraped_products)} items.")
    return scraped_products

def generate_macro_database(products):
    print("\nStep 2: Sending data to the LLM for macro extraction...")
    
    # Process the full batch of scraped items
    item_names = [item['name'] for item in products]
    
    prompt = f"""
    Act as a nutritional database. I am building a software engineering portfolio project.
    Please provide the estimated per-serving nutritional information for the following Trader Joe's items.
    
    It is highly important that the Dietary Fiber (g) is accurate, as this data will be used to fuel a constraint-solving engine that prioritizes digestion and strict maintenance targets.
    
    Items to analyze: {item_names}
    
    Return ONLY a raw JSON array of objects. Do not use markdown blocks or backticks. 
    Each object must have exactly these keys: "name", "calories", "protein", "carbs", "fat", "fiber".
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    
    return response.text

async def main():
    products = await scrape_catalog()
    if not products:
        print("Error: No products found.")
        return
        
    json_database = generate_macro_database(products)
    
    print("\nStep 3: Saving data locally...")
    
    # Clean the LLM output in case it accidentally added markdown formatting
    clean_json = json_database.replace('```json\n', '').replace('\n```', '')
    
    with open("trader_joes_macros.json", "w") as f:
        f.write(clean_json)
        
    print("Success! Saved to trader_joes_macros.json")

# This is the trigger that actually executes the logic above
if __name__ == "__main__":
    asyncio.run(main())