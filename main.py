import asyncio
import os
import sys
import json
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

load_dotenv()

VFS_URL = os.getenv("VFS_URL", "https://visa.vfsglobal.com/tur/tr/fra/login")

# Callback to report status back to the dashboard
status_callback = None

async def report_status(message, level="info"):
    print(f"[{level.upper()}] {message}")
    if status_callback:
        await status_callback(message, level)

async def handle_cookies(page):
    try:
        await report_status("Çerez banner'ı kontrol ediliyor...")
        accept_btn = page.locator("#onetrust-accept-btn-handler")
        if await accept_btn.is_visible(timeout=5000):
            await accept_btn.click()
            await report_status("Çerezler kabul edildi.", "success")
    except Exception:
        pass

async def login(page, email, password):
    await report_status("VFS Giriş sayfası açılıyor...")
    try:
        response = await page.goto(VFS_URL, wait_until="domcontentloaded", timeout=60000)
        if response:
            await report_status(f"Sayfa yüklendi (Durum: {response.status})")
            if response.status == 403:
                await report_status("Hata: 403 Forbidden - Erişime izin verilmiyor (Cloudflare/Bot engeli olabilir).", "error")
        
        await handle_cookies(page)
        
        await report_status("Giriş formu bekleniyor...")
        # Try to wait for the selector more robustly
        await page.wait_for_selector('input[formcontrolname="username"]', timeout=45000)
        
        await report_status("Giriş bilgileri giriliyor...")
        await page.fill('input[formcontrolname="username"]', email)
        await page.wait_for_selector('input[formcontrolname="password"]', timeout=5000)
        await page.fill('input[formcontrolname="password"]', password)
        
        await page.click('button.mat-raised-button.mat-primary:has-text("Oturum aç"), button.mat-raised-button.mat-primary:has-text("Sign in")')
        await report_status("Bilgiler gönderildi, panel bekleniyor...")
        await page.wait_for_selector('button.mat-raised-button.mat-primary', timeout=30000)
        await report_status("Giriş başarılı.", "success")
    except Exception as e:
        await report_status(f"Giriş hatası: {e}", "error")
        await page.screenshot(path="login_error.png")
        raise e

async def start_booking(page):
    await report_status("Randevu süreci başlatılıyor...")
    try:
        booking_btn = page.locator('button.mat-raised-button.mat-primary:has-text("Yeni bir randevu al"), button.mat-raised-button.mat-primary:has-text("Start New Booking")')
        await booking_btn.wait_for(timeout=10000)
        await booking_btn.click()
        await report_status("Süreç başladı.", "success")
    except Exception as e:
        await report_status(f"Başlatma hatası: {e}", "error")
        raise e

async def process_applicant(page, ref_number):
    await report_status(f"Aday detayları giriliyor: {ref_number}")
    try:
        await page.wait_for_selector('input[formcontrolname="referenceNumber"]', timeout=15000)
        await page.fill('input[formcontrolname="referenceNumber"]', ref_number)
        
        await page.click('button.mat-raised-button.mat-primary:has-text("Kaydet"), button.mat-raised-button.mat-primary:has-text("Save")')
        await report_status(f"Referans {ref_number} kaydedildi.", "success")
        
        await page.click('button.mat-raised-button.mat-primary:has-text("Devam et"), button.mat-raised-button.mat-primary:has-text("Continue")')
    except Exception as e:
         await report_status(f"Aday ekleme hatası: {e}", "error")

# Updated handle_otp to accept code from outside
otp_queue = asyncio.Queue()

async def handle_otp(page):
    await report_status("OTP (Doğrulama Kodu) bekleniyor...", "warning")
    try:
        await page.wait_for_selector('input[formcontrolname="otp"], input[id="otp"]', timeout=10000)
        # Wait for value from the queue (from UI) or terminal
        print("\n[Dashboard] OTP bekleniyor...")
        otp_code = await otp_queue.get()
        await report_status(f"OTP giriliyor: {otp_code}")
        await page.fill('input[formcontrolname="otp"], input[id="otp"]', otp_code)
        await page.click('button.mat-raised-button.mat-primary:has-text("Doğrula"), button.mat-raised-button.mat-primary:has-text("Verify")')
        await report_status("OTP doğrulandı.", "success")
    except Exception:
        await report_status("OTP ekranı algılanmadı, geçiliyor...")

async def select_appointment(page):
    await report_status("Tarih/Saat seçimi bekleniyor...", "warning")
    try:
        await page.wait_for_selector('.mat-datepicker-content', timeout=20000)
        await report_status("Lütfen tarayıcıdan tarih ve saat seçin.")
        
        continue_btn = page.locator('button.mat-raised-button.mat-primary:has-text("Devam et"), button.mat-raised-button.mat-primary:has-text("Continue")')
        await continue_btn.wait_for(timeout=120000) # 2 min
        await continue_btn.click()
        await report_status("Zaman seçimi onaylandı.", "success")
    except Exception as e:
        await report_status(f"Zaman seçimi hatası: {e}", "error")

async def handle_payment(page):
    await report_status("Ödeme ekranına geçiliyor...")
    try:
        checkboxes = page.locator('mat-checkbox')
        count = await checkboxes.count()
        for i in range(count):
            await checkboxes.nth(i).click()
        
        await page.click('button.mat-raised-button.mat-primary:has-text("Devam et"), button.mat-raised-button.mat-primary:has-text("Continue")')
        await report_status("Ödeme bilgilerinizi manuel giriniz.", "warning")
    except Exception as e:
        await report_status(f"Ödeme adımı hatası: {e}", "error")

async def run_bot(email, password, ref_numbers, callback=None):
    global status_callback
    status_callback = callback
    
    await report_status("Bot başlatılıyor...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        
        # Proxy configuration from environment variables
        proxy_server = os.getenv("PROXY_SERVER")
        proxy_username = os.getenv("PROXY_USERNAME")
        proxy_password = os.getenv("PROXY_PASSWORD")
        
        proxy_config = None
        if proxy_server:
            proxy_config = {"server": proxy_server}
            if proxy_username and proxy_password:
                proxy_config["username"] = proxy_username
                proxy_config["password"] = proxy_password
            await report_status(f"Proxy aktif: {proxy_server}")

        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            proxy=proxy_config
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            await login(page, email, password)
            await start_booking(page)
            
            for ref in ref_numbers:
                await process_applicant(page, ref.strip())
            
            await handle_otp(page)
            await select_appointment(page)
            await handle_payment(page)

            await report_status("İşlem tamamlandı! Randevunuz alındı.", "success")
        except Exception as e:
            await report_status(f"Bot durduruldu: {e}", "error")
        finally:
            await asyncio.sleep(10)
            await browser.close()

if __name__ == "__main__":
    # Local run logic if called directly
    load_dotenv()
    email = os.getenv("VFS_EMAIL")
    password = os.getenv("VFS_PASSWORD")
    refs = os.getenv("REFERENCE_NUMBERS", "").split(",")
    
    # Simple terminal callback
    async def term_callback(msg, lvl):
        pass

    asyncio.run(run_bot(email, password, refs, term_callback))
