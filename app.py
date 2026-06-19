import time
from datetime import datetime
from pathlib import Path

from cevir import metin_turkce_mi, metni_turkceye_cevir
from docx_export import docx_olustur
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from terminal_log import TerminalLog, konsol_hazirla

# Chrome görünürlük ayarı:
#   True  -> headless (pencere açılmaz, sadece terminalde log)
#   False -> Chrome penceresi ekranda görünür
ARKA_PLAN = False
PROJE_ADI = "Europa_medical_ihaleler"

VERI_KLASORU = Path(__file__).resolve().parent / "Europa_medical_ihaleler_Dosyalari"
log = TerminalLog()

MEDICAL_SATIRLARI_TOPLA_JS = """
const atlananlar = new Set(arguments[0] || []);
const bugun = arguments[1] || '';

function tarihKarsilastir(tarihStr, bugunStr) {
    const parse = s => {
        const [d, m, y] = s.split('/').map(Number);
        return new Date(y, m - 1, d).getTime();
    };
    return parse(tarihStr) - parse(bugunStr);
}

const notices = [];
const seen = new Set();
let eskiTarih = false;
let eskiTarihStr = null;

for (const row of document.querySelectorAll('table tr')) {
    const cells = [...row.querySelectorAll('td')];
    if (cells.length < 5) continue;

    const pubDate = cells[4].textContent.trim();
    if (!/^\\d{2}\\/\\d{2}\\/\\d{4}$/.test(pubDate)) continue;

    const karsilastirma = tarihKarsilastir(pubDate, bugun);
    if (karsilastirma < 0) {
        eskiTarih = true;
        eskiTarihStr = pubDate;
        continue;
    }
    if (karsilastirma > 0) continue;
    if (!/medical/i.test(row.innerText)) continue;

    const link = row.querySelector('a[href*="/notice/-/detail/"]');
    const noticeNumber = link ? link.textContent.trim() : null;
    if (!noticeNumber || atlananlar.has(noticeNumber) || seen.has(noticeNumber)) continue;

    seen.add(noticeNumber);
    notices.push(noticeNumber);
}

return { notices, eskiTarih, eskiTarihStr };
"""

ESKI_TARIH = object()

BASLANGIC_MESAJI = (
    "Dosyalar günlük klasörlerde biriktirilir. Daha önce alınan ilanlar tekrar alınmaz."
)

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
    """Chrome burada açılır: webdriver.Chrome(...) satırı tarayıcıyı başlatır."""
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

    # --- CHROME AÇILIYOR ---
    driver = webdriver.Chrome(options=options)
    if ARKA_PLAN:
        driver.set_window_size(1920, 1080)
    else:
        driver.maximize_window()
    return driver


def bugunun_ted_tarihi() -> str:
    """TED tablosundaki yayın tarihi formatı: GG/AA/YYYY"""
    return datetime.now().strftime("%d/%m/%Y")


def bugunun_klasoru() -> Path:
    tarih = datetime.now().strftime("%d.%m.%Y")
    klasor = VERI_KLASORU / f"{tarih}_Medical_Dosyalari"
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor


def ilan_kayitli_mi(ilan_no: str) -> bool:
    if not VERI_KLASORU.exists():
        return False
    return any(VERI_KLASORU.rglob(f"{ilan_no}.docx"))


def sayfayi_asagi_yukari_kaydir(driver):
    driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
    time.sleep(1)
    driver.execute_script("window.scrollTo(0, 0);")


def ilan_verilerini_al(driver, ilan_no):
    log.bilgi("İlan verileri toplanıyor...")
    sayfayi_asagi_yukari_kaydir(driver)
    veri = driver.execute_script(ILAN_VERISI_JS)

    if not veri or (not veri.get("summary") and not veri.get("notice")):
        raise RuntimeError("İlan verisi bulunamadı.")

    ozet = veri.get("summary", "")
    ilan = veri.get("notice", "")

    log.bilgi("Metin Türkçe'ye çevriliyor...")
    try:
        ozet = metni_turkceye_cevir(ozet) if ozet else ozet
        ilan = metni_turkceye_cevir(ilan) if ilan else ilan
    except Exception as e:
        log.hata(f"Çeviri başarısız: {e}")
        raise RuntimeError(f"Çeviri başarısız ({ilan_no})") from e

    if metin_turkce_mi(f"{ozet}\n{ilan}"):
        log.basarili("Metin Türkçe'ye çevrildi.")
    else:
        log.uyari("Çeviri tamamlanamadı; Word dosyası İngilizce kaydedilebilir.")

    bugun_klasoru = bugunun_klasoru()
    docx_yolu = bugun_klasoru / f"{ilan_no}.docx"

    log.bilgi(f"Word formatına dönüştürülüyor: {ilan_no}")
    docx_olustur(ozet, ilan, ilan_no, driver.current_url, docx_yolu)

    log.basarili(f"Word kaydedildi: {docx_yolu}")
    return docx_yolu


def sonuclara_don(driver, son_ilan_no: str | None = None):
    log.bilgi("Arama sonuçlarına dönülüyor...")
    driver.back()
    WebDriverWait(driver, 15).until(lambda d: "search/result" in d.current_url)
    sonuc_tablosu_bekle(driver)

    if son_ilan_no:
        try:
            ilan_linki = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, f"//table//tr[td]//a[normalize-space()='{son_ilan_no}']")
                )
            )
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", ilan_linki
            )
            time.sleep(1)
        except TimeoutException:
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
    else:
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)


def sonuc_tablosu_bekle(driver):
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH, "//table//tr[td]"))
    )
    time.sleep(1)


def sonraki_sayfaya_gec(driver, sayfa_no: int) -> bool:
    """Arama sonuçlarında belirtilen sayfa numarasına geçer. Buton yoksa False döner."""
    xpath = (
        f"(//button[@aria-label='Go to the next page'][normalize-space()='{sayfa_no}'])[1]"
    )
    log.bilgi(f"Sayfa {sayfa_no}'ye geçiliyor...")
    try:
        buton = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
    except TimeoutException:
        return False

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
        buton,
    )
    sonuc_tablosu_bekle(driver)
    driver.execute_script("window.scrollTo(0, 0);")
    log.basarili(f"Sayfa {sayfa_no} yüklendi.")
    return True


def tabloyu_asagi_kaydir(driver) -> int:
    return driver.execute_script(
        """
        const before = window.scrollY;
        window.scrollTo(0, document.documentElement.scrollHeight);
        return before;
        """
    )


def sonraki_medical_ilan_bul(driver, atlanan_ilanlar, bugun_tarihi: str):
    """Sayfadaki tüm sonuçları aşağı kaydırarak tarar (TED sayfa başına ~100 ilan)."""
    eski_tarih_goruldu = False
    eski_tarih_str = None
    sabit_kaydirma = 0
    onceki_scroll = -1

    while sabit_kaydirma < 4:
        sonuc = driver.execute_script(
            MEDICAL_SATIRLARI_TOPLA_JS, atlanan_ilanlar, bugun_tarihi
        )
        if sonuc.get("eskiTarih"):
            eski_tarih_goruldu = True
            eski_tarih_str = sonuc.get("eskiTarihStr")

        for ilan_no in sonuc.get("notices", []):
            if ilan_kayitli_mi(ilan_no):
                if ilan_no not in atlanan_ilanlar:
                    log.bilgi(f"{ilan_no} daha önce yapılmış, atlanıyor...")
                    atlanan_ilanlar.append(ilan_no)
                continue

            log.basarili(f"Medical {ilan_no} bulundu ({bugun_tarihi}).")
            return ilan_no

        satir_sayisi = len(driver.find_elements(By.XPATH, "//table//tr[td]"))
        scroll_y = driver.execute_script("return window.scrollY")
        tabloyu_asagi_kaydir(driver)
        time.sleep(1.5)
        yeni_scroll = driver.execute_script("return window.scrollY")

        log.bilgi(
            f"Sayfa taranıyor... (satır: {satir_sayisi}, kaydırma: {scroll_y} -> {yeni_scroll})"
        )

        if yeni_scroll == onceki_scroll:
            sabit_kaydirma += 1
        else:
            sabit_kaydirma = 0
        onceki_scroll = yeni_scroll

    if eski_tarih_goruldu:
        log.bilgi(
            f"Önceki günün ihaleleri başladı ({eski_tarih_str}). "
            f"Sadece {bugun_tarihi} tarihli ilanlar alınır."
        )
        return ESKI_TARIH

    return None


def ilana_git(driver, ilan_no):
    log.bilgi(f"İlan detayına giriliyor: {ilan_no}")
    ilan_linki = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located(
            (By.XPATH, f"//table//tr[td]//a[normalize-space()='{ilan_no}']")
        )
    )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();",
        ilan_linki,
    )
    WebDriverWait(driver, 15).until(lambda d: "/notice/-/detail/" in d.current_url)
    log.basarili(f"İlan detay sayfası açıldı: {ilan_no}")


def main():
    konsol_hazirla()
    url = "https://ted.europa.eu/en/browse-by-business-sector"
    driver = None
    son_hata = None

    try:
        log.basarili(f"{PROJE_ADI} başlatıldı.")
        log.bilgi_mavi(BASLANGIC_MESAJI)
        bugun = bugunun_klasoru()
        bugun_tarihi = bugunun_ted_tarihi()
        log.bilgi(f"Bugünün klasörü: {bugun.name}")
        log.bilgi(f"Sadece bugünün ihaleleri alınacak: {bugun_tarihi}")
        driver = tarayici_baslat()  # Chrome açılır
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
        log.bilgi("Sonuçlar yüklendi, medical ilanlar taranıyor...")
        sonuc_tablosu_bekle(driver)

        atlanan_ilanlar = []
        kaydedilen_sayisi = 0
        sayfa_no = 1
        eski_tarihe_ulasildi = False

        while True:
            log.bilgi(f"Sayfa {sayfa_no} taranıyor ({bugun_tarihi})...")

            while True:
                bulunan_ilan_no = sonraki_medical_ilan_bul(
                    driver, atlanan_ilanlar, bugun_tarihi
                )
                if bulunan_ilan_no is ESKI_TARIH:
                    eski_tarihe_ulasildi = True
                    break
                if not bulunan_ilan_no:
                    break

                ilana_git(driver, bulunan_ilan_no)
                try:
                    ilan_verilerini_al(driver, bulunan_ilan_no)
                except RuntimeError as e:
                    if "İlan verisi bulunamadı" in str(e):
                        log.uyari(
                            f"{bulunan_ilan_no} atlandı: detay sayfasında veri yok."
                        )
                        atlanan_ilanlar.append(bulunan_ilan_no)
                        sonuclara_don(driver, bulunan_ilan_no)
                        continue
                    raise

                atlanan_ilanlar.append(bulunan_ilan_no)
                kaydedilen_sayisi += 1

                log.bilgi("Sonraki medical ilan aranıyor...")
                sonuclara_don(driver, bulunan_ilan_no)

            if eski_tarihe_ulasildi:
                if kaydedilen_sayisi > 0:
                    log.basarili(
                        f"{kaydedilen_sayisi} ilan kaydedildi. "
                        f"Bugünün ({bugun_tarihi}) tüm ihaleleri alındı."
                    )
                else:
                    log.basarili(
                        f"Bugünün ({bugun_tarihi}) tüm ihaleleri alındı."
                    )
                break

            log.bilgi(f"Sayfa {sayfa_no} tamamlandı, sonraki sayfa deneniyor...")

            if not sonraki_sayfaya_gec(driver, sayfa_no + 1):
                if kaydedilen_sayisi > 0:
                    log.basarili(
                        f"{kaydedilen_sayisi} ilan kaydedildi. "
                        f"Bugünün ({bugun_tarihi}) tüm ihaleleri alındı."
                    )
                elif atlanan_ilanlar:
                    log.basarili(f"Bugünün ({bugun_tarihi}) tüm ihaleleri alındı.")
                else:
                    log.hata("Medical içeren ilan bulunamadı.")
                break

            sayfa_no += 1
            driver.execute_script("window.scrollTo(0, 0);")
            log.bilgi(f"Sayfa {sayfa_no}'de medical ilanlar taranıyor...")

    except Exception as e:
        son_hata = e
        log.hata(f"Beklenmeyen hata: {e}")

    finally:
        if driver is not None:
            # --- CHROME KAPATILIYOR ---
            driver.quit()
        log.hata_kaydet(son_hata)
        log.basarili(f"{PROJE_ADI} durduruldu.")


if __name__ == "__main__":
    main()
