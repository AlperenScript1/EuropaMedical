import time
from pathlib import Path

from docx_export import docx_olustur
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from terminal_log import TerminalLog, konsol_hazirla

# True: Chrome penceresi açılmaz, sadece terminalde log görünür
ARKA_PLAN = True
PROJE_ADI = "Europa_medical_ihaleler"

VERI_KLASORU = Path(__file__).resolve().parent / "veriler"
log = TerminalLog()

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
        log.bilgi("Chrome arka planda çalışıyor...")
    else:
        options.add_argument("--start-maximized")
        log.bilgi("Chrome görünür modda çalışıyor...")

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
    log.bilgi("Sayfa Türkçe'ye çevriliyor...")
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
            log.basarili("Sayfa Türkçe'ye çevrildi.")
        else:
            log.uyari("Çeviri uygulandı, doğrulanamadı; devam ediliyor.")
        return

    from selenium.webdriver.common.action_chains import ActionChains
    import pyautogui

    pyautogui.FAILSAFE = False
    log.bilgi("Sayfa içeriğine sağ tıklanıyor...")
    try:
        hedef = driver.find_element(By.TAG_NAME, "main")
    except Exception:
        hedef = driver.find_element(By.TAG_NAME, "body")

    ActionChains(driver).move_to_element(hedef).context_click().perform()
    time.sleep(1)

    log.bilgi("Menüden 'Türkçe'ye çevir' seçiliyor...")
    for _ in range(9):
        pyautogui.press("down")
        time.sleep(0.1)
    pyautogui.press("enter")
    time.sleep(3)

    if cevirildi_mi(driver):
        log.basarili("Sayfa Türkçe'ye çevrildi.")
        return

    log.uyari("Sağ tık menüsüyle çeviri algılanamadı, Google çeviri deneniyor...")
    google_ile_turkceye_cevir(driver)
    if cevirildi_mi(driver):
        log.basarili("Sayfa Türkçe'ye çevrildi.")
    else:
        log.uyari("Çeviri tamamlandı ancak doğrulanamadı, devam ediliyor.")


def sayfayi_asagi_yukari_kaydir(driver):
    log.bilgi("Sayfa en alta kaydırılıyor...")
    driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
    time.sleep(1)
    log.bilgi("Sayfa en üste geri kaydırılıyor...")
    driver.execute_script("window.scrollTo(0, 0);")


def ilan_verilerini_al(driver, ilan_no):
    log.bilgi("İlan verileri toplanıyor...")
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

    log.bilgi(f"Word formatına dönüştürülüyor: {ilan_no}")
    docx_olustur(
        veri.get("summary", ""),
        veri.get("notice", ""),
        ilan_no,
        driver.current_url,
        docx_yolu,
    )

    log.basarili(f"Metin kaydedildi: {txt_yolu}")
    log.basarili(f"Word kaydedildi: {docx_yolu}")
    log.bilgi(f"Toplam karakter: {len(metin)}")
    return docx_yolu


def main():
    konsol_hazirla()
    url = "https://ted.europa.eu/en/browse-by-business-sector"
    driver = None
    son_hata = None

    try:
        log.basarili(f"{PROJE_ADI} başlatıldı.")
        driver = tarayici_baslat()
        driver.get(url)

        log.bilgi("Medical aranıyor...")
        arama_kutusu = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@id='ted-search-input-text']"))
        )
        arama_kutusu.click()
        arama_kutusu.send_keys("medical")

        ara_butonu = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "(//button[@id='ted-search-submit'])[1]"))
        )
        ara_butonu.click()
        log.bilgi("Arama sonuçları bekleniyor...")

        WebDriverWait(driver, 15).until(lambda d: "search/result" in d.current_url)
        log.bilgi("Sonuçlar yükleniyor, sayfa kaydırılıyor...")

        medical_bulundu = False
        bulunan_ilan_no = None
        for kaydirma_sayisi in range(40):
            medical_satir = driver.execute_script(MEDICAL_SATIR_JS)
            if medical_satir:
                bulunan_ilan_no = medical_satir.get("noticeNumber")
                log.basarili(f"Medical {bulunan_ilan_no} bulundu.")
                medical_bulundu = True
                break

            satir_sayisi = len(driver.find_elements(By.XPATH, "//table//tr[td]"))
            log.bilgi(
                f"Medical aranıyor... (adım {kaydirma_sayisi + 1}, yüklenen satır: {satir_sayisi})"
            )
            driver.execute_script("window.scrollBy(0, 250);")
            time.sleep(1.5)

        if not medical_bulundu:
            log.hata("Medical içeren ilan bulunamadı.")
            return

        if not bulunan_ilan_no:
            log.hata("Bulunan satırda ilan numarası tespit edilemedi.")
            return

        log.bilgi(f"İlan detayına giriliyor: {bulunan_ilan_no}")
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
        log.basarili(f"İlan detay sayfası açıldı: {bulunan_ilan_no}")

        sayfayi_turkceye_cevir(driver)
        sayfayi_asagi_yukari_kaydir(driver)
        ilan_verilerini_al(driver, bulunan_ilan_no)

        log.basarili("Tüm işlemler başarıyla tamamlandı.")

    except Exception as e:
        son_hata = e
        log.hata(f"Beklenmeyen hata: {e}")

    finally:
        if driver is not None:
            driver.quit()
        log.hata_kaydet(son_hata)
        log.basarili(f"{PROJE_ADI} durduruldu.")


if __name__ == "__main__":
    main()
