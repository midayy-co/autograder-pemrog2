"""Autograder mini project Pertemuan 3: Konverter Kurs.

Menjalankan kurs.py + main.py praktikan dengan `requests` palsu dan `input()`
otomatis, lalu memberi nilai per poin spesifikasi (total 100).
Dipakai di halaman web (Pyodide) dan bisa juga dijalankan langsung:

    python grader.py folder_berisi_kurs_dan_main
"""

import io
import json
import os
import random
import re
import sys
import tempfile
import time
import types

LINE_LIMIT = 300_000   # batas baris dieksekusi per skenario (cegah infinite loop)
INPUT_LIMIT = 30       # batas jumlah input() per skenario


# ---------------------------------------------------------------- sentinels
class _Stop(BaseException):
    """Dipakai grader untuk menghentikan program praktikan."""


class LoopTerlalu(_Stop):
    pass


class TidakBerhenti(_Stop):
    pass


class InputHabis(_Stop):
    pass


# Sekali grader memutuskan berhenti, setiap baris berikutnya ikut melempar
# sentinel ini, jadi `except:` polos milik praktikan tidak bisa menelannya.
_HENTIKAN = [None]


def _hentikan(exc):
    _HENTIKAN[0] = exc
    raise exc


# ---------------------------------------------------------------- fake requests
def buat_requests_palsu(rates, internet_mati=False):
    mod = types.ModuleType("requests")
    exc = types.ModuleType("requests.exceptions")

    class RequestException(OSError):
        pass

    class ConnectionError_(RequestException):
        pass

    class Timeout(RequestException):
        pass

    class HTTPError(RequestException):
        pass

    ConnectionError_.__name__ = "ConnectionError"
    for k, v in {"RequestException": RequestException, "ConnectionError": ConnectionError_,
                 "Timeout": Timeout, "HTTPError": HTTPError,
                 "ConnectTimeout": Timeout, "ReadTimeout": Timeout}.items():
        setattr(exc, k, v)
        setattr(mod, k, v)
    mod.exceptions = exc

    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self.ok = status < 400
            self._payload = payload
            self.text = json.dumps(payload)
            self.content = self.text.encode()

        def json(self):
            return json.loads(self.text)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPError(f"{self.status_code} Client Error")

    def get(url, *args, **kwargs):
        mod.jumlah_panggilan += 1
        if internet_mati:
            raise ConnectionError_("Failed to establish a new connection: [Errno -3] Temporary failure in name resolution")
        m = re.search(r"/latest/([A-Za-z]+)", str(url))
        base = m.group(1).upper() if m else "USD"
        if base not in rates:
            return Response(404, {"result": "error", "error-type": "unsupported-code"})
        b = rates[base]
        konversi = {k: round(v / b, 6) for k, v in rates.items()}
        return Response(200, {"result": "success", "base_code": base,
                              "time_last_update_utc": "Wed, 21 Oct 2026 00:02:31 +0000",
                              "rates": konversi})

    mod.get = get
    mod.jumlah_panggilan = 0
    return mod


def kurs_acak():
    return {
        "USD": 1.0,
        "IDR": round(random.uniform(15000, 19000), 6),
        "JPY": round(random.uniform(135, 165), 6),
        "EUR": round(random.uniform(0.82, 0.96), 6),
        "SGD": round(random.uniform(1.25, 1.40), 6),
        "MYR": round(random.uniform(4.1, 4.8), 6),
        "GBP": round(random.uniform(0.72, 0.82), 6),
        "AUD": round(random.uniform(1.4, 1.6), 6),
        "CNY": round(random.uniform(6.9, 7.4), 6),
        "KRW": round(random.uniform(1300, 1450), 6),
    }


# ---------------------------------------------------------------- input otomatis
def jenis_prompt(prompt):
    p = prompt.lower()
    if any(w in p for w in ("mata uang", "kode", "tujuan", "currency", "konversi ke")):
        return "kode"
    if any(w in p for w in ("jumlah", "usd", "nominal", "berapa", "amount", "uang")):
        return "jumlah"
    return None


class InputOtomatis:
    """Memberi jawaban input() sesuai pertanyaan (jumlah USD atau kode mata uang)."""

    def __init__(self, langkah, log):
        # langkah: list of (jumlah, kode) ; kode None berarti tidak sampai ditanya
        self.langkah = list(langkah)
        self.i = 0
        self.jumlah_terkirim = False
        self.kode_terkirim = False
        self.log = log
        self.n = 0
        self.selesai_dikirim = False

    def __call__(self, prompt=""):
        prompt = str(prompt)
        self.n += 1
        if _HENTIKAN[0] is not None:
            raise _HENTIKAN[0]
        if self.selesai_dikirim:
            self.log.append(("in", prompt, None))
            _hentikan(TidakBerhenti())
        if self.n > INPUT_LIMIT or self.i >= len(self.langkah):
            self.log.append(("in", prompt, None))
            _hentikan(InputHabis())
        jumlah, kode = self.langkah[self.i]
        if jumlah == "selesai" and not self.jumlah_terkirim and not self.kode_terkirim:
            # 'selesai' diketik di pertanyaan pertama, apa pun bentuknya
            self.selesai_dikirim = True
            self.log.append(("in", prompt, "selesai"))
            return "selesai"
        jenis = jenis_prompt(prompt)
        if jenis is None:
            jenis = "kode" if self.jumlah_terkirim and not self.kode_terkirim else "jumlah"
        jumlah, kode = self.langkah[self.i]
        if jenis == "jumlah":
            if self.jumlah_terkirim:          # ditanya jumlah lagi -> langkah berikutnya
                self._maju()
                if self.i >= len(self.langkah):
                    self.log.append(("in", prompt, None))
                    _hentikan(InputHabis())
                jumlah, kode = self.langkah[self.i]
            nilai = jumlah
            self.jumlah_terkirim = True
            if nilai == "selesai":
                self.selesai_dikirim = True
            elif self.kode_terkirim:          # program menanyakan kode lebih dulu
                self._maju()
        else:
            if self.kode_terkirim:
                self._maju()
                if self.i >= len(self.langkah):
                    self.log.append(("in", prompt, None))
                    _hentikan(InputHabis())
                jumlah, kode = self.langkah[self.i]
            nilai = kode if kode is not None else "IDR"
            self.kode_terkirim = True
            if self.jumlah_terkirim:
                self._maju()
        self.log.append(("in", prompt, nilai))
        return nilai

    def _maju(self):
        self.i += 1
        self.jumlah_terkirim = False
        self.kode_terkirim = False


class Tangkap(io.TextIOBase):
    def __init__(self, log):
        self.log = log

    def write(self, s):
        if _HENTIKAN[0] is not None:
            raise _HENTIKAN[0]
        if s:
            if self.log and self.log[-1][0] == "out":
                self.log[-1] = ("out", self.log[-1][1] + s)
            else:
                self.log.append(("out", s))
        return len(s)


def transkrip(log):
    teks = ""
    for ev in log:
        if ev[0] == "out":
            teks += ev[1]
        elif ev[2] is None:
            teks += ev[1] + "⟂ (grader menghentikan program di sini)\n"
        else:
            teks += ev[1] + ev[2] + "\n"
    return teks


# ---------------------------------------------------------------- menjalankan
def _pasang(folder, rates, internet_mati):
    for nama in ("kurs", "main", "requests", "requests.exceptions"):
        sys.modules.pop(nama, None)
    req = buat_requests_palsu(rates, internet_mati)
    sys.modules["requests"] = req
    sys.modules["requests.exceptions"] = req.exceptions
    sys.path.insert(0, folder)
    return req


def _lepas(folder):
    for nama in ("kurs", "main", "requests", "requests.exceptions"):
        sys.modules.pop(nama, None)
    if folder in sys.path:
        sys.path.remove(folder)


def _jalankan(fn, log):
    """Menjalankan fn dengan stdout ditangkap + batas baris. Mengembalikan (status, pesan)."""
    hitung = [0]
    _HENTIKAN[0] = None

    def tracer(frame, event, arg):
        if _HENTIKAN[0] is not None:
            raise _HENTIKAN[0]
        if event == "line":
            hitung[0] += 1
            if hitung[0] > LINE_LIMIT:
                _hentikan(LoopTerlalu())
        return tracer

    stdout_asli, sleep_asli = sys.stdout, time.sleep
    sys.stdout = Tangkap(log)
    time.sleep = lambda *_a, **_k: None
    sys.settrace(tracer)
    try:
        fn()
        return "ok", ""
    except SystemExit:
        return "ok", ""
    except TidakBerhenti:
        return "tidak_berhenti", "Program masih meminta input setelah 'selesai'."
    except InputHabis:
        return "input_habis", "Program terus meminta input di luar skenario (kemungkinan error membuat loop salah alur)."
    except LoopTerlalu:
        return "loop", "Program berjalan terlalu lama tanpa meminta input (kemungkinan infinite loop)."
    except _Stop as e:
        return "loop", str(e)
    except BaseException as e:   # crash milik program praktikan
        return "crash", f"{type(e).__name__}: {e}"
    finally:
        sys.settrace(None)
        _HENTIKAN[0] = None
        sys.stdout = stdout_asli
        time.sleep = sleep_asli


def jalankan_main(folder, main_src, rates, langkah, internet_mati=False):
    log = []
    req = _pasang(folder, rates, internet_mati)
    import builtins
    input_asli = builtins.input
    builtins.input = InputOtomatis(langkah, log)
    try:
        kode = compile(main_src, os.path.join(folder, "main.py"), "exec")
        status, pesan = _jalankan(lambda: exec(kode, {"__name__": "__main__", "__file__": "main.py"}), log)
    except SyntaxError as e:
        status, pesan = "crash", f"SyntaxError: {e.msg} (baris {e.lineno})"
    finally:
        builtins.input = input_asli
        _lepas(folder)
    return status, pesan, log, req.jumlah_panggilan


# ---------------------------------------------------------------- pemeriksaan
ANGKA = re.compile(r"\d[\d.,]*")


def _ke_float(s):
    s = s.strip(".,")
    kandidat = set()
    kandidat.add(s.replace(",", ""))                                   # 180,140.27
    kandidat.add(s.replace(".", "").replace(",", "."))                 # 180.140,27
    hasil = []
    for k in kandidat:
        try:
            hasil.append(float(k))
        except ValueError:
            pass
    return hasil


def ada_angka(teks, target):
    for m in ANGKA.finditer(teks):
        for v in _ke_float(m.group()):
            if abs(v - target) <= max(1.0, abs(target) * 0.005):
                return True
    return False


def pesan_setelah(log, *nilai):
    """Teks yang dicetak program setelah input terakhir dari satu langkah (mis. jumlah & kode)
    sampai program meminta input berikutnya."""
    posisi = []
    for n in nilai:
        for idx, ev in enumerate(log):
            if ev[0] == "in" and ev[2] == n:
                posisi.append(idx)
                break
    if not posisi:
        return ""
    teks = ""
    for ev in log[max(posisi) + 1:]:
        if ev[0] == "in":
            break
        teks += ev[1]
    return teks.strip()


def input_terkirim(log, nilai):
    return any(ev[0] == "in" and ev[2] == nilai for ev in log)


def nilai_pengujian(file_kurs, file_main, seed=None):
    """file_kurs, file_main: isi file (str). Mengembalikan dict hasil penilaian."""
    rng_state = random.getstate()
    if seed is not None:
        random.seed(seed)
    rates = kurs_acak()
    random.setstate(rng_state)

    folder = tempfile.mkdtemp(prefix="kurs_")
    with open(os.path.join(folder, "kurs.py"), "w", encoding="utf-8") as f:
        f.write(file_kurs)
    with open(os.path.join(folder, "main.py"), "w", encoding="utf-8") as f:
        f.write(file_main)

    hasil = []

    def tambah(kode, judul, bobot, skor, catatan, log=None, status=None):
        hasil.append({"kode": kode, "judul": judul, "bobot": bobot, "skor": skor,
                      "catatan": catatan, "transkrip": transkrip(log) if log is not None else "",
                      "status": status})

    # ---- T1: fungsi ambil_kurs di kurs.py
    log = []
    req = _pasang(folder, rates, False)
    catatan, skor = "", 0
    try:
        kode = compile(file_kurs, os.path.join(folder, "kurs.py"), "exec")
        ns = {"__name__": "kurs"}
        status, pesan = _jalankan(lambda: exec(kode, ns), log)
        if status != "ok":
            catatan = "kurs.py gagal dijalankan: " + pesan
        elif not callable(ns.get("ambil_kurs")):
            catatan = "Tidak ada fungsi ambil_kurs(mata_uang) di kurs.py."
        else:
            benar = 0
            detail = []
            for kd in ("IDR", "JPY", "EUR"):
                hasil_fn = []
                st, ps = _jalankan(lambda: hasil_fn.append(ns["ambil_kurs"](kd)), log)
                if st != "ok":
                    detail.append(f"ambil_kurs('{kd}') error → {ps}")
                    continue
                v = hasil_fn[0]
                try:
                    ok = abs(float(v) - rates[kd]) <= rates[kd] * 0.0005
                except (TypeError, ValueError):
                    ok = False
                if ok:
                    benar += 1
                    detail.append(f"ambil_kurs('{kd}') = {v} ✓")
                else:
                    detail.append(f"ambil_kurs('{kd}') = {v!r}, seharusnya ±{rates[kd]}")
            if req.jumlah_panggilan == 0:
                catatan = "ambil_kurs tidak memanggil API (requests.get). Kurs tidak boleh ditulis manual."
            else:
                skor = round(20 * benar / 3)
                catatan = "; ".join(detail)
    except SyntaxError as e:
        catatan = f"kurs.py SyntaxError: {e.msg} (baris {e.lineno})"
    finally:
        _lepas(folder)
    tambah("T1", "Fungsi ambil_kurs(mata_uang) di kurs.py mengambil kurs dari API", 20, skor, catatan, log)

    # ---- T2: input & hasil konversi (2 konversi beruntun)
    st, ps, log, panggil = jalankan_main(folder, file_main, rates, [("10", "IDR"), ("2.5", "JPY"), ("selesai", None)])
    ok1 = ada_angka(transkrip(log), 10 * rates["IDR"])
    ok2 = ada_angka(transkrip(log), 2.5 * rates["JPY"])
    skor = 10 * ok1 + 10 * ok2
    cat = [f"10 USD → IDR: {'✓' if ok1 else '✗ seharusnya sekitar %.2f' % (10 * rates['IDR'])}",
           f"2.5 USD → JPY: {'✓' if ok2 else '✗ seharusnya sekitar %.2f' % (2.5 * rates['JPY'])}"]
    if st != "ok":
        cat.append(ps)
    tambah("T2", "Meminta jumlah USD & kode mata uang, lalu menampilkan hasil konversi", 20, skor, "; ".join(cat), log, st)

    # ---- T3: input bukan angka
    st, ps, log, panggil = jalankan_main(folder, file_main, rates, [("sepuluh", "IDR"), ("5", "EUR"), ("selesai", None)])
    pesan_err = pesan_setelah(log, "sepuluh", "IDR")
    lanjut = ada_angka(transkrip(log), 5 * rates["EUR"])
    skor, cat = 0, []
    if st == "crash":
        cat.append("Program crash: " + ps)
    elif not input_terkirim(log, "sepuluh"):
        cat.append("Program tidak meminta jumlah USD.")
    else:
        if pesan_err:
            skor += 8
            cat.append("Pesan error tampil ✓")
        else:
            cat.append("Tidak ada pesan error setelah input 'sepuluh'")
        if lanjut:
            skor += 7
            cat.append("Program lanjut & konversi berikutnya benar ✓")
        else:
            cat.append("Setelah error, konversi 5 USD → EUR tidak muncul/benar")
        if st != "ok":
            cat.append(ps)
    tambah("T3", "Menangani input bukan angka (ValueError)", 15, skor, "; ".join(cat), log, st)

    # ---- T4: kode mata uang tidak ada
    st, ps, log, panggil = jalankan_main(folder, file_main, rates, [("5", "XYZ"), ("3", "IDR"), ("selesai", None)])
    pesan_err = pesan_setelah(log, "5", "XYZ")
    lanjut = ada_angka(transkrip(log), 3 * rates["IDR"])
    skor, cat = 0, []
    if st == "crash":
        cat.append("Program crash: " + ps)
    elif not input_terkirim(log, "XYZ"):
        cat.append("Program tidak meminta kode mata uang.")
    else:
        if pesan_err:
            skor += 8
            cat.append("Pesan error tampil ✓")
        else:
            cat.append("Tidak ada pesan error setelah kode 'XYZ'")
        if lanjut:
            skor += 7
            cat.append("Program lanjut & konversi berikutnya benar ✓")
        else:
            cat.append("Setelah error, konversi 3 USD → IDR tidak muncul/benar")
        if st != "ok":
            cat.append(ps)
    tambah("T4", "Menangani kode mata uang tidak ada (KeyError)", 15, skor, "; ".join(cat), log, st)

    # ---- T5: internet mati
    st, ps, log, panggil = jalankan_main(folder, file_main, rates, [("10", "IDR"), ("selesai", None)], internet_mati=True)
    skor, cat = 0, []
    if st == "crash":
        cat.append("Program crash: " + ps)
    elif panggil == 0:
        cat.append("Program tidak pernah memanggil API, jadi kondisi internet mati tidak teruji")
    else:
        if pesan_setelah(log, "10", "IDR"):
            skor += 8
            cat.append("Pesan error tampil ✓")
        else:
            cat.append("Tidak ada pesan saat internet mati")
        if st == "ok" and input_terkirim(log, "selesai"):
            skor += 7
            cat.append("Program tetap jalan sampai 'selesai' ✓")
        else:
            cat.append(ps or "Program tidak lanjut sampai 'selesai'")
    tambah("T5", "Menangani internet mati (requests.exceptions.ConnectionError)", 15, skor, "; ".join(cat), log, st)

    # ---- T6: berulang sampai selesai
    st, ps, log, panggil = jalankan_main(folder, file_main, rates,
                                [("1", "IDR"), ("2", "EUR"), ("3", "SGD"), ("selesai", None)])
    teks = transkrip(log)
    skor, cat = 0, []
    jumlah_konversi = sum(ada_angka(teks, j * rates[k]) for j, k in ((1, "IDR"), (2, "EUR"), (3, "SGD")))
    if jumlah_konversi >= 3:
        skor += 8
        cat.append("Bisa 3 konversi beruntun ✓")
    else:
        cat.append(f"Hanya {jumlah_konversi} dari 3 konversi beruntun yang benar")
    if st == "ok" and input_terkirim(log, "selesai"):
        skor += 7
        cat.append("Berhenti rapi saat 'selesai' ✓")
    else:
        cat.append(ps or "Program tidak berhenti saat 'selesai'")
    tambah("T6", "Program berulang sampai user mengetik 'selesai'", 15, skor, "; ".join(cat), log, st)

    return {"total": sum(h["skor"] for h in hasil), "tes": hasil, "kurs_uji": rates}


if __name__ == "__main__":
    d = sys.argv[1]
    with open(os.path.join(d, "kurs.py"), encoding="utf-8") as f:
        k = f.read()
    with open(os.path.join(d, "main.py"), encoding="utf-8") as f:
        m = f.read()
    r = nilai_pengujian(k, m)
    for t in r["tes"]:
        print(f"{t['kode']} {t['skor']:>2}/{t['bobot']}  {t['catatan']}")
    print("TOTAL", r["total"])
