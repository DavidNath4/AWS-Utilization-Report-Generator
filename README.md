# AWS Utilization Report Generator API

Generate PowerPoint report dari file CloudViz (.docx) + AWS CloudWatch metrics.

## Quick Start (Lokal)

```bash
cd api-service
pip install -r requirements.txt
cp .env.example .env   # edit isi credentials
python app.py
```

Buka browser → `http://localhost:8000`

## Docker

```bash
cd api-service
docker build -t report-api .
docker run -p 8000:8000 --env-file .env report-api
```

## Environment Variables

| Variable | Deskripsi |
|----------|-----------|
| `AWS_ACCESS_KEY_ID_STS` | Access key buat STS AssumeRole |
| `AWS_SECRET_ACCESS_KEY_STS` | Secret key buat STS |
| `DEFAULT_ROLE_NAME` | Nama role di akun customer |
| `PERIOD_DAYS` | Berapa hari ke belakang (default 30) |

## Cara Pakai (Web UI)

1. Buka `http://localhost:8000`
2. Upload file CloudViz .docx (bisa multiple)
3. Klik "Preview Grouping" — cek grouping bener
4. Klik "Generate Reports"
5. File .pptx otomatis ke-download

### Multi-Account / Organisasi

Kalau satu organisasi punya beberapa AWS account (misal TMLI-Prod, TMLI-DR),
upload semua file .docx sekaligus. API otomatis group berdasarkan prefix nama:

- `TMLI-Prod` + `TMLI-DR` → 1 report "TMLI"
- `SMI-Prod` + `SMI-Staging` → 1 report "SMI"
- `Rodamas` → 1 report "Rodamas"

Kalau upload file dari organisasi berbeda, masing-masing jadi report terpisah
dan di-download sebagai .zip.

## API Endpoints

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/` | Web UI |
| GET | `/health` | Health check |
| GET | `/docs` | Swagger API docs |
| POST | `/preview` | Upload .docx, return grouping preview (JSON) |
| POST | `/generate` | Upload .docx, return .pptx atau .zip |
| POST | `/generate-report` | Single file (backward compatible) |

## Security Alert and Finding (GuardDuty)

Slide "9. Security Alert and Finding" diisi dari GuardDuty, hanya untuk region yang dikonfigurasi per akun (tidak scan semua region). Menampilkan top 10 finding aktif dalam periode report, urut severity (High >= 7, Medium 4-<7, Low <4) lalu terbaru, plus ringkasan jumlah per severity. Kalau GuardDuty tidak aktif / access denied / tidak ada finding, slide menampilkan pesan.

Permission IAM tambahan untuk role yang di-assume:

- `guardduty:ListDetectors`
- `guardduty:ListFindings`
- `guardduty:GetFindings`
- `guardduty:GetFindingsStatistics` (opsional, belum dipakai kode saat ini)

## Template PowerPoint

File `template.pptx` di-bundle di Docker image. Untuk ganti template:
1. Edit `template.pptx` di PowerPoint
2. Rebuild Docker image

## Struktur File

```
api-service/
├── app.py                 # FastAPI app
├── auth.py                # STS AssumeRole
├── collectors.py          # AWS data collection
├── docx_parser.py         # Parse CloudViz .docx
├── report_generator.py    # Generate PPTX
├── template.pptx          # Template PowerPoint
├── templates/index.html   # Web UI
├── requirements.txt       # Dependencies
├── Dockerfile             # Docker build
└── .env.example           # Contoh environment variables
```
