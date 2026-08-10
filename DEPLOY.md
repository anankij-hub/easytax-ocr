# คู่มือ Deploy EasyTax-OCR ขึ้น GitHub + Vercel

โฟลเดอร์นี้เป็นเวอร์ชันที่ปรับให้รันบน Vercel ได้ (ต่างจากเวอร์ชัน local ที่ใช้ Tesseract + SQLite):

| ส่วน | เวอร์ชัน local | เวอร์ชัน Vercel (โฟลเดอร์นี้) |
|---|---|---|
| เว็บเซิร์ฟเวอร์ | Python stdlib `http.server` | Flask (`api/index.py`) |
| ฐานข้อมูล | ไฟล์ SQLite ในเครื่อง | Postgres ภายนอก (Neon/Supabase) ผ่าน `DATABASE_URL` |
| OCR | Tesseract (โปรแกรมในเครื่อง) | Google Cloud Vision API ผ่าน `GOOGLE_VISION_API_KEY` |
| ไฟล์ต้นฉบับที่อัปโหลด | เก็บในโฟลเดอร์ `uploads/` | เก็บเป็น bytea ในตาราง Postgres |

เหตุผลที่ต้องเปลี่ยน: Vercel เป็น serverless ไม่มี disk ถาวรและรันโปรแกรมระบบอย่าง Tesseract ไม่ได้ ส่วน `extractor.py` (ตรรกะดึงฟิลด์/จัดประเภทเต็มรูป-ย่อ) **ไม่ต้องแก้อะไรเลย** เพราะทำงานกับข้อความล้วนๆ ไม่ขึ้นกับว่า OCR engine ไหนเป็นคนอ่าน

---

## ขั้นตอนที่ 1: สร้างฐานข้อมูล Postgres ฟรี

เลือกทำอย่างใดอย่างหนึ่ง (ผลลัพธ์ที่ต้องการเหมือนกันคือ connection string 1 เส้นสำหรับ `DATABASE_URL`)

### แบบ Neon

1. ไปที่ [neon.tech](https://neon.tech) สมัคร/ล็อกอิน แล้วสร้างโปรเจกต์ใหม่
2. หลังสร้างเสร็จ จะมีหน้า **Connection string** ให้คัดลอก — เลือกแบบ **Pooled connection** (มีคำว่า `-pooler` ในชื่อ host) เพราะเหมาะกับ serverless มากกว่า
3. หน้าตาจะประมาณนี้: `postgresql://neondb_owner:xxxxx@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
4. เก็บ connection string นี้ไว้ — จะใช้เป็นค่า `DATABASE_URL` ในขั้นตอนที่ 4

### แบบ Supabase

1. ไปที่ [supabase.com](https://supabase.com) สมัคร/ล็อกอิน (ล็อกอินด้วย GitHub ได้เลย)
2. กด **New Project** — ตั้งชื่อโปรเจกต์, ตั้ง **Database Password** (จำให้ดี ต้องใช้ต่อ), เลือก Region ที่ใกล้ที่สุด (เช่น Singapore) แล้วกดสร้าง รอประมาณ 1-2 นาทีให้ provision เสร็จ
3. เข้าเมนู **Project Settings** (รูปเฟือง) -> **Database** -> เลื่อนไปหัวข้อ **Connection string**
4. เลือกแท็บ **Connection pooling** โหมด **Transaction** (สำคัญ — โหมดนี้เหมาะกับ serverless อย่าง Vercel) แล้วคัดลอก connection string
5. หน้าตาจะประมาณนี้: `postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres`
6. แทนที่ `[YOUR-PASSWORD]` ในเส้นนั้นด้วยรหัสผ่านฐานข้อมูลที่ตั้งไว้ในข้อ 2 จริงๆ — นี่คือค่า `DATABASE_URL` ที่จะใช้ในขั้นตอนที่ 4

## ขั้นตอนที่ 2: สร้าง Google Cloud Vision API key

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/) สร้างโปรเจกต์ใหม่ (หรือใช้โปรเจกต์เดิม)
2. เมนูซ้าย -> **APIs & Services** -> **Library** -> ค้นหา "Cloud Vision API" -> กด **Enable**
3. เมนูซ้าย -> **APIs & Services** -> **Credentials** -> **Create Credentials** -> **API key**
4. คัดลอก API key ที่ได้ — แนะนำกด **Restrict key** แล้วเลือกจำกัดให้ใช้ได้เฉพาะ "Cloud Vision API" เพื่อความปลอดภัย
5. ค่าใช้จ่าย: มี free tier ให้ใช้ฟรีในแต่ละเดือน เกินจากนั้นคิดเงินตามจำนวนภาพที่ประมวลผล — เช็คราคาปัจจุบันที่ [cloud.google.com/vision/pricing](https://cloud.google.com/vision/pricing) ก่อนใช้งานจริงจัง

## ขั้นตอนที่ 3: Push โค้ดขึ้น GitHub

เปิด Terminal ไปที่โฟลเดอร์นี้ (`easytax_ocr_vercel`):

```bash
git init
git add .
git commit -m "EasyTax OCR - Vercel deployment"
```

ไปที่ [github.com/new](https://github.com/new) สร้าง repository ใหม่ (ไม่ต้องติ๊ก "Add README") จากนั้น:

```bash
git remote add origin https://github.com/<ชื่อผู้ใช้>/<ชื่อ-repo>.git
git branch -M main
git push -u origin main
```

## ขั้นตอนที่ 4: Deploy บน Vercel

1. ไปที่ [vercel.com](https://vercel.com) ล็อกอินด้วยบัญชี GitHub เดียวกัน
2. กด **Add New** -> **Project** -> เลือก repository ที่เพิ่ง push ไป -> **Import**
3. ก่อนกด Deploy ให้เปิดส่วน **Environment Variables** แล้วเพิ่ม 2 ตัว:
   - `DATABASE_URL` = connection string จาก Neon (ขั้นตอนที่ 1)
   - `GOOGLE_VISION_API_KEY` = API key จาก Google Cloud (ขั้นตอนที่ 2)
4. กด **Deploy** รอสักครู่ Vercel จะ build และให้ URL มา เช่น `https://your-project.vercel.app`
5. เปิด URL นั้น หน้าเว็บควรขึ้นเหมือนตอนรัน local ทุกอย่าง ลองอัปโหลดใบกำกับภาษีทดสอบ

ทุกครั้งที่ `git push` โค้ดใหม่ขึ้น branch `main` Vercel จะ deploy เวอร์ชันใหม่ให้อัตโนมัติ

## ทดสอบในเครื่องก่อน deploy (แนะนำ)

ติดตั้ง Vercel CLI แล้วรันจำลอง serverless environment ในเครื่องได้:

```bash
npm install -g vercel
cp .env.example .env    # แล้วใส่ค่า DATABASE_URL / GOOGLE_VISION_API_KEY จริง
pip install -r requirements.txt
vercel dev
```

จะได้ URL แบบ `http://localhost:3000` ให้ทดสอบเหมือนของจริงก่อน push

## ข้อจำกัดของแผนฟรี (Hobby) ที่ควรรู้

- **ขนาดไฟล์อัปโหลด**: request body จำกัดประมาณ 4.5MB — ถ้าถ่ายรูปด้วยมือถือความละเอียดสูงมากอาจเกิน ลองลดขนาด/บีบอัดภาพก่อนอัปโหลดถ้าเจอปัญหา
- **เวลาทำงานของ function**: ค่า default ประมาณ 10 วินาที — พอสำหรับอัปโหลดทีละ 1-2 ไฟล์ ถ้าอัปโหลดพร้อมกันหลายไฟล์ใหญ่ๆ อาจ timeout ได้ แนะนำอัปโหลดทีละไม่กี่ไฟล์
- **Neon free tier**: มี compute hours จำกัดต่อเดือน และฐานข้อมูลจะ "sleep" เมื่อไม่ได้ใช้งาน (auto-wake เมื่อมี request เข้ามา อาจช้าขึ้นเล็กน้อยตอน request แรก)
- **Cloud Vision free tier**: มีโควตาฟรีต่อเดือน เกินจากนั้นเริ่มคิดเงิน ควรตั้ง budget alert ไว้ใน Google Cloud Console

## หมายเหตุ

โค้ดชุดนี้ยังไม่ได้ถูกทดสอบกับ Postgres/Cloud Vision จริง (สภาพแวดล้อมที่ผมใช้พัฒนาไม่มีอินเทอร์เน็ตออกไปยัง Neon/Google ได้) — ตรวจสอบ logic แล้วอย่างละเอียด แต่ถ้าเจอ error ตอน deploy จริง ส่ง error message มาได้เลย จะช่วยไล่แก้ให้
