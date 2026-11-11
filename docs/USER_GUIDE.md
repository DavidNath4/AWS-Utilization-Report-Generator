# AWS Utilization Report Generator — Panduan Penggunaan

## Apa Ini?

Tool untuk generate **Monthly Support Report** (PowerPoint) secara otomatis dari file CloudViz (.docx). Tool ini akan:

1. Membaca informasi customer dari file CloudViz
2. Mengambil data utilization dari AWS (CPU, Memory, Storage, Cost, dll)
3. Generate report PowerPoint lengkap dengan chart dan tabel

## Prasyarat

- **Python 3.10+** — download dan install dari: [https://www.python.org/downloads/](https://www.python.org/downloads/)
  - Saat install, **centang "Add Python to PATH"**
- **File .env** berisi AWS credentials (minta ke tim Cloud Engineering)
- **File CloudViz (.docx)** dari customer yang mau di-generate report-nya

## Cara Menjalankan

### Pertama Kali (Setup)

1. Download folder `api-service` dari Google Drive
2. Minta file `.env` ke tim Cloud Engineering (berisi credentials AWS)
3. Taruh file `.env` di dalam folder `api-service` (sejajar dengan `run.bat`)
4. Install Python dari [python.org/downloads](https://www.python.org/downloads/) — **centang "Add Python to PATH"** saat install

### Windows

1. Buka folder `api-service`
2. Double-click file **`run.bat`**
3. Browser otomatis terbuka ke halaman Report Generator
4. Untuk stop: tekan `Ctrl+C` di command prompt

### Linux / Mac

```bash
cd api-service
chmod +x run.sh
./run.sh
```

### Docker

Kalau tidak mau install Python, bisa pakai Docker:

```bash
# Build image (sekali aja)
cd api-service
docker build -t report-api .

# Jalankan
docker run -p 8000:8000 --env-file .env report-api
```

Buka browser → `http://localhost:8000`

Untuk stop: tekan `Ctrl+C` di terminal.

> **Deploy di server (untuk akses tim):** Jalankan Docker di VM/server, lalu semua orang bisa akses via `http://<ip-server>:8000` dari browser — tanpa perlu install apapun di laptop masing-masing.

## Cara Generate Report

### Single Customer (1 file)

1. Buka `http://localhost:8000` di browser
2. Klik area upload atau drag file `.docx` ke area tersebut
3. Klik **"Preview Grouping"** — pastikan info customer benar
4. Klik **"Generate Reports"**
5. Tunggu 1-2 menit (tergantung jumlah resource di AWS)
6. File `.pptx` otomatis ter-download

### Multiple Accounts / Organisasi (beberapa file)

Jika satu organisasi punya beberapa AWS account (misal TMLI-Prod dan TMLI-DR):

1. Upload **semua file .docx** sekaligus
2. Klik **"Preview Grouping"** — tool otomatis mengelompokkan berdasarkan nama organisasi:
   ```
   📊 TMLI
     • TMLI-Prod (571600860596) — ap-southeast-3
     • TMLI-DR (574067619520) — ap-southeast-3
   
   📊 SMI
     • SMI-Prod (123456789012) — ap-southeast-1
     • SMI-Staging (987654321098) — ap-southeast-1
   ```
3. Pastikan grouping sudah benar
4. Klik **"Generate Reports"**
5. Jika ada beberapa organisasi, hasil download berupa file `.zip` berisi semua report

### Aturan Grouping Otomatis

Tool mengelompokkan file berdasarkan **prefix nama sebelum tanda `-`**:

| Nama di CloudViz | Group | Report |
|---|---|---|
| TMLI-Prod | TMLI | ✅ Digabung |
| TMLI-DR | TMLI | ✅ Digabung |
| SMI-Prod | SMI | ✅ Digabung |
| SMI-Staging | SMI | ✅ Digabung |
| Rodamas | Rodamas | Sendiri |
| Summarecon | Summarecon | Sendiri |

## Isi Report yang Di-generate

Report PowerPoint berisi slide-slide berikut:

| No | Slide | Keterangan |
|---|---|---|
| 1 | Monthly Support Report | Halaman judul (dari template) |
| 2 | Agenda | Daftar isi |
| 3 | Monthly Incident Report | Placeholder (diisi manual) |
| 4 | Monthly CloudWatch Alarm Report | Placeholder (diisi manual) |
| 5 | Monthly Berca Support Activities | Placeholder (diisi manual) |
| 6 | Infrastructure Summary | Tabel ringkasan resource |
| 7 | Current High Level Design | Diagram HLD dari CloudViz |
| 8 | Compute & Memory Utilization | Tabel + chart CPU/Memory per EC2 |
| 9 | Database Utilization (RDS) | Tabel + chart per RDS |
| 10 | EBS Storage Utilization | Tabel EBS volumes |
| 11 | S3 Storage Utilization | Tabel S3 + object count |
| 12 | VPN Connection | Placeholder (diisi manual) |
| 13 | Elastic Disaster Recovery | Tabel DRS (jika ada) |
| 14 | Top Spender | Pie chart + tabel cost |
| 15 | Security Alert and Finding | Tabel temuan GuardDuty (otomatis) |
| 16 | Cost Optimization Recommendation | Template rekomendasi |
| 17 | Support Flow | Placeholder (diisi manual) |
| 18 | Savings Plans | Tabel SP (jika ada) |

> Slide bertanda "Placeholder" perlu diisi manual setelah report di-generate.

### Security Alert and Finding (GuardDuty)

Slide ini diisi otomatis dari AWS GuardDuty:

- Hanya region yang dikonfigurasi untuk akun tersebut (region dari file CloudViz / parameter `region`) yang di-query. Region lain tidak di-scan.
- Yang diambil: finding aktif (tidak di-archive) yang `updatedAt`-nya masuk dalam periode report.
- Tabel menampilkan maksimal 10 finding, urut severity (High, Medium, Low) lalu terbaru. Kolom: Severity, Type, Title, Resource Type, Region, Count, Last Seen. Di atas tabel ada ringkasan jumlah per severity.
- Severity: High (>= 7), Medium (4 sampai < 7), Low (< 4).
- Jika GuardDuty belum aktif, akses ditolak, atau terjadi error, slide menampilkan pesan (report tetap jadi). Jika tidak ada finding, slide menampilkan "No active GuardDuty findings in this report period."

Permission IAM yang dibutuhkan di role yang di-assume (`guardduty:GetFindingsStatistics` opsional, belum dipakai oleh kode saat ini):

```json
{
  "Effect": "Allow",
  "Action": [
    "guardduty:ListDetectors",
    "guardduty:ListFindings",
    "guardduty:GetFindings",
    "guardduty:GetFindingsStatistics"
  ],
  "Resource": "*"
}
```

## Troubleshooting

### "Gagal assume role ke akun ..."
- Pastikan AWS credentials di file `.env` masih valid (belum expired)
- Pastikan role name di `.env` sesuai dengan yang ada di akun customer
- Hubungi tim DevOps untuk update credentials

### Report lama di-generate (lebih dari 5 menit)
- Normal jika customer punya banyak resource (EC2, EBS, S3)
- Setiap resource perlu query CloudWatch metrics satu per satu
- Jangan tutup browser selama proses berjalan

### File .docx tidak bisa di-upload
- Pastikan file berformat `.docx` (bukan `.doc` atau `.pdf`)
- File harus dari CloudViz export
- 3 baris pertama file harus berisi: Nama Customer, Account ID, Region

### Browser tidak terbuka otomatis
- Buka manual: `http://localhost:8000`

### Port 8000 sudah dipakai
- Stop aplikasi lain yang pakai port 8000
- Atau edit `app.py` baris terakhir, ganti port: `uvicorn.run(app, host="0.0.0.0", port=9000)`

## Ganti Template PowerPoint

1. Buka file `template.pptx` di PowerPoint
2. Edit background, logo, warna, font sesuai kebutuhan
3. Save
4. Restart aplikasi (stop lalu jalankan ulang `run.bat`)

> Slide pertama di template akan dipakai sebagai halaman judul.
> Slide lainnya di template akan dihapus dan diganti dengan konten report.

## Kontak

Jika ada masalah atau pertanyaan, hubungi tim Cloud Engineering.
