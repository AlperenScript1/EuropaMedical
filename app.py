import ctypes
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from cevir import CeviriBasarisizError, metin_turkce_mi, metni_turkceye_cevir
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
PID_DOSYASI = Path(__file__).resolve().parent / "calisma.pid"
log = TerminalLog()

_driver = None
_kapatiliyor = False
_console_handler_ref = None
_job_handle = None
_parent_pid: int | None = None
_arama_sonuc_url: str | None = None

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


def _pid_kaydet():
    PID_DOSYASI.write_text(str(os.getpid()), encoding="utf-8")


def _pid_sil():
    if PID_DOSYASI.exists():
        PID_DOSYASI.unlink()


def _chrome_kapat():
    global _driver
    if _driver is None:
        return

    try:
        servis = getattr(_driver, "service", None)
        if servis and servis.process and servis.process.poll() is None:
            pid = servis.process.pid
            os.system(f"taskkill /PID {pid} /T /F >nul 2>&1")
            servis.process.kill()
    except Exception:
        pass

    try:
        _driver.quit()
    except Exception:
        pass

    _driver = None


def _temiz_kapat(zorla_cikis: bool = True):
    """Terminal kapanınca veya Ctrl+C ile Chrome dahil her şeyi durdur."""
    global _kapatiliyor

    if _kapatiliyor:
        return
    _kapatiliyor = True

    try:
        log.bilgi("Program durduruluyor...")
    except Exception:
        print("[BİLGİ] Program durduruluyor...", flush=True)

    _chrome_kapat()
    _pid_sil()

    try:
        log.basarili(f"{PROJE_ADI} durduruldu.")
    except Exception:
        print(f"[OK] {PROJE_ADI} durduruldu.", flush=True)

    if zorla_cikis:
        os._exit(0)


def _sinyal_yakala(*_args):
    _temiz_kapat()


def _windows_konsol_kapat_handler(ctrl_type):
    # 0=Ctrl+C, 1=Ctrl+Break, 2=terminal X, 5=logoff, 6=shutdown
    if ctrl_type not in (0, 1, 2, 5, 6):
        return False

    # X ile kapatmada handler hemen cikmali; thread ile donmek Python'u yetim birakir.
    if ctrl_type in (2, 5, 6):
        _temiz_kapat()
        return True

    threading.Thread(target=_temiz_kapat, daemon=True).start()
    return True


def _windows_islem_grubu_kur():
    """Python kapanınca Chrome/chromedriver da kapansın."""
    global _job_handle
    if sys.platform != "win32":
        return

    kernel32 = ctypes.windll.kernel32

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    _job_handle = kernel32.CreateJobObjectW(None, None)
    if not _job_handle:
        return

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(
        _job_handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )

    mevcut = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, os.getpid())
    if mevcut:
        kernel32.AssignProcessToJobObject(_job_handle, mevcut)
        kernel32.CloseHandle(mevcut)


def _process_joba_ekle(pid: int) -> None:
    """Chromedriver gibi alt surecleri de job'a bagla; terminal kapaninca onlar da kapansin."""
    global _job_handle
    if sys.platform != "win32" or not _job_handle or not pid:
        return

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32
    surec = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if surec:
        kernel32.AssignProcessToJobObject(_job_handle, surec)
        kernel32.CloseHandle(surec)


def _parent_pid_al() -> int | None:
    if sys.platform != "win32":
        return None

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = -1
    kernel32 = ctypes.windll.kernel32

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_char * 260),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return None

    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        mevcut_pid = os.getpid()
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.th32ProcessID == mevcut_pid:
                return entry.th32ParentProcessID
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
        return None
    finally:
        kernel32.CloseHandle(snapshot)


def _process_yasiyor_mu(pid: int) -> bool:
    if sys.platform != "win32":
        return True
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    surec = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if surec:
        kernel32.CloseHandle(surec)
        return True
    return False


def _kapatma_kontrol() -> bool:
    """Terminal veya calistiran pencere kapandiysa programi durdur."""
    if _kapatiliyor:
        return False
    if sys.platform != "win32":
        return True

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd and ctypes.windll.user32.IsWindow(hwnd) == 0:
        _temiz_kapat()
        return False

    if _parent_pid and not _process_yasiyor_mu(_parent_pid):
        _temiz_kapat()
        return False

    return True


def _konsol_penceresi_kapandi_mi(hwnd: int) -> bool:
    if not hwnd:
        return False
    return ctypes.windll.user32.IsWindow(hwnd) == 0


def _terminal_kapanis_izle():
    """Terminal sekmesi/carpisi kapaninca programi durdur."""

    def _pencere_izle():
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        while not _kapatiliyor:
            time.sleep(0.25)
            if _konsol_penceresi_kapandi_mi(hwnd):
                _temiz_kapat()
                return

    def _stdin_izle():
        if sys.stdin is None or not sys.stdin.isatty():
            return
        try:
            while not _kapatiliyor:
                if sys.stdin.read(1) == "":
                    _temiz_kapat()
                    return
        except Exception:
            if not _kapatiliyor:
                _temiz_kapat()

    def _parent_izle():
        if not _parent_pid:
            return
        while not _kapatiliyor:
            time.sleep(0.2)
            if not _process_yasiyor_mu(_parent_pid):
                _temiz_kapat()
                return

    threading.Thread(target=_pencere_izle, daemon=True).start()
    threading.Thread(target=_stdin_izle, daemon=True).start()
    threading.Thread(target=_parent_izle, daemon=True).start()


def sinyalleri_ayarla():
    global _console_handler_ref, _parent_pid

    signal.signal(signal.SIGINT, _sinyal_yakala)
    signal.signal(signal.SIGTERM, _sinyal_yakala)
    _windows_islem_grubu_kur()
    _parent_pid = _parent_pid_al()

    if sys.platform == "win32":
        _console_handler_ref = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)(
            _windows_konsol_kapat_handler
        )
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler_ref, True)

    threading.Thread(target=_terminal_kapanis_izle, daemon=True).start()


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
    servis = getattr(driver, "service", None)
    if servis and servis.process and servis.process.pid:
        _process_joba_ekle(servis.process.pid)
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
    except CeviriBasarisizError as e:
        raise RuntimeError(f"Çevirilemedi: {ilan_no}") from e

    if not metin_turkce_mi(f"{ozet}\n{ilan}"):
        raise RuntimeError(f"Çevirilemedi: {ilan_no}")

    log.basarili("Metin Türkçe'ye çevrildi.")

    bugun_klasoru = bugunun_klasoru()
    docx_yolu = bugun_klasoru / f"{ilan_no}.docx"

    log.bilgi(f"Word formatına dönüştürülüyor: {ilan_no}")
    docx_olustur(ozet, ilan, ilan_no, driver.current_url, docx_yolu)

    log.basarili(f"Word kaydedildi: {docx_yolu}")
    return docx_yolu


def sonuclara_don(driver, son_ilan_no: str | None = None) -> bool:
    global _arama_sonuc_url
    log.bilgi("Arama sonuçlarına dönülüyor...")

    for deneme in range(1, 4):
        try:
            if deneme == 1:
                driver.back()
            elif _arama_sonuc_url:
                log.uyari("Geri dönüş başarısız, arama sayfası yeniden açılıyor...")
                driver.get(_arama_sonuc_url)
            else:
                driver.back()

            WebDriverWait(driver, 20).until(
                lambda d: "search/result" in d.current_url
            )
            sonuc_tablosu_bekle(driver)
            break
        except TimeoutException:
            if deneme < 3:
                log.uyari(
                    f"Arama tablosu yüklenemedi, tekrar deneniyor ({deneme}/3)..."
                )
                time.sleep(2)
            else:
                log.hata("Arama sonuçlarına dönülemedi; tablo yüklenmedi.")
                return False

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

    return True


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
        if not _kapatma_kontrol():
            return None
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
    sinyalleri_ayarla()
    _pid_kaydet()

    url = "https://ted.europa.eu/en/browse-by-business-sector"
    global _driver
    son_hata = None

    try:
        log.basarili(f"{PROJE_ADI} başlatıldı.")
        log.bilgi_mavi(BASLANGIC_MESAJI)
        bugun = bugunun_klasoru()
        bugun_tarihi = bugunun_ted_tarihi()
        log.bilgi(f"Bugünün klasörü: {bugun.name}")
        log.bilgi(f"Sadece bugünün ihaleleri alınacak: {bugun_tarihi}")
        _driver = tarayici_baslat()  # Chrome açılır
        _driver.get(url)

        log.bilgi("Medical aranıyor...")
        arama_kutusu = WebDriverWait(_driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@id='ted-search-input-text']"))
        )
        arama_kutusu.click()
        arama_kutusu.send_keys("medical")

        ara_butonu = WebDriverWait(_driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "(//button[@id='ted-search-submit'])[1]"))
        )
        ara_butonu.click()
        log.bilgi("Arama sonuçları bekleniyor...")

        WebDriverWait(_driver, 15).until(lambda d: "search/result" in d.current_url)
        _arama_sonuc_url = _driver.current_url
        log.bilgi("Sonuçlar yüklendi, medical ilanlar taranıyor...")
        sonuc_tablosu_bekle(_driver)

        atlanan_ilanlar = []
        kaydedilen_sayisi = 0
        sayfa_no = 1
        eski_tarihe_ulasildi = False

        while True:
            if not _kapatma_kontrol():
                return
            log.bilgi(f"Sayfa {sayfa_no} taranıyor ({bugun_tarihi})...")

            while True:
                if not _kapatma_kontrol():
                    return
                bulunan_ilan_no = sonraki_medical_ilan_bul(
                    _driver, atlanan_ilanlar, bugun_tarihi
                )
                if bulunan_ilan_no is ESKI_TARIH:
                    eski_tarihe_ulasildi = True
                    break
                if not bulunan_ilan_no:
                    break

                ilana_git(_driver, bulunan_ilan_no)
                try:
                    ilan_verilerini_al(_driver, bulunan_ilan_no)
                except RuntimeError as e:
                    mesaj = str(e)
                    if "İlan verisi bulunamadı" in mesaj:
                        log.uyari(
                            f"{bulunan_ilan_no} atlandı: detay sayfasında veri yok."
                        )
                        atlanan_ilanlar.append(bulunan_ilan_no)
                        if not sonuclara_don(_driver, bulunan_ilan_no):
                            return
                        continue
                    if "Çevirilemedi" in mesaj:
                        log.uyari(
                            f"{bulunan_ilan_no} atlandı: Türkçe'ye çevrilemedi."
                        )
                        atlanan_ilanlar.append(bulunan_ilan_no)
                        if not sonuclara_don(_driver, bulunan_ilan_no):
                            return
                        continue
                    raise

                atlanan_ilanlar.append(bulunan_ilan_no)
                kaydedilen_sayisi += 1

                log.bilgi("Sonraki medical ilan aranıyor...")
                if not sonuclara_don(_driver, bulunan_ilan_no):
                    return

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

            if not sonraki_sayfaya_gec(_driver, sayfa_no + 1):
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
            _driver.execute_script("window.scrollTo(0, 0);")
            log.bilgi(f"Sayfa {sayfa_no}'de medical ilanlar taranıyor...")

    except Exception as e:
        son_hata = e
        log.hata(f"Beklenmeyen hata: {e}")

    finally:
        if not _kapatiliyor:
            _chrome_kapat()
            _pid_sil()
            log.hata_kaydet(son_hata)
            log.basarili(f"{PROJE_ADI} durduruldu.")


if __name__ == "__main__":
    main()
