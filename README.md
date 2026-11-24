# Savour Dishes – Python backend

Flask + SQLite. The same server also serves the website, so there is nothing else to run.

## Run it

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

By default it keeps everything in one SQLite file (`saviour.db`), which is fine for trying it out. For real use, switch to PostgreSQL: see **PostgreSQL** below.

## Folder layout

```
saviour-backend/
  app.py            the API + database (creates saviour.db on first run)
  requirements.txt
  docker-compose.yml   a ready-made PostgreSQL database (optional)
  postgres-schema.sql  reference copy of the tables (the app creates them itself)
  static/index.html the website (staff and owner only)
  static/img/       logo and dish photos
```

## Staff dashboard layout

After logging in, staff and the owner land on a **home screen** like a mobile-money app: a card with today's sales, open orders and
payments not yet confirmed, then a grid of icon tiles for every section they may open. Red numbers on the **Orders** and
**Transactions** tiles show what needs attention. Tapping a tile opens that section; the **←** button (or the phone's back button)
returns home. Sections the owner has switched off simply don't appear.

## Light and dark theme

Everyone (customers, staff and the owner) has a theme button at the top of every screen, including the login page. Tap it to cycle
**🌗 Auto** (follows the phone's light/dark setting, the default), **☀️ Light** and **🌙 Dark**. The choice is remembered on that device only,
not on the account, and Auto switches by itself when the phone's setting changes.

## Owner and staff

- **Owner** (`staff01` on first run) can open everything and has an extra **Access** tab.
- **Staff** can open everything too, until the owner switches sections off for them.

Set the owner's password before the first run:

```
SD_ADMIN_PASSWORD="choose-a-strong-one" python app.py
```

If you don't, the password is `saviour123`; change it before going live.

In the **Access** tab the owner can add a staff member and tick or untick each section
(Overview, Business Today, Orders, Sales, Purchases, Expenses, Transactions, Profit & Loss, Staff report, Best Sellers, Menu) for that person.
Changes apply straight away, even if the staff member is signed in.

From the command line instead: `python app.py create-staff jane "Jane Doe" Staff`

Older databases are upgraded automatically (Manager becomes Owner; other roles become Staff).

## API

| Method | Path | Who |
|---|---|---|
| POST | /api/login/staff `{id, password}` | anyone |
| POST | /api/logout, GET /api/me | logged in |
| GET | /api/menu | anyone |
| POST | /api/menu `{name, category, price, emoji?, description?}` | *menu* access (adds a dish) |
| PUT, DELETE | /api/menu/<id> | *menu* access (edit or remove a dish; a dish inside a combo can't be deleted) |
| PATCH | /api/menu/<id> `{available: bool}` and/or `{price: int}` | *menu* access to switch on/off; *menu* or *sales* access to change a price |
| GET | /api/price-changes | *sales* access |
| POST, PUT, DELETE | /api/combos, /api/combos/<id> | *sales* access |
| GET | /api/orders | *orders* access |
| PATCH | /api/orders/<SD0001> `{status}` | *orders* access (Pending → Preparing → Served) |
| GET | /api/payment-info | anyone (payment methods and the till number) |
| PUT | /api/settings/till `{till}` | owner only |
| GET | /api/transactions?limit=&offset=&method=&status=&from=&to=&q= | *transactions* access (default: last 20) |
| PATCH | /api/transactions/<TX0001> `{status: Paid\|Failed}` | *transactions* access |
| GET | /api/mpesa/status | owner only |
| POST | /api/pay/c2b/<secret>/confirmation, /validation | Safaricom only (secret is in the address) |
| GET | /api/reports/overview?range= | *overview* access (daily sales, purchases and expenses for the graph) |
| GET | /api/reports/today?date= | *today* access (Business Today) |
| PUT | /api/orders/<SD0001>/payments `{parts: [{method, amount, status?, reference?}]}` | *transactions* access (split or change what is still unpaid) |
| POST | /api/sales `{items, service?, location?, parts?, draft_id?}` | *sales* access (counter sale, recorded as served) |
| GET, POST, PUT, DELETE | /api/drafts, /api/drafts/<id> | *sales* access |
| POST, DELETE | /api/wastage, /api/wastage/<id> | *expenses* access (GET: the `wastage` block of /api/expenses) |
| GET | /api/sales?range= | *sales* access |
| GET, POST, DELETE | /api/purchases | *purchases* access |
| GET, POST, DELETE | /api/expenses | *expenses* access |
| GET, PUT, DELETE | /api/purchases/<id>/photo (id of a single purchase or of a trip), /api/purchase_drafts/<id>/photo, /api/expenses/<id>/photo `{image}` | the same section's access (a receipt photo; PUT takes a JPEG/PNG/WebP data URL up to 1.5 MB) |
| GET, POST | /api/purchase-drafts | the Purchases section (list drafts; start a draft `{label, date, lines}`) |
| PUT, DELETE | /api/purchase-drafts/<id> | the Purchases section (save or delete a draft) |
| DELETE | /api/purchase-trips/<id> | the Purchases section (deletes everything bought together, and its photo) |
| POST | /api/purchase-drafts/<id>/submit | the Purchases section (records every line as a purchase, then removes the draft) |
| GET | /api/reports/staff?range= | *team* access (started, served, counter sales, payments confirmed, average wait, records entered) |
| GET | /api/reports/dishes?range= | *dishes* access (best sellers, slow movers, busy hours, income by category) |
| GET | /api/receipts/<SD0001> | staff with *orders*, *sales* or *transactions* access |
| GET, PUT | /api/access, /api/access/<staff_id> `{area, allowed}` | owner only |
| POST | /api/staff `{id, name, password}` | owner only |

`range` is one of `today`, `week`, `month` (default) or `all`.
Each order records which staff member started it and which one served it.
Dates use East Africa Time by default; change with `SD_TZ_HOURS` (e.g. `SD_TZ_HOURS=2`).

## Notes

- Passwords are hashed; login tokens are stored hashed and expire after 12 hours.
- Order prices and availability are always taken from the database, never from the browser.
- To let staff on other devices use it, run with `SD_HOST=0.0.0.0` and put it behind HTTPS
  (e.g. nginx or a host like Render/Railway).

## Menu, photos and logo

The menu (35 dishes, copied from the board on the wall) is in `SEED_MENU` in `app.py`.
It is loaded into the database the first time the app runs; an older sample menu is replaced automatically.

- **The logo and the six dish photos are also built into `index.html`**, so the site never shows a broken picture, even if the `img` folder isn't uploaded
  (a photo that can't load turns into the dish's emoji avatar). Every other dish has a round emoji avatar tinted by its category, light or dark.
  To change the logo or a photo, update the picture files *and* the copy inside `index.html`, or ask for it to be regenerated.
- **Logo:** `static/img/logo.png`. Replace the file with a cleaner copy any time (a clear, straight-on image works best).
- **Dish photos:** a dish shows a round photo if it is listed in `DISH_PHOTOS` in `app.py`; otherwise an emoji avatar.
  Add a photo by copying the file into `static/img/` and adding `"Dish name": "file.jpg"`, then restart. No database change needed.

## Business Today, counter sales, split payments and wastage

- **Business Today** (staff tile): what happened on a day, today by default, or pick another day. Sales, profit after costs, purchases, expenses, food wasted, money received (cash / till / waiting to be confirmed), orders, sales by hour, best sellers, who served, and a timeline of everything that happened. The owner can switch it off for staff under **Access**.
- **Overview** now graphs sales, purchases and expenses as three separate bars per day, with a table underneath.
- **Sales -> New sale / Drafts:** tap dishes to make a counter sale (recorded as served, under "Walk-in customer"). Pay cash, till or split. **Save as draft** keeps it for later; drafts are not counted as sales until completed.
- **Split payment:** a sale can be part cash, part till. Staff can split or change what is still unpaid with **Split / change** on an order. Each part is confirmed on its own in Transactions. A confirmed part never changes.
- **Expenses -> Food Wastage:** record food thrown away (item, quantity, cost, reason). It is shown beside expenses, in Overview, Business Today and Profit & Loss, but never subtracted twice, because the money was already spent on purchases.
- **Purchases:** type the quantity, pick a unit (kg, litres, bags...) and the price per unit; the total amount fills in by itself.
- Existing databases upgrade by themselves on the next start.

## Receipts, Best Sellers and Staff report

- **Receipts.** Customers get a **🧾 Receipt** button on each order that isn't cancelled. Staff get it in Orders, in the sales log,
  and a receipt opens straight after a counter sale. A receipt can be **printed** (or saved as PDF from the print screen)
  or sent on **WhatsApp**. Staff sharing a customer's receipt open WhatsApp already addressed to her number.
  The receipt shows PAID or PAYMENT PENDING, so it doubles as a bill.
- **Best Sellers** (own tile, own access switch, so the owner can hide it from staff). Uses served orders for the period picked:
  most sold or most income, slow movers (dishes on the menu that sold least, including ones that sold nothing),
  the busiest hours of the day and income by category. Dishes switched off on the menu are left out of slow movers.
- **Staff report** now also shows counter sales, payments confirmed, average minutes from order to served (customer orders only)
  and how many purchases, expenses and wastage records each person entered.

## Receipt photos

On **Purchases** and **Expenses**, the form has **📷 Take photo** (opens the phone camera) and **🖼️ Choose photo** (from the gallery). The photo is saved
with the record. A record saved without one has **📷 Add** in its list row, and a record with one has **🧾 View** (tap the photo to zoom, **Replace** or **Remove**).
Photos are shrunk on the phone to about 200-500 KB first, checked by the server (real JPEG/PNG/WebP, 1.5 MB at most) and kept **in the database**
(so they survive Render deploys). Deleting a purchase or expense deletes its photo. They follow the section's access switch, so staff who
can't open Expenses can't see its receipts. Rough size: 1,000 photos is about 300 MB, so check your database plan's storage now and then.

## Purchase drafts and things bought together

When you buy several things in one trip, add them to a draft list instead of recording each one straight away. On the Purchases page, fill in the item and press **Add to draft list instead**. The draft saves itself after every change, so you can close the app and come back. Open it later from the **Drafts** tab (Open or Delete). Give the draft one receipt photo for the whole list (Take photo / Choose photo on the draft, or on the form when you add an item).

Press **Submit all purchases** and every line is recorded, all together or not at all, using the draft's date and your name. Items bought together show as **one line** in the Purchases list (the draft's name, the combined total and the receipt). Tap the line to see the items inside; Delete on that line removes the whole purchase. A list with a single item is recorded as a normal purchase. Drafts do not count in any total or report until they are submitted; each item counts once in the reports.

## Line graphs

Overview shows sales, purchases and expenses as a **line graph** (one line each, a dot per day). Tap or hover a day to read its numbers
below the graph; long periods scroll sideways, opening on the latest days, with the amounts on the left staying in view.
Profit & Loss uses the same graph for sales against purchases plus expenses.

## Profit & Loss

Staff dashboard -> **Profit & Loss**. Pick Today, Yesterday, This week, This month, Last month or This year, or search by a single day, a month, a year or custom dates.

- **Statement:** Sales, less Purchases = Gross profit, less Expenses (by category) = Net profit or loss, with the previous period beside it and the change.
- **Money received:** cash, KCB Till, and sales not yet confirmed.
- **Day by day** (or month by month for long periods) chart, top dishes, sales by category, purchases by item.
- **Records:** the sales, purchases and expenses behind the figures, plus a **CSV download**.
- Sales count when an order is marked **Served**. Purchases and expenses count on their recorded date.
- The owner can switch this section off for staff under **Access**.

API: `GET /api/reports/pnl?from=YYYY-MM-DD&to=YYYY-MM-DD`

## Managing the menu

In the staff **Menu** tile, staff and the owner can:
- **Add a dish:** name, category (pick an existing one or type a new one, which creates a new menu section), price, an emoji for its avatar, and an optional description. It shows on customers' menus straight away.
- **Change a price:** type the new price in the dish's box and tap **Save price**. Orders already placed keep the price they were made at, and every change is logged in Sales → Item prices.
- **Edit or remove:** **Edit** changes any detail; **Delete** removes a dish (past orders keep its name and price). A dish that is part of a combo can't be deleted until the combo is changed. Use **Mark unavailable** to hide a dish for a while.
- New dishes get an emoji avatar. Photos are built into the page for the original six dishes only, and renaming one of those turns it into an emoji avatar.
- The owner can switch the Menu section off for staff in **Access**. The starter menu is loaded once, so dishes you add or remove are never undone when the app restarts.

## Prices and combos

In the **Sales** tab there are three views: Sales log, Item prices and Combos.

- **Item prices:** change any dish's price. It applies to new orders straight away; orders already placed keep the price they were made at.
  Every change is logged (who, when, old and new price). If a price changes while a customer is checking out, they are asked to review their total.
- **Combos:** bundle dishes at one price (for example Chapati x2 + African Tea). Combos show first on the customer menu with the saving.
  A combo is unavailable while any dish in it is switched off. The kitchen sees what is inside each combo on the order.
- The owner controls this with the **Sales** access box in the Access tab.

## Staff only

The website is for **staff and the owner only**. There is no customer sign-up, menu, cart or order page, and no customer text-message codes.
Staff enter every sale themselves under **Sales -> New sale** (cash, till or split; save a draft for a table that is still eating),
and can print or WhatsApp a receipt straight after.

- **Older data is kept.** Customer accounts, their old orders and their feedback stay in the database, and old orders still show in
  **Orders**, Transactions, reports and receipts under the customer's name. Nobody can log in as a customer any more, and any customer
  sign-ins still open are ended when the app starts. Nothing is deleted from the database.
- **Settings no longer needed:** `SD_AT_USERNAME`, `SD_AT_KEY`, `SD_AT_SENDER`, `SD_AT_ENV` and `SD_SMS_CONSOLE` (text messages) do nothing now and can be removed from Render.
- **If you ever want customers back**, the earlier version of the app (with customer sign-in, ordering, feedback and receipts) is the one to go back to.

## Payments and transactions

- **When entering a sale** staff choose **Cash**, **KCB Till (M-Pesa)** or part of each, and can type the M-Pesa confirmation code
  from the customer's payment message (now, or later when it is known).
- **The owner sets the till number** in the **Transactions** tab (or start the app with `SD_KCB_TILL=123456`).
- **Without the automatic setup below** the app cannot see M-Pesa, so it cannot confirm that money arrived by itself.
  A staff member or the owner checks the payment (cash in hand, or the code in the till's SMS / KCB statement)
  and presses **Received**. Until then the payment shows as "Not confirmed". **Not received** marks a payment that never came.
  A confirmed payment can't be changed afterwards, and it records who confirmed it and when.
  An M-Pesa code can only be used for one payment.
- **Transactions tab** (staff and owner; the owner can switch it off for staff in Access): the last 20 transactions first,
  totals confirmed by method, and **Show more** to page back through the whole history.
  Filter by method, status, dates, or search by name, phone, order number or M-Pesa code.
- Orders from before payments were recorded have no payment record and don't appear in Transactions.

## Automatic M-Pesa confirmation (optional)

It is **off until you set it up**; until then staff confirm by hand and nothing else changes.

When it is on:
1. A customer pays the till by M-Pesa. Safaricom tells the app about the payment.
2. Staff enter the M-Pesa code from the customer's message on the sale (when the sale is entered, or later by changing the payment).
   As soon as the code and a till notification for at least the right amount are both there, the payment turns **Paid** by itself,
   marked "confirmed automatically". It doesn't matter which arrives first.
3. If the customer paid too little, the payment stays "Not confirmed" with the reason, and staff decide.
   An underpayment is never confirmed automatically.

The payment prompt that used to pop up on the customer's phone is gone together with the customer side.

**Set-up (uses Safaricom's Daraja service):**
1. Register at developer.safaricom.co.ke, create an app, and get the consumer key and secret. Test in the sandbox first.
2. Your site needs a public **https** address (Safaricom can't reach localhost).
3. Start the app with:

```
SD_MPESA_ENV=sandbox            # change to production when you go live
SD_MPESA_KEY=...  SD_MPESA_SECRET=...
SD_MPESA_SHORTCODE=...          # your till/store number as registered with Safaricom
SD_MPESA_TILL=...               # your till number, if different from the shortcode
SD_PUBLIC_URL=https://your-site.example
python app.py
```

4. To receive till notifications, run `python app.py mpesa-register` once. The owner's **Transactions** tab also shows the two addresses Safaricom should use.
   Paybill instead of a Buy Goods till: add `SD_MPESA_TYPE=paybill`.

**Check before relying on it:** this was tested here against simulated Safaricom replies, not the live service.
Whether a till issued through KCB can be used with Daraja, and which shortcode to use for it, is for Safaricom or KCB to confirm.
Run a small real payment in the sandbox and then in production before you stop checking by hand.
The callbacks are protected only by the secret in their address (Safaricom doesn't sign them), so keep the addresses private.
A wrong or someone else's unused M-Pesa code typed in for the same amount could be confirmed by mistake, so check the code against the customer's message.

## PostgreSQL

Set `DATABASE_URL` and the app uses PostgreSQL instead of the SQLite file. Nothing else changes: it creates its own tables on first start
and upgrades them on later starts. Without `DATABASE_URL` it keeps using SQLite.

1. **Get a database.** Either use a hosted one (Render, Railway, Supabase, Neon... any gives you a connection address), or run one yourself:
   `SD_DB_PASSWORD=choose-a-strong-one docker compose up -d` (uses `docker-compose.yml`).
2. **Install and run:**

```
pip install -r requirements.txt
DATABASE_URL="postgresql://savour:YOUR-PASSWORD@127.0.0.1:5432/savour" SD_ADMIN_PASSWORD="choose-a-strong-one" python app.py
```

   Hosted databases often need `?sslmode=require` at the end of the address. `postgres://` addresses work too.
3. **Keep your existing data** (only if you have been using the SQLite file): start the app once on the old file with this latest version so it is upgraded,
   then, with `DATABASE_URL` set and an empty PostgreSQL database:

```
python app.py migrate-to-postgres saviour.db
```

   It copies staff, customers, menu, combos, orders, payments, purchases, expenses, price history and access settings, and refuses to run
   if the PostgreSQL database already holds customers or orders. Everyone has to log in again afterwards.
4. **Back up** with `pg_dump "$DATABASE_URL" > backup.sql` (most hosts also do this for you).

`SD_DB_POOL` (default 10) sets how many database connections the app keeps. For a live site, run it with a production server instead of `python app.py`:
`gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT` (one worker on purpose: the app keeps a few short-lived counters in memory and sets up the tables on start).

## Deploying on Render

1. Put the project on GitHub. Create a **PostgreSQL** database on Render, then a **Web Service** from the repo.
2. Web Service settings: **Build command** `pip install -r requirements.txt`; **Start command** `gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT`.
3. Under **Environment**, add:

| Name | Value |
|---|---|
| `DATABASE_URL` | the database's **Internal Database URL** (same region as the web service) |
| `SD_ADMIN_PASSWORD` | a strong owner password (used the first time only) |
| `SD_KCB_TILL` | your till number (optional; the owner can also set it in the app) |

   For automatic M-Pesa add `SD_PUBLIC_URL` (your Render address, `https://your-app.onrender.com`) and the `SD_MPESA_*` values listed above.
4. Don't set `SD_HOST` or `SD_PORT` (Render gives the port). Render serves the site over HTTPS.
5. The website files must be in a folder called `static` (lowercase `Static` also works). If the page says "Not Found", the folder is missing or misnamed in your repo.
6. Render's disk is wiped on every deploy, so keep everything in PostgreSQL, not the SQLite file. Check your database plan's expiry and backups on Render.
