import time
from pathlib import Path

from docx_export import docx_olustur
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# True: Chrome penceresi açılmaz, sadece terminalde log görünür
ARKA_PLAN = True

VERI_KLASORU = Path(__file__).resolve().parent / "veriler"

MEDICAL_SATIR_JS = """
const rows = [...document.querySelectorAll('table tr')].filter(
    row => row.querySelectorAll('td').length > 0
);
for (const row of rows) {
    if (!/medical/i.test(row.innerText)) continue;
    const rect = row.getBoundingClientRect();
    const gorunur = rect.top >= 0 && rect.bottom <= window.innerHeight;
    if (!gorunur) continue;

    const link = row.querySelector('a[href*="/notice/-/detail/"]');
    return {
        rowText: row.innerText.trim().slice(0, 150),
        noticeNumber: link ? link.textContent.trim() : null,
    };
}
return null;
"""

ILAN_VERISI_JS = """
function accordionMetni(id) {
    const acc = document.getElementById(id);
    if (!acc) return null;
    const details = acc.querySelector('[class*="AccordionDetails"]');
    return (details || acc).innerText.trim();
}

return {
    summary: accordionMetni('summary-accordion'),
    notice: accordionMetni('notice-accordion'),
};
"""

def tarayici_baslat():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=tr-TR")

    if ARKA_PLAN:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        print("[BİLGİ] Chrome arka planda (headless) çalışıyor.", flush=True)
    else:
        options.add_argument("--start-maximized")
        print("[BİLGİ] Chrome görünür modda çalışıyor.", flush=True)

    driver = webdriver.Chrome(options=options)
    if ARKA_PLAN:
        driver.set_window_size(1920, 1080)
    else:
        driver.maximize_window()
    return driver


def cevirildi_mi(driver):
    html = driver.find_element(By.TAG_NAME, "html")
    sinif = html.get_attribute("class") or ""
    lang = html.get_attribute("lang") or ""
    return "translated" in sinif or lang.startswith("tr")


def google_ile_turkceye_cevir(driver):
    print("[BİLGİ] Google çeviri uygulanıyor...", flush=True)
    driver.execute_script(
        """
        if (!document.getElementById('google_translate_element')) {
            const div = document.createElement('div');
            div.id = 'google_translate_element';
            div.style.display = 'none';
            document.body.prepend(div);
        }
        window.googleTranslateElementInit = function() {
            new google.translate.TranslateElement({
                pageLanguage: 'en',
                includedLanguages: 'tr',
                autoDisplay: false
            }, 'google_translate_element');
        };
        if (!document.getElementById('google-translate-script')) {
            const script = document.createElement('script');
            script.id = 'google-translate-script';
            script.src = 'https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
            document.head.appendChild(script);
        } else {
            window.googleTranslateElementInit();
        }
        """
    )
    time.sleep(3)
    driver.execute_script(
        """
        const select = document.querySelector('.goog-te-combo');
        if (select) {
            select.value = 'tr';
            select.dispatchEvent(new Event('change'));
        }
        """
    )
    time.sleep(4)


def sayfayi_turkceye_cevir(driver):
    if ARKA_PLAN:
        google_ile_turkceye_cevir(driver)
        if cevirildi_mi(driver):
            print("[OK] Sayfa Türkçe'ye çevrildi.", flush=True)
        else:
            print("[UYARI] Çeviri uygulandı, doğrulanamadı; devam ediliyor.", flush=True)
        return

    from selenium.webdriver.common.action_chains import ActionChains
    import pyautogui

    pyautogui.FAILSAFE = False
    print("[BİLGİ] Sayfa içeriğine sağ tıklanıyor...", flush=True)
    try:
        hedef = driver.find_element(By.TAG_NAME, "main")
    except Exception:
        hedef = driver.find_element(By.TAG_NAME, "body")

    ActionChains(driver).move_to_element(hedef).context_click().perform()
    time.sleep(1)

    print("[BİLGİ] Menüden 'Türkçe'ye çevir' seçiliyor...", flush=True)
    for _ in range(9):
        pyautogui.press("down")
        time.sleep(0.1)
    pyautogui.press("enter")
    time.sleep(3)

    if cevirildi_mi(driver):
        print("[OK] Sayfa Türkçe'ye çevrildi.", flush=True)
        return

    print("[BİLGİ] Sağ tık menüsüyle çeviri algılanamadı, Google çeviri deneniyor...", flush=True)
    google_ile_turkceye_cevir(driver)
    if cevirildi_mi(driver):
        print("[OK] Sayfa Türkçe'ye çevrildi.", flush=True)
    else:
        print("[UYARI] Çeviri tamamlandı ancak doğrulanamadı, devam ediliyor.", flush=True)


def sayfayi_asagi_yukari_kaydir(driver):
    print("[BİLGİ] Sayfa en alta kaydırılıyor...")
    driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
    time.sleep(1)
    print("[BİLGİ] Sayfa en üste geri kaydırılıyor...")
    driver.execute_script("window.scrollTo(0, 0);")


def ilan_verilerini_al(driver, ilan_no):
    print("[BİLGİ] İlan verileri toplanıyor (header, footer, diller/formatlar hariç)...")
    veri = driver.execute_script(ILAN_VERISI_JS)

    if not veri or (not veri.get("summary") and not veri.get("notice")):
        raise RuntimeError("İlan verisi bulunamadı.")

    bolumler = []
    if veri.get("summary"):
        bolumler.append("=== ÖZET ===\n" + veri["summary"])
    if veri.get("notice"):
        bolumler.append("=== İLAN ===\n" + veri["notice"])

    metin = "\n\n".join(bolumler)
    VERI_KLASORU.mkdir(exist_ok=True)
    txt_yolu = VERI_KLASORU / f"{ilan_no}.txt"
    docx_yolu = VERI_KLASORU / f"{ilan_no}.docx"
    txt_yolu.write_text(metin, encoding="utf-8")

    docx_olustur(
        veri.get("summary", ""),
        veri.get("notice", ""),
        ilan_no,
        driver.current_url,
        docx_yolu,
    )

    print(f"[OK] Metin kaydedildi: {txt_yolu}")
    print(f"[OK] Word kaydedildi: {docx_yolu}")
    print(f"[BİLGİ] Toplam karakter: {len(metin)}")
    return docx_yolu


url = "https://ted.europa.eu/en/browse-by-business-sector"

try:
    driver = tarayici_baslat()
    driver.get(url)

    arama_kutusu = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//input[@id='ted-search-input-text']"))
    )
    arama_kutusu.click()
    arama_kutusu.send_keys("medical")
    print("[OK] Arama kutusuna 'medical' yazıldı.")

    ara_butonu = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "(//button[@id='ted-search-submit'])[1]"))
    )
    ara_butonu.click()
    print("[OK] Ara butonuna tıklandı. Sonuçlar bekleniyor...")

    WebDriverWait(driver, 15).until(lambda d: "search/result" in d.current_url)
    print("[OK] Arama sonuç sayfasına geçildi.")

    print("[BİLGİ] 'Medical' görünene kadar sayfa yavaşça aşağı kaydırılacak...")

    medical_bulundu = False
    bulunan_ilan_no = None
    for kaydirma_sayisi in range(40):
        medical_satir = driver.execute_script(MEDICAL_SATIR_JS)
        if medical_satir:
            print(
                f"[BAŞARILI] 'Medical' ekranda göründü! Kaydırma durduruldu. "
                f"(Adım: {kaydirma_sayisi + 1})"
            )
            print(f"[BİLGİ] Bulunan satır: {medical_satir['rowText']}")
            bulunan_ilan_no = medical_satir.get("noticeNumber")
            medical_bulundu = True
            break

        satir_sayisi = len(driver.find_elements(By.XPATH, "//table//tr[td]"))
        print(
            f"-> Henüz ekranda görünmedi, aşağı kaydırılıyor... "
            f"(Adım {kaydirma_sayisi + 1}, yüklenen satır: {satir_sayisi})"
        )
        driver.execute_script("window.scrollBy(0, 250);")
        time.sleep(1.5)

    if not medical_bulundu:
        print("[HATA] Sayfa kaydırılmasına rağmen ekranda 'Medical' içeren satır bulunamadı.")
    elif not bulunan_ilan_no:
        print("[HATA] Bulunan satırda ilan numarası linki tespit edilemedi.")
    else:
        print(f"[BİLGİ] İlan linkine tıklanıyor: {bulunan_ilan_no}")
        ilan_linki = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, f"//table//tr[td]//a[normalize-space()='{bulunan_ilan_no}']")
            )
        )
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
            ilan_linki,
        )

        WebDriverWait(driver, 15).until(
            lambda d: "/notice/-/detail/" in d.current_url
        )
        print(f"[OK] İlan detay sayfasına girildi: {driver.current_url}")

        sayfayi_turkceye_cevir(driver)
        sayfayi_asagi_yukari_kaydir(driver)
        ilan_verilerini_al(driver, bulunan_ilan_no)

        print("[OK] İşlem tamamlandı.")

except Exception as e:
    print(f"Bir hata oluştu: {e}", flush=True)

finally:
    if "driver" in locals():
        driver.quit()
    print("[BİTTİ] Test sonlandırıldı.", flush=True)
