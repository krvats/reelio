# Selling Reelio: what is true, and what to do

## The honest part
Reelio's code is public so GitHub Pages and Actions are free. That means anyone can download it, and an AI can rebuild it. Nothing on a public repo can stop that. What you can sell is what a copy does not include:

1. **Done-for-you setup.** Most people will not do 15 minutes of GitHub, Meta and Google steps. You do it for them (the in-app setup guides you).
2. **Hosted accounts.** Posting runs on infrastructure you control, users just log in with email (`api/`, `docs/TUTORIAL.md` Part 3). Here access can really be switched off.
3. **Support and upkeep.** Instagram/YouTube change things; you keep it working, and you hold the Cloudinary/Google/Meta setup for them.
4. **Licence.** The repo is All Rights Reserved: nobody may run or resell it without your written permission. This is your legal lever, but it only works if you act on copies you find; it is not legal advice and cannot physically stop copying. To change it, replace `LICENSE`.

If you want less copying, make the worker (`worker/`, `api/`, `license/`) a **private** repo and keep only `web/` public. GitHub Pages on a private repo needs a paid GitHub plan, and private Actions minutes are limited, so this is a cost trade-off.

## How people get access (no payment on the site)
The site has no prices or checkout. "Message us" opens an Instagram DM to @kr5na_ (`contactUrl` in `web/app-config.js`). Suggested flow:
1. Person messages you with their page and channel counts.
2. You agree price and take payment yourself (UPI etc.).
3. Self-host: you create their setup or walk them through it. Hosted: create their account (`admin.html`) or grant access with the license service (`web/upi-admin.html`, `license/README.md`).
4. They open the app (`app.html`) and connect accounts.

## Before you announce
- Terms, Privacy and Copyright pages are filled in (brand only, India, contact via Instagram @kr5na_, refund: full before setup starts, none after delivery, 7-day case-by-case). A lawyer review is still wise once you earn real money.
- Rotate any tokens that were ever in old zips or chats.
- Meta and Google will not approve a public app without a registered business, so sell the bring-your-own-keys model (each user creates their own Meta and Google app).
- Test one full flow live: Instagram publish via Cloudinary, YouTube upload, Telegram alert.
