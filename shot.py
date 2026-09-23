"""Screenshot the web UI for proof. python shot.py <url> <out.png> [query] [mode]"""
import sys, time
from playwright.sync_api import sync_playwright

url, out = sys.argv[1], sys.argv[2]
query = sys.argv[3] if len(sys.argv) > 3 else ""
mode = sys.argv[4] if len(sys.argv) > 4 else "hybrid"
with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1280, "height": 1400}, device_scale_factor=2)
    page.goto(url, wait_until="networkidle")
    if query:
        page.select_option("#mode", mode)
        page.fill("#q", query)
        page.click("button")
        page.wait_for_function("document.getElementById('meta').textContent.includes('ผลลัพธ์')", timeout=60000)
        time.sleep(0.4)
    page.screenshot(path=out, full_page=False)
    b.close()
print("shot", out)
