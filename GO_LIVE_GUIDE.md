# Go-Live Guide (for non-technical users)

Follow this like a recipe, top to bottom. Each step is labelled:
- 👉 **YOU** = something you click/sign up for in a website, then paste me a value.
- 🤖 **CLAUDE** = I do it for you. You don't touch anything.

You'll create **3 free accounts** (GitHub, Neon, Vercel) and paste me **3 values**.
That's the whole job. Take your time — nothing here can break anything.

---

## Part A — Put the code on GitHub

GitHub is just online storage for the app's code. Vercel reads it from there.

1. 👉 **YOU** — Go to https://github.com/signup and make a free account (if you don't have one).
2. 👉 **YOU** — Go to https://github.com/new and create an empty repository:
   - **Repository name:** `nse-amc`
   - Set it to **Private** (so it's not public).
   - **Do NOT** tick "Add a README" or any other checkbox. Leave them empty.
   - Click **Create repository**.
3. 👉 **YOU** — On the next page, copy the web address at the top. It looks like:
   `https://github.com/yourname/nse-amc.git`
4. 👉 **YOU** — Make a one-time access key so I'm allowed to upload the code:
   - Go to https://github.com/settings/tokens?type=beta
   - Click **Generate new token**.
   - Name it `deploy`, set **Expiration** to 7 days.
   - Under **Repository access** choose **Only select repositories** → pick `nse-amc`.
   - Under **Permissions → Repository permissions → Contents**, set it to **Read and write**.
   - Click **Generate token** and copy the long code that starts with `github_pat_...`
5. 👉 **YOU → me** — Paste me the **repository address** (step 3) and the **token** (step 4).
6. 🤖 **CLAUDE** — I upload the code to your GitHub repo.
7. 👉 **YOU** — Once I confirm it's done, you can delete that token at
   https://github.com/settings/tokens?type=beta (it has done its job). Optional but tidy.

> The token is like a temporary password. Sharing it with me here is fine for a one-time
> upload, and deleting it afterwards (step 7) means it can never be reused.

---

## Part B — Create the database (Neon, free)

This is where customer/contract data is stored permanently.

1. 👉 **YOU** — Go to https://neon.tech and sign up (you can use your GitHub login).
2. 👉 **YOU** — Click **Create project**. Any name is fine. Pick a region near India if offered.
3. 👉 **YOU** — After it's created, look for **Connection string** (or "Connection details").
   Copy the line that starts with `postgresql://...` — it ends with `...sslmode=require`.
4. 👉 **YOU → me** — Paste me that `postgresql://...` line. (This is value #2.)

---

## Part C — Create the upload storage (Vercel Blob)

This is where visit photos and service reports are saved.

1. 👉 **YOU** — Go to https://vercel.com and sign up (use your GitHub login again).
2. 👉 **YOU** — In the top menu click **Storage** → **Create Database** → choose **Blob** → **Create**.
3. 👉 **YOU** — Open the new Blob store, find **Tokens** (or ".env.local" tab), and copy the value
   that starts with `vercel_blob_rw_...`
4. 👉 **YOU → me** — Paste me that `vercel_blob_rw_...` value. (This is value #3.)

---

## Part D — Turn it into a live website (Vercel)

1. 👉 **YOU** — In Vercel, click **Add New… → Project**.
2. 👉 **YOU** — Find your `nse-amc` repository in the list and click **Import**.
   (If asked, allow Vercel to access your GitHub.)
3. 👉 **YOU** — Before clicking Deploy, open the **Environment Variables** section and add these
   rows. I'll give you the exact values to paste (some I'll generate for you):

   | Name | Where the value comes from |
   |------|----------------------------|
   | `SECRET_KEY` | I'll give you a random one to paste |
   | `DATABASE_URL` | the Neon line from Part B |
   | `BLOB_READ_WRITE_TOKEN` | the Vercel Blob value from Part C |
   | `OPENROUTER_API_KEY` | I'll give you yours |
   | `OPENROUTER_MODEL` | `anthropic/claude-haiku-4.5` |
   | `EMERGENCY_HOTLINE` | `1800-891-8565` |
   | `COMPANY_PHONE` | `9687266625` |
   | `COMPANY_EMAIL` | `info@northernstarengineering.com` |
   | `COMPANY_ADDRESS` | `521-522, Western Business Park, opp. S.D. Jain School, Surat, Gujarat 395007` |

4. 👉 **YOU** — Click **Deploy** and wait a couple of minutes. Vercel gives you a link like
   `https://nse-amc.vercel.app` — that's your live site! 🎉

---

## Part E — Load the starter data

1. 👉 **YOU → me** — Tell me Part D is done.
2. 🤖 **CLAUDE** — I load the demo plans, staff, and a sample customer into your new database so
   the site isn't empty.

---

## ⚠️ Important: before real customers use it

The customer login currently **shows the code on screen instead of texting it**. That's fine for
you to test, but it is not safe for real customers. When you're ready, tell me and I'll add real
SMS text-message login (you'd open one more account with a texting service like Twilio or MSG91).

---

## Where you are now

- ✅ App built and tested
- ✅ Code ready and saved on your computer (committed)
- ⬜ Part A — GitHub  ⬜ Part B — Neon  ⬜ Part C — Blob  ⬜ Part D — Deploy  ⬜ Part E — Data
- ⬜ SMS login (before going public)
